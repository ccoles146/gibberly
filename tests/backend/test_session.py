import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

ENGLISH_ONLY = [{"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"}]


def _make_handler(loop, on_status=None, target_languages=None):
    """Helper to build a SessionHandler with all dependencies mocked."""
    from backend.session import SessionHandler
    return SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        target_languages=target_languages or ENGLISH_ONLY,
        loop=loop,
        on_status=on_status,
    )


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_has_unique_id(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    s1, s2 = _make_handler(loop), _make_handler(loop)
    assert s1.session_id != s2.session_id
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_listener_tokens_keyed_by_lang(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub.get_listener_token.return_value = "wss://tok"
    mock_pub_class.return_value = mock_pub
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    assert handler.listener_tokens["en"] == "wss://tok"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id, "en")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_write_audio_forwards_to_stt_session(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.write(b"\xde\xad\xbe\xef")
    mock_stt.write.assert_called_once_with(b"\xde\xad\xbe\xef")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_sends_phrase_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Der Herr ist gut.", "en_text": "The Lord is good."})

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler._process_chunk("Ähm, der Herr ist gut."))

    phrase_msgs = [m for m in statuses if m.get("type") == "phrase"]
    assert len(phrase_msgs) == 1
    assert phrase_msgs[0]["raw_src"] == "Ähm, der Herr ist gut."
    assert phrase_msgs[0]["clean_src"] == "Der Herr ist gut."
    assert phrase_msgs[0]["en_text"] == "The Lord is good."
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_all_tts_when_clean_src_empty(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "", "en_text": ""})

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    loop.run_until_complete(handler._process_chunk("Ähm"))

    mock_tts.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_tts_when_no_audio_listeners(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    """TTS must not fire when audio_active_count for that language is 0."""
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    # audio_active_count["en"] is 0 by default
    loop.run_until_complete(handler._process_chunk("Gut"))

    mock_tts.synthesize.assert_not_called()
    # phrase should still be published even without audio
    mock_pub.publish_phrase.assert_called_once()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_synthesizes_when_audio_listener_present(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})

    def fake_synthesize(text, on_chunk, tone="calm"):
        on_chunk(b"\x01\x02")

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize
    mock_tts_class.return_value = mock_tts

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.audio_join("en")  # one audio listener
    loop.run_until_complete(handler._process_chunk("Gut"))

    on_chunk_arg = mock_tts.synthesize.call_args[0][1]
    mock_tts.synthesize.assert_called_once_with("Good", on_chunk_arg, tone="calm")
    mock_pub.publish_audio.assert_called_once_with(handler.session_id, "en", b"\x01\x02")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_falls_back_on_llm_error(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(side_effect=Exception("timeout"))

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler._process_chunk("Der Herr ist gut."))

    fallback_msgs = [m for m in statuses if m.get("type") == "llm_fallback"]
    assert len(fallback_msgs) == 1
    assert fallback_msgs[0]["chunk"] == "Der Herr ist gut."
    mock_tts_class.return_value.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_listener_join_leave_updates_total_count_in_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    handler.listener_join("en")
    handler.listener_join("es")
    handler.listener_leave("en")
    loop.run_until_complete(asyncio.sleep(0))  # let threadsafe coroutines run

    listener_msgs = [m for m in statuses if m.get("type") == "listeners"]
    counts = [m["count"] for m in listener_msgs]
    assert counts == [1, 2, 1]
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_audio_join_leave_updates_audio_active_count(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)

    handler.audio_join("en")
    assert handler.audio_active_count["en"] == 1
    handler.audio_join("en")
    assert handler.audio_active_count["en"] == 2
    handler.audio_leave("en")
    assert handler.audio_active_count["en"] == 1
    handler.audio_leave("en")
    handler.audio_leave("en")  # extra leave — should not go negative
    assert handler.audio_active_count["en"] == 0
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_pause_sets_paused_flag_and_broadcasts(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler.pause())

    assert handler.paused is True
    mock_stt.pause_recognition.assert_called_once()
    mock_pub.broadcast_event.assert_called_once_with(handler.session_id, {"type": "paused"})
    assert any(m.get("type") == "paused" for m in statuses)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_resume_clears_paused_flag_and_broadcasts(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    handler.paused = True
    loop.run_until_complete(handler.resume())

    assert handler.paused is False
    mock_stt.resume_recognition.assert_called_once()
    mock_pub.broadcast_event.assert_called_once_with(handler.session_id, {"type": "resumed"})
    assert any(m.get("type") == "resumed" for m in statuses)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_dropped_when_paused(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.paused = True
    loop.run_until_complete(handler._process_chunk("Gut"))

    mock_llm.translate.assert_not_called()
    mock_pub.publish_phrase.assert_not_called()
    loop.close()
