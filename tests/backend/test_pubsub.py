import json
import pytest
from unittest.mock import MagicMock, patch


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_sends_binary_to_lang_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")

    audio = b"\x00\x01\x02\x03"
    publisher.publish_audio("abc123", "en", audio)

    mock_client.send_to_group.assert_called_once_with(
        "session-abc123-en", audio, content_type="application/octet-stream"
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_get_listener_token_scoped_to_lang_group(mock_client_class):
    mock_client = MagicMock()
    mock_client.get_client_access_token.return_value = {
        "url": "wss://test.webpubsub.azure.com/client/hubs/sermon?access_token=token123"
    }
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    url = publisher.get_listener_token("session42", "fr")

    assert url.startswith("wss://")
    mock_client.get_client_access_token.assert_called_once_with(
        groups=["session-session42-fr"],
        roles=["webpubsub.joinLeaveGroup.session-session42-fr"],
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_phrase_sends_text_for_lang(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_phrase("sess1", "es", "El texto limpio", "The clean text")

    call_args = mock_client.send_to_group.call_args
    assert call_args[0][0] == "session-sess1-es"
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "phrase"
    assert payload["text"] == "The clean text"
    assert payload["clean_src"] == "El texto limpio"


@patch("backend.pubsub.WebPubSubServiceClient")
def test_send_close_broadcasts_to_all_lang_groups(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    from backend.languages import SUPPORTED_LANGUAGES
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.send_close("sess1")

    assert mock_client.send_to_group.call_count == len(SUPPORTED_LANGUAGES)
    called_groups = {c[0][0] for c in mock_client.send_to_group.call_args_list}
    for lang in SUPPORTED_LANGUAGES:
        assert f"session-sess1-{lang['code']}" in called_groups
