import pytest
from unittest.mock import MagicMock, patch


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_returns_audio_bytes(mock_config, mock_synthesizer_class):
    import azure.cognitiveservices.speech as speechsdk

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b"RIFF...wav-bytes"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synthesizer_class.return_value = mock_synth

    from backend.tts import synthesize
    audio = synthesize("Hello world", speech_key="key", speech_region="westeurope")

    assert audio == b"RIFF...wav-bytes"
    mock_synth.speak_text_async.assert_called_once_with("Hello world")


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_raises_on_failure(mock_config, mock_synthesizer_class):
    import azure.cognitiveservices.speech as speechsdk

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.Canceled
    mock_result.cancellation_details.error_details = "quota exceeded"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synthesizer_class.return_value = mock_synth

    from backend.tts import synthesize
    with pytest.raises(RuntimeError, match="quota exceeded"):
        synthesize("Hello", speech_key="key", speech_region="westeurope")
