import logging
import threading
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk

log = logging.getLogger("gibberly")


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

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._cap_timer is None:
                self._cap_timer = threading.Timer(self._time_cap_s, self._on_cap_timeout)
                self._cap_timer.daemon = True
                self._cap_timer.start()

    def _on_cap_timeout(self) -> None:
        with self._lock:
            full_interim = self._interim_text
            already_sent = self._total_dispatched
            new_part = self._tail_after_dispatched(full_interim, already_sent)
            if new_part:
                self._total_dispatched = full_interim
            self._cap_timer = None
        if new_part:
            self._on_text(new_part)

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
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
            self._on_text(text)

    def _on_canceled(self, evt) -> None:
        details = evt.cancellation_details
        log.warning(
            "STT canceled — reason: %s, code: %s, details: %s",
            details.reason, details.error_code, details.error_details,
        )
        # Reconnect on service/network errors only.
        # EndOfStream fires on normal stop (stop_continuous_recognition / stream close) — don't reconnect.
        if details.reason == speechsdk.CancellationReason.Error and self._running:
            log.info("STT error cancellation — scheduling reconnect in 1 s")
            t = threading.Timer(1.0, self._reconnect)
            t.daemon = True
            t.start()

    def _on_session_stopped(self, evt) -> None:
        # Fires on both explicit stop (pause / stop) and unexpected stops.
        # Do NOT reconnect here — pause_recognition calls stop_continuous_recognition_async,
        # which also fires this event with _running=True. Reconnection is handled exclusively
        # by _on_canceled for genuine error cases.
        log.info("STT session stopped (running=%s)", self._running)

    def _reconnect(self) -> None:
        with self._lock:
            if not self._running:
                return
        log.info("STT reconnecting (language=%s)…", self._language)
        try:
            self._recognizer.start_continuous_recognition()
            log.info("STT reconnected successfully")
        except Exception as exc:
            log.error("STT reconnect failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
        try:
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            pass
        self._push_stream.close()

    def pause_recognition(self) -> None:
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
        with self._lock:
            self._interim_text = ""
            self._total_dispatched = ""
        self._recognizer.start_continuous_recognition()
