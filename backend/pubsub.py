from azure.messaging.webpubsubservice import WebPubSubServiceClient


class PubSubPublisher:
    def __init__(self, connection_string: str, hub: str = "sermon"):
        # Normalize connection string: Azure Portal returns "AccessKey" but SDK expects "accesskey"
        normalized_cs = connection_string.replace("AccessKey=", "accesskey=")
        self._client = WebPubSubServiceClient.from_connection_string(
            normalized_cs, hub=hub
        )

    def publish_audio(self, session_id: str, audio_bytes: bytes) -> None:
        group = f"session-{session_id}"
        self._client.send_to_group(group, audio_bytes, content_type="application/octet-stream")

    def get_listener_token(self, session_id: str) -> str:
        group = f"session-{session_id}"
        result = self._client.get_client_access_token(
            groups=[group],
            roles=[f"webpubsub.joinLeaveGroup.{group}"],
        )
        return result["url"]

    def publish_phrase(self, session_id: str, raw_de: str, clean_de: str, en_text: str) -> None:
        import json
        group = f"session-{session_id}"
        self._client.send_to_group(
            group,
            json.dumps({"type": "phrase", "raw_de": raw_de, "clean_de": clean_de, "text": en_text}),
            content_type="application/json",
        )

    def send_close(self, session_id: str) -> None:
        group = f"session-{session_id}"
        self._client.send_to_group(group, '{"type":"close"}', content_type="application/json")
