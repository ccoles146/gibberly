import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from backend.stt import STTSession
from backend.llm_translator import LLMTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates STT → LLM clean+translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 4.0,
        context_window: int = 5,
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
        self._tts_lock = asyncio.Lock()

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._llm_translator = LLMTranslator(
            openai_endpoint, openai_api_key, openai_deployment,
            context_window=context_window,
        )
        self._tts = TTSSynthesizer(speech_key, speech_region)
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            silence_timeout_ms=silence_timeout_ms,
            time_cap_s=time_cap_s,
        )

    def _on_text(self, raw_de: str) -> None:
        """Called from STTSession recognized/cap thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_de), self._loop
        )

    async def _process_chunk(self, raw_de: str) -> None:
        try:
            result = await self._llm_translator.translate(raw_de)
            clean_de = result["clean_de"]
            en_text = result["en_text"]
        except Exception:
            clean_de = raw_de
            en_text = raw_de
            await self._send_status({"type": "llm_fallback", "chunk": raw_de})

        if not en_text:
            return

        await self._send_status({
            "type": "phrase",
            "raw_de": raw_de,
            "clean_de": clean_de,
            "en_text": en_text,
        })

        loop = asyncio.get_running_loop()

        async with self._tts_lock:
            await loop.run_in_executor(
                None,
                lambda: self._publisher.publish_phrase(self.session_id, en_text),
            )

            try:
                def on_chunk(audio_bytes: bytes) -> None:
                    self._publisher.publish_audio(self.session_id, audio_bytes)

                await loop.run_in_executor(
                    None,
                    lambda: self._tts.synthesize(en_text, on_chunk),
                )
            except Exception as exc:
                await self._send_status({"type": "tts_error", "error": str(exc)})

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
