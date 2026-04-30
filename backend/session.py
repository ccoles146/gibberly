import asyncio
import logging
import time
import uuid
from typing import Awaitable, Callable, Optional

log = logging.getLogger("gibberly.session")

from backend.stt import STTSession
from backend.llm_translator import LLMTranslator, ContentFilterError
from backend.tts import TTSSynthesizer, OpenAITTSSynthesizer
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
        openai_tts_endpoint: Optional[str] = None,
        openai_tts_api_key: Optional[str] = None,
        openai_tts_model: str = "gpt-4o-mini-tts",
        openai_tts_voice: str = "coral",
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
        self._chunk_count = 0
        self._start_time = time.monotonic()
        self._stopped = False

        self.listener_count: dict[str, int] = {}
        self.audio_active_count: dict[str, int] = {}
        self.paused: bool = False

        self._chunk_queue: asyncio.Queue[str] = asyncio.Queue()
        self._drain_task: Optional[asyncio.Task] = None

        self._publisher = PubSubPublisher(pubsub_cs)

        # One listener token per language
        self.listener_tokens: dict[str, str] = {
            lang["code"]: self._publisher.get_listener_token(self.session_id, lang["code"])
            for lang in target_languages
        }

        # One TTS synthesizer per language
        if openai_tts_endpoint and openai_tts_api_key:
            self._tts: dict[str, TTSSynthesizer | OpenAITTSSynthesizer] = {
                lang["code"]: OpenAITTSSynthesizer(
                    openai_tts_endpoint,
                    openai_tts_api_key,
                    voice=openai_tts_voice,
                    model=openai_tts_model,
                )
                for lang in target_languages
            }
            log.info(
                "Session %s — TTS: OpenAI (model=%s voice=%s)",
                self.session_id, openai_tts_model, openai_tts_voice,
            )
        else:
            self._tts = {
                lang["code"]: TTSSynthesizer(speech_key, speech_region, voice=lang["voice"])
                for lang in target_languages
            }
            log.info("Session %s — TTS: Azure Speech", self.session_id)

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
        log.info(
            "Session %s created — source=%s targets=%s",
            self.session_id,
            source_lang,
            [l["code"] for l in target_languages],
        )

    def _on_text(self, raw_src: str) -> None:
        """Called from STTSession thread — bridge to asyncio."""
        self._loop.call_soon_threadsafe(self._chunk_queue.put_nowait, raw_src)

    async def _drain_chunks(self) -> None:
        """Single consumer coroutine — serialises LLM calls so context is always coherent."""
        try:
            while True:
                raw_src = await self._chunk_queue.get()
                if self._stopped:
                    break
                await self._process_chunk(raw_src)
        except asyncio.CancelledError:
            log.info("Session %s — drain task cancelled", self.session_id)
        except Exception as exc:
            log.error("Session %s — drain task crashed: %s", self.session_id, exc, exc_info=True)
            raise

    async def _process_chunk(self, raw_src: str) -> None:
        if self._stopped or self.paused:
            log.debug(
                "Session %s — chunk ignored (%s): %r",
                self.session_id, "stopped" if self._stopped else "paused", raw_src[:40],
            )
            return

        self._chunk_count += 1
        chunk_num = self._chunk_count
        t0 = time.monotonic()
        log.debug("Session %s — chunk #%d begin: %r", self.session_id, chunk_num, raw_src[:60])

        try:
            result = await self._llm_translator.translate(raw_src)
            clean_src = result["clean_src"]
        except ContentFilterError as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.warning(
                "Session %s — chunk #%d skipped by content filter after %.0fms (%s). "
                "Context cleared — next chunk will process cleanly.",
                self.session_id, chunk_num, elapsed_ms, exc,
            )
            await self._send_status({"type": "content_filter_skip", "chunk": raw_src})
            return
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.error(
                "Session %s — chunk #%d LLM failed after %.0fms, falling back: %s",
                self.session_id, chunk_num, elapsed_ms, exc,
            )
            await self._send_status({"type": "llm_fallback", "chunk": raw_src})
            return

        if not clean_src:
            log.debug("Session %s — chunk #%d filtered to empty by LLM", self.session_id, chunk_num)
            return

        await self._send_status({
            "type": "phrase",
            "raw_src": raw_src,
            "clean_src": clean_src,
            "en_text": result.get("en_text", ""),
        })

        tone = result.get("tone", "calm")
        loop = asyncio.get_running_loop()

        async with self._tts_lock:
            for lang in self._target_languages:
                text = result.get(lang["llm_key"], "")
                if not text:
                    log.debug(
                        "Session %s — chunk #%d no translation for lang=%s",
                        self.session_id, chunk_num, lang["code"],
                    )
                    continue

                log.debug(
                    "Session %s — chunk #%d publishing phrase lang=%s",
                    self.session_id, chunk_num, lang["code"],
                )
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda lc=lang["code"], cs=clean_src, t=text: (
                                self._publisher.publish_phrase(self.session_id, lc, cs, t)
                            ),
                        ),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    log.error(
                        "Session %s — chunk #%d phrase publish TIMED OUT lang=%s after 5s — skipping",
                        self.session_id, chunk_num, lang["code"],
                    )
                except Exception as exc:
                    log.error(
                        "Session %s — chunk #%d phrase publish failed lang=%s: %s",
                        self.session_id, chunk_num, lang["code"], exc,
                    )

                audio_listeners = self.audio_active_count.get(lang["code"], 0)
                if audio_listeners > 0:
                    tts = self._tts[lang["code"]]
                    try:
                        def on_chunk(audio_bytes: bytes, lc=lang["code"]) -> None:
                            self._publisher.publish_audio(self.session_id, lc, audio_bytes)

                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda t=text, s=tts, oc=on_chunk, tn=tone: s.synthesize(t, oc, tone=tn),
                            ),
                            timeout=15.0,
                        )
                    except asyncio.TimeoutError:
                        log.error(
                            "Session %s — chunk #%d TTS TIMED OUT lang=%s tone=%s after 15s — skipping",
                            self.session_id, chunk_num, lang["code"], tone,
                        )
                    except Exception as exc:
                        log.error(
                            "Session %s — chunk #%d TTS failed lang=%s tone=%s: %s",
                            self.session_id, chunk_num, lang["code"], tone, exc,
                        )
                        await self._send_status({"type": "tts_error", "error": str(exc)})
                else:
                    log.debug(
                        "Session %s — chunk #%d TTS skipped lang=%s (no audio listeners)",
                        self.session_id, chunk_num, lang["code"],
                    )

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug("Session %s — chunk #%d done in %.0fms", self.session_id, chunk_num, elapsed_ms)

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def pause(self) -> None:
        log.info("Session %s — pausing", self.session_id)
        self.paused = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stt.pause_recognition)
        await loop.run_in_executor(
            None, lambda: self._publisher.broadcast_event(self.session_id, {"type": "paused"})
        )
        await self._send_status({"type": "paused"})

    async def resume(self) -> None:
        log.info("Session %s — resuming", self.session_id)
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
        log.info(
            "Session %s — listener joined lang=%s count=%d total=%d",
            self.session_id, lang, self.listener_count[lang], total,
        )
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def listener_leave(self, lang: str) -> int:
        self.listener_count[lang] = max(0, self.listener_count.get(lang, 0) - 1)
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        total = sum(self.listener_count.values())
        log.info(
            "Session %s — listener left lang=%s count=%d total=%d",
            self.session_id, lang, self.listener_count[lang], total,
        )
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def audio_join(self, lang: str) -> int:
        self.audio_active_count[lang] = self.audio_active_count.get(lang, 0) + 1
        log.info(
            "Session %s — audio unmuted lang=%s active_audio_listeners=%d",
            self.session_id, lang, self.audio_active_count[lang],
        )
        return self.audio_active_count[lang]

    def audio_leave(self, lang: str) -> int:
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        log.info(
            "Session %s — audio muted lang=%s active_audio_listeners=%d",
            self.session_id, lang, self.audio_active_count[lang],
        )
        return self.audio_active_count[lang]

    def start(self) -> None:
        self._drain_task = self._loop.create_task(self._drain_chunks())
        self._stt.start()

    def write(self, audio_bytes: bytes) -> None:
        self._stt.write(audio_bytes)

    def stop(self) -> None:
        self._stopped = True
        elapsed_s = time.monotonic() - self._start_time
        log.info(
            "Session %s stopping — duration=%.0fs chunks=%d listeners=%s",
            self.session_id, elapsed_s, self._chunk_count,
            dict(self.listener_count),
        )
        self._stt.stop()
        if self._drain_task is not None:
            self._loop.call_soon_threadsafe(self._drain_task.cancel)
        try:
            self._publisher.send_close(self.session_id)
        except Exception as exc:
            log.warning("Session %s — send_close failed (ignored): %s", self.session_id, exc)
