import threading
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk


class STTSession:
    """Azure Speech Recognizer (de-DE) with recognized-event dispatch.

    Dispatches full utterances on `recognized` events. A configurable time cap
    forces dispatch of interim text if no recognized event fires within the cap.
    """

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_text: Callable[[str], None],
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 4.0,
    ):
        self._on_text = on_text
        self._time_cap_s = time_cap_s
        self._lock = threading.Lock()
        self._interim_text = ""
        self._cap_timer: Optional[threading.Timer] = None

        self._push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_recognition_language = "de-DE"
        config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(silence_timeout_ms),
        )

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )
        self._recognizer.recognizing.connect(self._on_recognizing)
        self._recognizer.recognized.connect(self._on_recognized)

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._cap_timer is None:
                self._cap_timer = threading.Timer(self._time_cap_s, self._on_cap_timeout)
                self._cap_timer.daemon = True
                self._cap_timer.start()

    def _on_cap_timeout(self) -> None:
        with self._lock:
            text = self._interim_text
            self._interim_text = ""
            self._cap_timer = None
        if text.strip():
            self._on_text(text)

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            self._interim_text = ""
        text = evt.result.text
        if text.strip():
            self._on_text(text)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
