import threading
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk


class STTSession:
    """Azure Speech Recognizer (de-DE) with timer-based interim chunking.

    Calls on_text(chunk) with new German words every chunk_interval seconds
    from interim recognizing events, then flushes remaining words on the final
    recognized event.
    """

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_text: Callable[[str], None],
        chunk_interval: float = 1.5,
    ):
        self._on_text = on_text
        self._chunk_interval = chunk_interval
        self._lock = threading.Lock()
        self._interim_text = ""
        self._last_word_count = 0
        self._timer: Optional[threading.Timer] = None

        self._push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_recognition_language = "de-DE"
        config.set_property("Speech_SegmentationSilenceTimeoutMs", "500")

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )
        self._recognizer.recognizing.connect(self._on_recognizing)
        self._recognizer.recognized.connect(self._on_recognized)

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._timer is None:
                self._timer = threading.Timer(self._chunk_interval, self._dispatch)
                self._timer.daemon = True
                self._timer.start()

    def _dispatch(self) -> None:
        with self._lock:
            words = self._interim_text.split()
            new_words = words[self._last_word_count:]
            self._last_word_count = len(words)
            self._timer = None
        if new_words:
            self._on_text(" ".join(new_words))

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            final_words = evt.result.text.split()
            new_words = final_words[self._last_word_count:]
            self._last_word_count = 0
            self._interim_text = ""
        if new_words:
            self._on_text(" ".join(new_words))

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
