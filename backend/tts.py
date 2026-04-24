from typing import Callable
import azure.cognitiveservices.speech as speechsdk
from openai import OpenAI

# Tone → natural-language voice instruction for gpt-4o-mini-tts.
# Uses OpenAI's `instructions` parameter — SSML is not supported by this model.
_TONE_INSTRUCTIONS: dict[str, str] = {
    "calm":        "Speak gently and evenly with quiet warmth. Unhurried, steady pace.",
    "warm":        "Speak with pastoral warmth and genuine care. Natural, conversational tone.",
    "urgent":      "Speak with urgency and conviction. Slightly faster pace, words carry weight.",
    "emphatic":    "Speak with deliberate emphasis on key words. Authoritative but not harsh.",
    "joyful":      "Speak brightly, with life and celebration in the voice.",
    "solemn":      "Speak slowly and gravely. Quiet reverence, weighted pauses.",
    "questioning": "Slightly open, inviting tone. Raise inflection at key moments of reflection.",
}


class TTSSynthesizer:
    """Synthesizes text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Returns one complete MP3 blob via on_audio_chunk once synthesis finishes.
    The tone argument is accepted for interface parity but ignored.
    """

    def __init__(self, speech_key: str, speech_region: str, voice: str = "en-US-AndrewNeural"):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_synthesis_voice_name = voice
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

    def synthesize(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None],
        tone: str = "calm",
    ) -> None:
        result = self._synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"TTS failed: {result.reason}")
        if result.audio_data:
            on_audio_chunk(result.audio_data)


class OpenAITTSSynthesizer:
    """Synthesizes text using a configurable OpenAI TTS model via Azure OpenAI.

    Uses the v1 API (api_version='v1') — no dated version string required.
    synthesize() is synchronous — run it in a thread executor.
    Voice instructions are derived from the tone argument.
    Note: SSML is not supported; this model uses natural-language instructions.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        voice: str = "coral",
        model: str = "gpt-4o-mini-tts",
    ):
        self._client = OpenAI(
            api_key=api_key,
            base_url=endpoint.rstrip("/") + "/openai/v1",
        )
        self._voice = voice
        self._model = model

    def synthesize(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None],
        tone: str = "calm",
    ) -> None:
        instructions = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["calm"])
        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            instructions=instructions,
        )
        audio_bytes = response.content
        if audio_bytes:
            on_audio_chunk(audio_bytes)
