from unittest.mock import MagicMock, patch, call
import azure.cognitiveservices.speech as speechsdk


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_connects_synthesizing_event(mock_config, mock_synth_class):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello", lambda c: None)

    mock_synth.synthesizing.connect.assert_called_once()
    mock_synth.synthesizing.disconnect_all.assert_called_once()


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_streams_chunks_via_event(mock_config, mock_synth_class):
    chunks_received = []
    chunk_a = b"\x01\x02\x03"
    chunk_b = b"\x04\x05\x06"

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result

    registered_callback = None

    def capture_connect(cb):
        nonlocal registered_callback
        registered_callback = cb

    mock_synth.synthesizing.connect.side_effect = capture_connect

    def simulate_synthesis():
        evt_a = MagicMock()
        evt_a.result.audio_data = chunk_a
        evt_b = MagicMock()
        evt_b.result.audio_data = chunk_b
        registered_callback(evt_a)
        registered_callback(evt_b)
        return mock_result

    mock_synth.speak_text_async.return_value.get.side_effect = simulate_synthesis

    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello world", chunks_received.append)

    assert chunks_received == [chunk_a, chunk_b]


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_skips_empty_audio_data(mock_config, mock_synth_class):
    chunks_received = []

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result

    registered_callback = None

    def capture_connect(cb):
        nonlocal registered_callback
        registered_callback = cb

    mock_synth.synthesizing.connect.side_effect = capture_connect

    def simulate_synthesis():
        evt = MagicMock()
        evt.result.audio_data = b""
        registered_callback(evt)
        return mock_result

    mock_synth.speak_text_async.return_value.get.side_effect = simulate_synthesis
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello", chunks_received.append)

    assert chunks_received == []


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_raises_on_failure(mock_config, mock_synth_class):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.Canceled
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth.synthesizing.connect.side_effect = lambda cb: None
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
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth.synthesizing.connect.side_effect = lambda cb: None
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    assert mock_config_instance.speech_synthesis_voice_name == "en-US-AndrewNeural"
