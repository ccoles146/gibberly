from unittest.mock import MagicMock, patch


def _make_synth_mock(audio_data: bytes):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.audio_data = audio_data
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    return mock_synth


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_streams_audio_chunks(mock_config, mock_synth_class):
    audio = bytes(range(256)) * 16  # 4096 bytes
    mock_synth_class.return_value = _make_synth_mock(audio)

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("God is good.", chunks.append)

    assert len(chunks) == 1
    assert chunks[0] == audio


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_splits_large_audio_into_chunks(mock_config, mock_synth_class):
    # 3 full chunks + 1 partial
    audio = bytes(range(256)) * 52  # 13312 bytes → 3 × 4096 + 1024
    mock_synth_class.return_value = _make_synth_mock(audio)

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello world.", chunks.append)

    assert len(chunks) == 4
    assert chunks[0] == audio[:4096]
    assert chunks[1] == audio[4096:8192]
    assert chunks[2] == audio[8192:12288]
    assert chunks[3] == audio[12288:]


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_empty_result_emits_no_chunks(mock_config, mock_synth_class):
    mock_synth_class.return_value = _make_synth_mock(b"")

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert chunks == []


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_andrew_neural_voice(mock_config, mock_synth_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth_class.return_value = _make_synth_mock(b"")

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    assert mock_config_instance.speech_synthesis_voice_name == "en-US-AndrewNeural"
