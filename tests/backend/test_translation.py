import pytest
from unittest.mock import MagicMock, patch


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
@patch("backend.translation.speechsdk.audio.AudioStreamFormat")
def test_session_starts_continuous_recognition(
    mock_audio_fmt, mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.translation import TranslationSession
    session = TranslationSession(speech_key="k", speech_region="r", on_translation=lambda t: None)
    session.start()

    mock_recognizer.start_continuous_recognition.assert_called_once()


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
@patch("backend.translation.speechsdk.audio.AudioStreamFormat")
def test_write_pushes_bytes_to_stream(
    mock_audio_fmt, mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream

    from backend.translation import TranslationSession
    session = TranslationSession(speech_key="k", speech_region="r", on_translation=lambda t: None)
    session.write(b"\x01\x02\x03")

    mock_stream.write.assert_called_once_with(b"\x01\x02\x03")


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
@patch("backend.translation.speechsdk.audio.AudioStreamFormat")
def test_recognized_callback_fires_on_translation(
    mock_audio_fmt, mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    captured = []
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.translation import TranslationSession
    session = TranslationSession(
        speech_key="k", speech_region="r", on_translation=captured.append
    )

    # Simulate the SDK firing the recognized event
    evt = MagicMock()
    evt.result.translations = {"en": "Peace be with you"}
    # Grab the handler registered via recognizer.recognized.connect(handler)
    handler = mock_recognizer.recognized.connect.call_args[0][0]
    handler(evt)

    assert captured == ["Peace be with you"]
