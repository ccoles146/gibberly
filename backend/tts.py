from typing import Callable
import azure.cognitiveservices.speech as speechsdk

_VOICE = "en-US-AndrewNeural"
_CHUNK_SIZE = 4096


class TTSSynthesizer:
    """Synthesizes English text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Calls on_audio_chunk(bytes) with each chunk as synthesis streams.
    """

    def __init__(self, speech_key: str, speech_region: str):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_synthesis_voice_name = _VOICE
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        )
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

    def synthesize(self, text: str, on_audio_chunk: Callable[[bytes], None]) -> None:
        result = self._synthesizer.speak_text_async(text).get()
        audio = result.audio_data  # bytes — no buffer-passing, works on all SDK versions
        for i in range(0, len(audio), _CHUNK_SIZE):
            on_audio_chunk(audio[i:i + _CHUNK_SIZE])
