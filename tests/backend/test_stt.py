import threading
import time
from unittest.mock import MagicMock, patch


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
def test_stt_recognized_dispatches_full_text(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    evt.result.text = "Das ist gut und schön"
    session._on_recognized(evt)

    assert dispatched == ["Das ist gut und schön"]


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

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.NoMatch
    evt.result.text = ""
    session._on_recognized(evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_empty_text_skipped(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    evt.result.text = ""
    session._on_recognized(evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_time_cap_dispatches_interim_text(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,
    )

    evt = MagicMock()
    evt.result.text = "Das ist ein langer Satz"
    session._on_recognizing(evt)

    time.sleep(0.3)

    assert dispatched == ["Das ist ein langer Satz"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_cancels_time_cap(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.5,
    )

    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)

    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Das ist gut und schön"
    session._on_recognized(final_evt)

    time.sleep(0.7)

    assert dispatched == ["Das ist gut und schön"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_time_cap_clears_interim_after_dispatch(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,
    )

    evt = MagicMock()
    evt.result.text = "Erster Satz"
    session._on_recognizing(evt)
    time.sleep(0.3)

    assert dispatched == ["Erster Satz"]

    time.sleep(0.3)
    assert dispatched == ["Erster Satz"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_silence_timeout_configured(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_config_instance = MagicMock()
    mock_config_class.return_value = mock_config_instance
    mock_recognizer_class.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession(
        speech_key="k", speech_region="r",
        on_text=lambda t: None,
        silence_timeout_ms=1500,
    )

    import azure.cognitiveservices.speech as speechsdk
    mock_config_instance.set_property.assert_any_call(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "1500"
    )
