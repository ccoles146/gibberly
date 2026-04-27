import logging
import threading
import time
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk

log = logging.getLogger("gibberly.stt")


class STTSession:
    """Azure Speech Recognizer with recognized-event dispatch and auto-reconnect.

    Dispatches full utterances on `recognized` events. A configurable time cap
    forces dispatch of interim text if no recognized event fires within the cap.

    Cap-timer / recognized deduplication
    ─────────────────────────────────────
    Azure's `recognizing` events return the *cumulative* interim text for the
    current utterance.  When the cap timer fires mid-utterance it dispatches the
    portion not yet sent and records it in `_total_dispatched`.  When `recognized`
    fires we must strip that already-sent prefix from the final text.

    The tricky part: Azure often *reformulates* text between interim and final
    events — punctuation, capitalisation, minor word changes.  Exact-string prefix
    matching therefore fails frequently, causing the entire utterance to be re-sent.

    We use word-count-based stripping as the primary strategy:

        skip the first N words of the recognised text, where N = number of words
        in `_total_dispatched`.

    Exact-string match is tried first (zero-cost, handles the common case); the
    word-count fallback handles reformulation.  If the recognised text is shorter
    than what was already dispatched (very rare reformulation), we return nothing.
    """

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_text: Callable[[str], None],
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 4.0,
        language: str = "de-DE",
    ):
        self._on_text = on_text
        self._time_cap_s = time_cap_s
        self._language = language
        self._speech_key = speech_key
        self._speech_region = speech_region
        self._silence_timeout_ms = silence_timeout_ms

        self._lock = threading.Lock()
        self._interim_text = ""
        self._total_dispatched = ""
        self._cap_timer: Optional[threading.Timer] = None
        self._running = False
        self._reconnect_attempts = 0
        self._session_start_time: Optional[float] = None

        self._push_stream = speechsdk.audio.PushAudioInputStream()
        self._recognizer = self._build_recognizer()

    # ── Recognizer construction ───────────────────────────────────────────────

    def _build_recognizer(self) -> speechsdk.SpeechRecognizer:
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)
        config = speechsdk.SpeechConfig(
            subscription=self._speech_key, region=self._speech_region
        )
        config.speech_recognition_language = self._language
        config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(self._silence_timeout_ms),
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )
        recognizer.session_started.connect(self._on_session_started)
        recognizer.recognizing.connect(self._on_recognizing)
        recognizer.recognized.connect(self._on_recognized)
        recognizer.canceled.connect(self._on_canceled)
        recognizer.session_stopped.connect(self._on_session_stopped)
        return recognizer

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _tail_after_dispatched(full_text: str, already_sent: str) -> str:
        """Return the portion of full_text not covered by already_sent.

        Strategy:
        1. Exact-string prefix match (fast, handles identical text).
        2. Word-count skip (handles Azure reformulation between interim/final).
        """
        if not already_sent:
            return full_text

        # Strategy 1: exact prefix
        if full_text.startswith(already_sent):
            return full_text[len(already_sent):].strip()

        # Strategy 2: skip by word count
        full_words = full_text.split()
        sent_word_count = len(already_sent.split())
        if sent_word_count >= len(full_words):
            return ""  # recognised text adds nothing new
        return " ".join(full_words[sent_word_count:]).strip()

    # ── SDK event callbacks ───────────────────────────────────────────────────

    def _on_session_started(self, evt) -> None:
        self._session_start_time = time.monotonic()
        log.info(
            "Azure STT session established — language=%s silence_timeout=%dms cap=%.1fs",
            self._language,
            self._silence_timeout_ms,
            self._time_cap_s,
        )

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._cap_timer is None:
                self._cap_timer = threading.Timer(self._time_cap_s, self._on_cap_timeout)
                self._cap_timer.daemon = True
                self._cap_timer.start()
                log.debug("STT cap timer started (%.1fs) — interim: %r", self._time_cap_s, evt.result.text[:60])

    def _on_cap_timeout(self) -> None:
        with self._lock:
            full_interim = self._interim_text
            already_sent = self._total_dispatched
            new_part = self._tail_after_dispatched(full_interim, already_sent)
            if new_part:
                self._total_dispatched = full_interim
            self._cap_timer = None
        if new_part:
            log.debug("STT cap dispatch (%d words): %r", len(new_part.split()), new_part[:80])
            self._on_text(new_part)

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            if evt.result.reason == speechsdk.ResultReason.NoMatch:
                log.debug("STT no-match — NoSpeech or low confidence")
            return
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            already_sent = self._total_dispatched
            self._interim_text = ""
            self._total_dispatched = ""

        text = self._tail_after_dispatched(evt.result.text, already_sent)
        if text:
            log.info("STT recognized (%d words): %r", len(text.split()), text[:100])
            self._on_text(text)
        else:
            log.debug("STT recognized but fully covered by cap dispatch — skipping")

    def _on_canceled(self, evt) -> None:
        details = evt.cancellation_details
        reason_name = details.reason.name if hasattr(details.reason, "name") else str(details.reason)
        code_name = details.error_code.name if hasattr(details.error_code, "name") else str(details.error_code)

        if details.reason == speechsdk.CancellationReason.Error:
            log.error(
                "STT canceled — reason=%s code=%s details=%s",
                reason_name, code_name, details.error_details,
            )
            if self._running:
                log.info("STT scheduling reconnect in 1s (attempt %d)", self._reconnect_attempts + 1)
                t = threading.Timer(1.0, self._reconnect)
                t.daemon = True
                t.start()
        else:
            # EndOfStream on normal stop — not an error
            log.info("STT canceled (normal) — reason=%s", reason_name)

    def _on_session_stopped(self, evt) -> None:
        elapsed = ""
        if self._session_start_time is not None:
            secs = time.monotonic() - self._session_start_time
            elapsed = f" after {secs:.0f}s"
        log.info("STT session stopped%s (running=%s)", elapsed, self._running)

    def _reconnect(self) -> None:
        with self._lock:
            if not self._running:
                return
        self._reconnect_attempts += 1
        log.info("STT reconnecting (language=%s attempt=%d)…", self._language, self._reconnect_attempts)
        t0 = time.monotonic()
        try:
            self._recognizer.start_continuous_recognition()
            log.info("STT reconnected successfully in %.0fms", (time.monotonic() - t0) * 1000)
        except Exception as exc:
            log.error("STT reconnect failed (attempt=%d): %s", self._reconnect_attempts, exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        log.info("STT starting continuous recognition (language=%s)", self._language)
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
        log.info("STT stopping")
        try:
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            pass
        self._push_stream.close()
        log.info("STT stopped (total reconnects=%d)", self._reconnect_attempts)

    def pause_recognition(self) -> None:
        log.info("STT pausing recognition")
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            self._interim_text = ""
            self._total_dispatched = ""
        try:
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            pass

    def resume_recognition(self) -> None:
        log.info("STT resuming recognition")
        with self._lock:
            self._interim_text = ""
            self._total_dispatched = ""
        self._recognizer.start_continuous_recognition()
