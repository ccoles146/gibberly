import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_has_unique_id(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler

    def make():
        return SessionHandler(
            speech_key="sk", speech_region="r", pubsub_cs="cs",
            openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
            translator_key="tk", translator_region="r",
            loop=loop,
        )

    s1, s2 = make(), make()
    assert s1.session_id != s2.session_id
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_listener_token_comes_from_pubsub(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub.get_listener_token.return_value = "wss://tok"
    mock_pub_class.return_value = mock_pub
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    assert handler.listener_token == "wss://tok"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_write_audio_forwards_to_stt_session(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    handler.write(b"\xde\xad\xbe\xef")
    mock_stt.write.assert_called_once_with(b"\xde\xad\xbe\xef")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_sends_phrase_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(return_value="Der Herr ist gut.")

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr
    mock_tr.translate = AsyncMock(return_value="The Lord is good.")

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
        on_status=capture_status,
    )

    loop.run_until_complete(handler._process_chunk("Ähm, der Herr ist gut."))

    phrase_msgs = [m for m in statuses if m.get("type") == "phrase"]
    assert len(phrase_msgs) == 1
    assert phrase_msgs[0]["raw_de"] == "Ähm, der Herr ist gut."
    assert phrase_msgs[0]["clean_de"] == "Der Herr ist gut."
    assert phrase_msgs[0]["text"] == "The Lord is good."
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_tts_for_empty_clean(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(return_value="")  # all-filler chunk

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    loop.run_until_complete(handler._process_chunk("Ähm"))

    mock_tr.translate.assert_not_called()
    mock_tts.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_falls_back_on_llm_error(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(side_effect=Exception("timeout"))

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr
    mock_tr.translate = AsyncMock(return_value="The Lord is good.")

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
        on_status=capture_status,
    )
    loop.run_until_complete(handler._process_chunk("Der Herr ist gut."))

    fallback_msgs = [m for m in statuses if m.get("type") == "llm_fallback"]
    assert len(fallback_msgs) == 1
    assert fallback_msgs[0]["chunk"] == "Der Herr ist gut."

    mock_tr.translate.assert_called_once_with("Der Herr ist gut.")
    loop.close()
