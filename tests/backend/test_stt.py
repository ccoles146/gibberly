import threading
from unittest.mock import MagicMock, patch, call


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_starts_continuous_recognition(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.start()

    mock_recognizer.start_continuous_recognition.assert_called_once()


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_write_pushes_bytes(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer_class.return_value = MagicMock()

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.write(b"\x01\x02\x03")

    mock_stream.write.assert_called_once_with(b"\x01\x02\x03")


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_dispatch_sends_new_words_only(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # Simulate recognizing event with 3 words
    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)

    # First dispatch sends all 3 words
    session._dispatch()
    assert dispatched == ["Das ist gut"]

    # More words arrive in next interim result
    evt2 = MagicMock()
    evt2.result.text = "Das ist gut und schön"
    session._on_recognizing(evt2)

    session._dispatch()
    assert dispatched == ["Das ist gut", "und schön"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_flushes_remaining_words(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # 3 words already dispatched (cursor at 3)
    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)
    session._dispatch()  # sends "Das ist gut", cursor=3

    # recognized fires with 5 words total — only last 2 are new
    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Das ist gut und schön"
    session._on_recognized(final_evt)

    assert dispatched == ["Das ist gut", "und schön"]
    # cursor reset to 0
    assert session._last_word_count == 0


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_non_speech_skipped(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.NoMatch
    final_evt.result.text = ""
    session._on_recognized(final_evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_dispatch_skips_when_no_new_words(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # dispatch fires but no interim text yet
    session._dispatch()
    assert dispatched == []
