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


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_strips_cap_timer_prefix(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    """When cap timer fires first, recognized should only dispatch the new tail.

    Azure's recognizing events return the full utterance-so-far, so when the cap
    timer dispatches "A B C" and recognized later fires with "A B C D E", we must
    not re-speak "A B C" — only "D E" should be dispatched.
    """
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,
    )

    # Interim fires — cap timer starts
    interim_evt = MagicMock()
    interim_evt.result.text = "Und erst nach zweieinhalb Tagen als plötzlich"
    session._on_recognizing(interim_evt)

    time.sleep(0.3)  # cap fires → dispatches the interim text
    assert len(dispatched) == 1
    assert dispatched[0] == "Und erst nach zweieinhalb Tagen als plötzlich"

    # Recognized fires with the FULL utterance (superset of interim)
    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Und erst nach zweieinhalb Tagen als plötzlich der Friede da ist"
    session._on_recognized(final_evt)

    # Only the new tail should be dispatched — not the full sentence again
    assert len(dispatched) == 2
    assert dispatched[1] == "der Friede da ist"


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_word_count_fallback_on_reformulation(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    """When Azure reformulates (exact prefix doesn't match), word-count stripping
    must be used so we don't re-dispatch the whole utterance.

    This is the primary cause of phrase repetition in live sessions: the recognised
    text has different capitalisation/punctuation from the interim, so exact prefix
    matching fails.  Word-count fallback strips the right number of words instead.
    """
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,
    )

    # Interim has lower-case / no punctuation (typical for Azure interim events)
    interim_evt = MagicMock()
    interim_evt.result.text = "petrus will nicht dass wir stolpern"
    session._on_recognizing(interim_evt)

    time.sleep(0.3)
    assert dispatched == ["petrus will nicht dass wir stolpern"]

    # Final is reformulated: capitalised, punctuated, extra words appended
    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Petrus will nicht, dass wir stolpern, Petrus will nicht, dass wir hängen bleiben."
    session._on_recognized(final_evt)

    # Exact prefix fails (capitalisation diff) → word-count strips first 6 words
    # → only the new tail is dispatched, NOT the full sentence again
    assert len(dispatched) == 2
    tail = dispatched[1]
    assert "stolpern" not in tail  # "stolpern" was in the cap-dispatched part
    assert "hängen" in tail or "bleiben" in tail  # new content is present


def test_tail_after_dispatched_exact_prefix():
    from backend.stt import STTSession
    result = STTSession._tail_after_dispatched(
        "Das ist gut und schön.", "Das ist gut"
    )
    assert result == "und schön."


def test_tail_after_dispatched_word_count_fallback():
    """Reformulated final text: exact prefix fails → word count strips correctly."""
    from backend.stt import STTSession
    # Interim (already_sent) has 5 words.  Final has 8 words with minor differences.
    result = STTSession._tail_after_dispatched(
        "Petrus will nicht, dass wir stolpern weiter.",   # 7 words
        "petrus will nicht dass wir",                      # 5 words (exact fails)
    )
    words = result.split()
    assert len(words) == 2  # last 2 words of the 7-word final text


def test_tail_after_dispatched_nothing_new():
    """Recognised text is entirely covered by what was already dispatched."""
    from backend.stt import STTSession
    result = STTSession._tail_after_dispatched(
        "Das ist gut.",     # 3 words
        "Das ist gut schön",  # 4 words — sent more than recognised
    )
    assert result == ""


def test_tail_after_dispatched_no_prior_dispatch():
    from backend.stt import STTSession
    result = STTSession._tail_after_dispatched("Das ist gut.", "")
    assert result == "Das ist gut."


@patch("backend.stt.speechsdk.SpeechConfig")
@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
def test_stt_uses_given_language(mock_stream, mock_audio_cfg, mock_recognizer, mock_config):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_recognizer.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession("key", "region", on_text=lambda t: None, language="en-US")

    assert mock_config_instance.speech_recognition_language == "en-US"


@patch("backend.stt.speechsdk.SpeechConfig")
@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
def test_stt_defaults_to_german(mock_stream, mock_audio_cfg, mock_recognizer, mock_config):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_recognizer.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession("key", "region", on_text=lambda t: None)

    assert mock_config_instance.speech_recognition_language == "de-DE"


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_pause_recognition_stops_recognizer_without_closing_stream(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.pause_recognition()

    mock_recognizer.stop_continuous_recognition_async.assert_called_once()
    mock_recognizer.stop_continuous_recognition_async.return_value.get.assert_called_once()
    mock_stream.close.assert_not_called()


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_resume_recognition_starts_recognizer(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.resume_recognition()

    mock_recognizer.start_continuous_recognition.assert_called_once()
    mock_stream.close.assert_not_called()
