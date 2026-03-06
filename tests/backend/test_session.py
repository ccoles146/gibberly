import asyncio
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_deps():
    with patch("backend.session.TranslationSession") as mock_ts_class, \
         patch("backend.session.synthesize") as mock_synth, \
         patch("backend.session.PubSubPublisher") as mock_pub_class:

        mock_ts = MagicMock()
        mock_ts_class.return_value = mock_ts

        mock_pub = MagicMock()
        mock_pub_class.return_value = mock_pub
        mock_pub.get_listener_token.return_value = "wss://pubsub.example.com/token123"

        mock_synth.return_value = b"RIFF...wav"

        yield mock_ts_class, mock_synth, mock_pub_class, mock_ts, mock_pub


def test_session_has_unique_id(mock_deps):
    from backend.session import SessionHandler
    s1 = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    s2 = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    assert s1.session_id != s2.session_id


def test_session_listener_url_contains_session_id(mock_deps):
    *_, mock_ts, mock_pub = mock_deps
    from backend.session import SessionHandler
    handler = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    url = handler.listener_token
    assert url == "wss://pubsub.example.com/token123"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id)


def test_write_audio_forwards_to_translation_session(mock_deps):
    *_, mock_ts, mock_pub = mock_deps
    from backend.session import SessionHandler
    handler = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    handler.start()
    handler.write(b"\xde\xad\xbe\xef")
    mock_ts.write.assert_called_once_with(b"\xde\xad\xbe\xef")


def test_on_translation_synthesizes_and_publishes(mock_deps):
    mock_ts_class, mock_synth, mock_pub_class, mock_ts, mock_pub = mock_deps
    loop = asyncio.new_event_loop()

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="k", speech_region="r", pubsub_cs="cs", loop=loop
    )
    handler.start()

    # Grab the on_translation callback passed to TranslationSession
    on_translation = mock_ts_class.call_args[1]["on_translation"]

    # Fire it (simulates SDK callback on background thread)
    on_translation("Guten Morgen")

    # Run the loop to process the coroutine
    loop.run_until_complete(asyncio.sleep(0.1))

    mock_synth.assert_called_once_with("Guten Morgen", speech_key="k", speech_region="r")
    mock_pub.publish_audio.assert_called_once_with(handler.session_id, b"RIFF...wav")
    loop.close()
