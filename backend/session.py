import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from backend.stt import STTSession
from backend.llm_cleaner import LLMCleaner
from backend.text_translator import TextTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates STT → LLM clean → translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        translator_key: str,
        translator_region: str,
        chunk_interval: float = 1.5,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        on_status: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.session_id = str(uuid.uuid4())
        if loop is None:
            raise TypeError(
                "SessionHandler requires an explicit event loop. "
                "Pass the running loop via loop=asyncio.get_running_loop()."
            )
        self._loop = loop
        self._on_status = on_status
        self.listener_count = 0

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._cleaner = LLMCleaner(openai_endpoint, openai_api_key, openai_deployment)
        self._translator = TextTranslator(translator_key, translator_region)
        self._tts = TTSSynthesizer(speech_key, speech_region)
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            chunk_interval=chunk_interval,
        )

    def _on_text(self, raw_de: str) -> None:
        """Called from STTSession timer/recognized thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_de), self._loop
        )

    async def _process_chunk(self, raw_de: str) -> None:
        try:
            clean_de = await self._cleaner.clean(raw_de)
        except Exception:
            clean_de = raw_de
            await self._send_status({"type": "llm_fallback", "chunk": raw_de})

        if not clean_de:
            return

        en_text = await self._translator.translate(clean_de)
        if not en_text:
            await self._send_status({"type": "translator_error", "chunk": clean_de})
            return

        await self._send_status({
            "type": "phrase",
            "raw_de": raw_de,
            "clean_de": clean_de,
            "text": en_text,
        })

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_phrase(self.session_id, en_text),
        )
        await loop.run_in_executor(
            None,
            lambda: self._tts.synthesize(
                en_text,
                lambda chunk: asyncio.run_coroutine_threadsafe(
                    self._publish_chunk(chunk), loop
                ),
            ),
        )

    async def _publish_chunk(self, audio_bytes: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_audio(self.session_id, audio_bytes),
        )

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except Exception:
                pass

    def listener_join(self) -> int:
        self.listener_count += 1
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def listener_leave(self) -> int:
        self.listener_count = max(0, self.listener_count - 1)
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def start(self) -> None:
        self._stt.start()

    def write(self, audio_bytes: bytes) -> None:
        self._stt.write(audio_bytes)

    def stop(self) -> None:
        self._stt.stop()
        self._publisher.send_close(self.session_id)
