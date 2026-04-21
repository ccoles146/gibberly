import json
import logging
from backend.languages import SUPPORTED_LANGUAGES
from azure.messaging.webpubsubservice import WebPubSubServiceClient

log = logging.getLogger("gibberly")


class PubSubPublisher:
    def __init__(self, connection_string: str, hub: str = "sermon"):
        # Normalize connection string: Azure Portal returns "AccessKey" but SDK expects "accesskey"
        normalized_cs = connection_string.replace("AccessKey=", "accesskey=")
        self._client = WebPubSubServiceClient.from_connection_string(
            normalized_cs, hub=hub
        )

    def publish_audio(self, session_id: str, lang: str, audio_bytes: bytes) -> None:
        group = f"session-{session_id}-{lang}"
        self._client.send_to_group(group, audio_bytes, content_type="application/octet-stream")

    def get_listener_token(self, session_id: str, lang: str) -> str:
        group = f"session-{session_id}-{lang}"
        result = self._client.get_client_access_token(
            groups=[group],
            roles=[f"webpubsub.joinLeaveGroup.{group}"],
        )
        return result["url"]

    def publish_phrase(self, session_id: str, lang: str, clean_src: str, text: str) -> None:
        group = f"session-{session_id}-{lang}"
        self._client.send_to_group(
            group,
            json.dumps({"type": "phrase", "clean_src": clean_src, "text": text}),
            content_type="application/json",
        )

    def send_close(self, session_id: str) -> None:
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, '{"type":"close"}', content_type="application/json")
            except Exception as exc:
                log.warning("send_close to group %s failed (ignored): %s", group, exc)

    def broadcast_event(self, session_id: str, event: dict) -> None:
        payload = json.dumps(event)
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, payload, content_type="application/json")
            except Exception as exc:
                log.warning("broadcast_event to %s failed: %s", group, exc)
