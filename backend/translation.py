from typing import Callable
import azure.cognitiveservices.speech as speechsdk

VOICE = "en-US-AndrewNeural"


class TranslationSession:
    """Wraps Azure Speech Translation+Synthesis for a single streaming session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_audio_chunk: Callable[[bytes], None],
    ):
        self._push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.translation.SpeechTranslationConfig(
            subscription=speech_key, region=speech_region
        )
        config.speech_recognition_language = "de-DE"
        config.add_target_language("en")
        config.voice_name = VOICE

        self._recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=config, audio_config=audio_config
        )
        self._recognizer.synthesizing.connect(
            lambda evt: self._on_synthesizing(evt, on_audio_chunk)
        )

    def _on_synthesizing(self, evt, on_audio_chunk: Callable[[bytes], None]) -> None:
        audio = evt.result.audio
        if audio:
            on_audio_chunk(audio)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
