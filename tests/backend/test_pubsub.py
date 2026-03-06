import pytest
from unittest.mock import MagicMock, patch


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_sends_binary_to_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")

    audio = b"\x00\x01\x02\x03"
    publisher.publish_audio("abc123", audio)

    mock_client.send_to_group.assert_called_once_with(
        "session-abc123", audio, content_type="application/octet-stream"
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_get_listener_url_returns_websocket_url(mock_client_class):
    mock_client = MagicMock()
    mock_client.get_client_access_token.return_value = {
        "url": "wss://test.webpubsub.azure.com/client/hubs/sermon?access_token=token123"
    }
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    url = publisher.get_listener_token("session42")

    assert url.startswith("wss://")
    mock_client.get_client_access_token.assert_called_once_with(
        groups=["session-session42"],
        roles=["webpubsub.joinLeaveGroup.session-session42"],
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_send_close_sends_json_to_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.send_close("sess1")

    mock_client.send_to_group.assert_called_once_with(
        "session-sess1", '{"type":"close"}', content_type="application/json"
    )
