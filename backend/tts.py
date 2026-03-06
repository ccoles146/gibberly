import azure.cognitiveservices.speech as speechsdk

VOICE = "en-US-JennyNeural"


def synthesize(text: str, speech_key: str, speech_region: str) -> bytes:
    """Synthesise English text to WAV bytes using Azure Neural TTS."""
    config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    config.speech_synthesis_voice_name = VOICE
    # audio_config=None → output to memory (result.audio_data)
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    result = synth.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data

    raise RuntimeError(
        f"TTS failed: {result.cancellation_details.error_details}"
    )
