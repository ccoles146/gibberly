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
        result_future = self._synthesizer.start_speaking_text_async(text)
        result = result_future.get()
        audio_stream = speechsdk.AudioDataStream(result)
        buffer = bytearray(_CHUNK_SIZE)
        while True:
            filled = audio_stream.read_data(buffer)
            if filled == 0:
                break
            on_audio_chunk(bytes(buffer[:filled]))
