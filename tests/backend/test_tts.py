from unittest.mock import MagicMock, patch
import azure.cognitiveservices.speech as speechsdk


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_publishes_complete_audio(mock_config, mock_synth_class):
    """Complete audio_data from the result is passed to the callback once."""
    complete_audio = b"\xff\xfb" + b"\x00" * 100

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = complete_audio
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    chunks_received = []
    synth.synthesize("Hello", chunks_received.append)

    assert chunks_received == [complete_audio]


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_skips_empty_result(mock_config, mock_synth_class):
    """Empty audio_data in result does not invoke the callback."""
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b""
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    chunks_received = []
    synth.synthesize("Hello", chunks_received.append)

    assert chunks_received == []


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_raises_on_failure(mock_config, mock_synth_class):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.Canceled
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    import pytest
    with pytest.raises(RuntimeError, match="TTS failed"):
        synth.synthesize("Hello", lambda c: None)


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_andrew_neural_voice(mock_config, mock_synth_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b"\x00"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    assert mock_config_instance.speech_synthesis_voice_name == "en-US-AndrewNeural"


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_custom_voice(mock_config, mock_synth_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b"\x00"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope", voice="es-ES-ElviraNeural")

    assert mock_config_instance.speech_synthesis_voice_name == "es-ES-ElviraNeural"


# ── OpenAITTSSynthesizer ────────────────────────────────────────────────────

@patch("backend.tts.OpenAI")
def test_openai_tts_synthesize_returns_audio(mock_client_class):
    """Audio bytes from the API response are passed to the callback."""
    audio_bytes = b"\xff\xfb" + b"\x00" * 200
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = audio_bytes

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key")
    received = []
    synth.synthesize("God loves you", received.append)

    assert received == [audio_bytes]


@patch("backend.tts.OpenAI")
def test_openai_tts_passes_tone_as_instructions(mock_client_class):
    """The tone argument is mapped to a non-empty instructions string."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = b"\x00"

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key")
    synth.synthesize("Hallelujah", lambda _: None, tone="joyful")

    call_kwargs = mock_client.audio.speech.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini-tts"
    assert len(call_kwargs["instructions"]) > 10


@patch("backend.tts.OpenAI")
def test_openai_tts_uses_configurable_model(mock_client_class):
    """The model name is taken from the constructor argument, not hardcoded."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = b"\x00"

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key", model="gpt-4o-tts")
    synth.synthesize("Test", lambda _: None)

    call_kwargs = mock_client.audio.speech.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-tts"
