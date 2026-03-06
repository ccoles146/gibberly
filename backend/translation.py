from typing import Callable
import azure.cognitiveservices.speech as speechsdk


class TranslationSession:
    """Wraps Azure Speech Translation for a single streaming session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_translation: Callable[[str], None],
    ):
        fmt = speechsdk.audio.AudioStreamFormat.get_wave_format_pcm(16000, 16, 1)
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.translation.SpeechTranslationConfig(
            subscription=speech_key, region=speech_region
        )
        config.speech_recognition_language = "de-DE"
        config.add_target_language("en")

        self._recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=config, audio_config=audio_config
        )
        self._recognizer.recognized.connect(
            lambda evt: self._on_recognized(evt, on_translation)
        )

    def _on_recognized(self, evt, on_translation: Callable[[str], None]) -> None:
        translation = evt.result.translations.get("en", "")
        if translation:
            on_translation(translation)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
