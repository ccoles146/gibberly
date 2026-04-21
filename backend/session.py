import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Optional

log = logging.getLogger("gibberly")

from backend.stt import STTSession
from backend.llm_translator import LLMTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher
from backend.languages import SUPPORTED_LANGUAGES, get_target_languages


class SessionHandler:
    """Orchestrates STT → LLM interpret+translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        target_languages: list[dict],
        source_lang: str = "de-DE",
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 8.0,
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
        self.source_lang = source_lang
        self._target_languages = target_languages
        self._tts_lock = asyncio.Lock()

        self.listener_count: dict[str, int] = {}
        self.audio_active_count: dict[str, int] = {}
        self.paused: bool = False

        self._publisher = PubSubPublisher(pubsub_cs)

        # One listener token per language
        self.listener_tokens: dict[str, str] = {
            lang["code"]: self._publisher.get_listener_token(self.session_id, lang["code"])
            for lang in target_languages
        }

        # One TTS synthesizer per language
        self._tts: dict[str, TTSSynthesizer] = {
            lang["code"]: TTSSynthesizer(speech_key, speech_region, voice=lang["voice"])
            for lang in target_languages
        }

        self._llm_translator = LLMTranslator(
            openai_endpoint, openai_api_key, openai_deployment,
            target_languages=target_languages,
            context_window=context_window,
        )
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            silence_timeout_ms=silence_timeout_ms,
            time_cap_s=time_cap_s,
            language=source_lang,
        )

    def _on_text(self, raw_src: str) -> None:
        """Called from STTSession thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_src), self._loop
        )

    async def _process_chunk(self, raw_src: str) -> None:
        if self.paused:
            return
        try:
            result = await self._llm_translator.translate(raw_src)
            clean_src = result["clean_src"]
        except Exception:
            await self._send_status({"type": "llm_fallback", "chunk": raw_src})
            return

        if not clean_src:
            return

        await self._send_status({
            "type": "phrase",
            "raw_src": raw_src,
            "clean_src": clean_src,
            "en_text": result.get("en_text", ""),
        })

        loop = asyncio.get_running_loop()

        async with self._tts_lock:
            for lang in self._target_languages:
                text = result.get(lang["llm_key"], "")
                if not text:
                    continue

                await loop.run_in_executor(
                    None,
                    lambda lc=lang["code"], cs=clean_src, t=text: (
                        self._publisher.publish_phrase(self.session_id, lc, cs, t)
                    ),
                )

                if self.audio_active_count.get(lang["code"], 0) > 0:
                    tts = self._tts[lang["code"]]
                    try:
                        def on_chunk(audio_bytes: bytes, lc=lang["code"]) -> None:
                            self._publisher.publish_audio(self.session_id, lc, audio_bytes)

                        await loop.run_in_executor(
                            None,
                            lambda t=text, s=tts, oc=on_chunk: s.synthesize(t, oc),
                        )
                    except Exception as exc:
                        await self._send_status({"type": "tts_error", "error": str(exc)})

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except Exception:
                pass

    async def pause(self) -> None:
        self.paused = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stt.pause_recognition)
        await loop.run_in_executor(
            None, lambda: self._publisher.broadcast_event(self.session_id, {"type": "paused"})
        )
        await self._send_status({"type": "paused"})

    async def resume(self) -> None:
        self.paused = False
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stt.resume_recognition)
        await loop.run_in_executor(
            None, lambda: self._publisher.broadcast_event(self.session_id, {"type": "resumed"})
        )
        await self._send_status({"type": "resumed"})

    def listener_join(self, lang: str) -> int:
        self.listener_count[lang] = self.listener_count.get(lang, 0) + 1
        total = sum(self.listener_count.values())
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def listener_leave(self, lang: str) -> int:
        self.listener_count[lang] = max(0, self.listener_count.get(lang, 0) - 1)
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        total = sum(self.listener_count.values())
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def audio_join(self, lang: str) -> int:
        self.audio_active_count[lang] = self.audio_active_count.get(lang, 0) + 1
        return self.audio_active_count[lang]

    def audio_leave(self, lang: str) -> int:
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        return self.audio_active_count[lang]

    def start(self) -> None:
        self._stt.start()

    def write(self, audio_bytes: bytes) -> None:
        self._stt.write(audio_bytes)

    def stop(self) -> None:
        self._stt.stop()
        try:
            self._publisher.send_close(self.session_id)
        except Exception as exc:
            log.warning("send_close failed (ignored): %s", exc)
