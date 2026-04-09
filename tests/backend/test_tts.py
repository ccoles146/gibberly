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

    # read_data fills buffer with 4 bytes first call, returns 0 second call
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    call_count = 0

    def fake_read(buf):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            buf[:4] = bytearray([0xFF, 0xFE, 0x00, 0x01])
            return 4
        return 0

    mock_stream.read_data.side_effect = fake_read

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("God is good.", chunks.append)

    assert len(chunks) == 1
    assert chunks[0] == bytes([0xFF, 0xFE, 0x00, 0x01])


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
    call_count = 0

    def fake_read(buf):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            buf[:2] = bytearray([call_count, call_count])
            return 2
        return 0

    mock_stream.read_data.side_effect = fake_read

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert len(chunks) == 3
    assert chunks[0] == bytes([1, 1])
    assert chunks[1] == bytes([2, 2])
    assert chunks[2] == bytes([3, 3])


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
