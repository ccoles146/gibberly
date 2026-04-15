from typing import Callable
import azure.cognitiveservices.speech as speechsdk

_VOICE = "en-US-AndrewNeural"


class TTSSynthesizer:
    """Synthesizes English text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Returns one complete MP3 blob via on_audio_chunk once synthesis finishes.
    Using the completed result (not the synthesizing event) guarantees the
    blob is a self-contained, decodable MP3 file on the receiver side.
    """

    def __init__(self, speech_key: str, speech_region: str):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_synthesis_voice_name = _VOICE
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

    def synthesize(self, text: str, on_audio_chunk: Callable[[bytes], None]) -> None:
        result = self._synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"TTS failed: {result.reason}")
        if result.audio_data:
            on_audio_chunk(result.audio_data)
