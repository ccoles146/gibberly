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
