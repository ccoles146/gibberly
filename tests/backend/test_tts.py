from unittest.mock import MagicMock, patch


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_streams_audio_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth

    mock_result = MagicMock()
    mock_future = MagicMock()
    mock_future.get.return_value = mock_result
    mock_synth.start_speaking_text_async.return_value = mock_future

    # read_data returns 4 bytes first call, 0 (end of stream) second call
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_stream.read_data.side_effect = [4, 0]

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("God is good.", chunks.append)

    assert len(chunks) == 1
    assert len(chunks[0]) == 4


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_emits_multiple_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth
    mock_future = MagicMock()
    mock_future.get.return_value = MagicMock()
    mock_synth.start_speaking_text_async.return_value = mock_future

    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_stream.read_data.side_effect = [2, 2, 2, 0]

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert len(chunks) == 3
    assert all(len(c) == 2 for c in chunks)


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_empty_stream_emits_no_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth
    mock_future = MagicMock()
    mock_future.get.return_value = MagicMock()
    mock_synth.start_speaking_text_async.return_value = mock_future

    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_stream.read_data.return_value = 0  # immediately empty

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert chunks == []


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_andrew_neural_voice(mock_config, mock_synth_class, mock_stream_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth
    mock_synth.start_speaking_text_async.return_value.get.return_value = MagicMock()
    mock_stream_class.return_value.read_data.return_value = 0

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    assert mock_config_instance.speech_synthesis_voice_name == "en-US-AndrewNeural"
