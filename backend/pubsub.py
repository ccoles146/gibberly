import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from backend.languages import SUPPORTED_LANGUAGES
from azure.core.pipeline.transport import RequestsTransport
from azure.messaging.webpubsubservice import WebPubSubServiceClient

log = logging.getLogger("gibberly.pubsub")


def _jwt_exp_utc(token_url: str) -> Optional[str]:
    """Decode the exp claim from the JWT in the access_token query param."""
    try:
        parts = token_url.split("access_token=")
        if len(parts) < 2:
            return None
        jwt = parts[1].split("&")[0]
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%H:%M UTC")
    except Exception:
        pass
    return None


class PubSubPublisher:
    def __init__(self, connection_string: str, hub: str = "sermon"):
        # Normalize connection string: Azure Portal returns "AccessKey" but SDK expects "accesskey"
        normalized_cs = connection_string.replace("AccessKey=", "accesskey=")
        # HTTP-level timeout prevents zombie threads when the PubSub REST endpoint
        # is unresponsive. Without this, requests hangs indefinitely, fills the
        # executor thread pool, and causes all subsequent publishes to queue and timeout.
        transport = RequestsTransport(connection_timeout=3, read_timeout=4)
        self._client = WebPubSubServiceClient.from_connection_string(
            normalized_cs, hub=hub, transport=transport
        )
        log.info("PubSub client initialised (hub=%s)", hub)

    def get_listener_token(self, session_id: str, lang: str) -> str:
        group = f"session-{session_id}-{lang}"
        t0 = time.monotonic()
        result = self._client.get_client_access_token(
            groups=[group],
            roles=[f"webpubsub.joinLeaveGroup.{group}"],
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        url = result["url"]
        exp = _jwt_exp_utc(url) or "~60 min"
        log.info(
            "PubSub token issued — group=%s expires=%s (%.0fms)",
            group, exp, elapsed_ms,
        )
        return url

    def publish_audio(self, session_id: str, lang: str, audio_bytes: bytes) -> None:
        group = f"session-{session_id}-{lang}"
        t0 = time.monotonic()
        try:
            self._client.send_to_group(group, audio_bytes, content_type="application/octet-stream")
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.debug("PubSub audio — group=%s size=%d bytes %.0fms", group, len(audio_bytes), elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.error(
                "PubSub audio publish FAILED — group=%s size=%d bytes %.0fms: %s",
                group, len(audio_bytes), elapsed_ms, exc,
            )
            raise

    def publish_phrase(self, session_id: str, lang: str, clean_src: str, text: str) -> None:
        group = f"session-{session_id}-{lang}"
        payload = json.dumps({"type": "phrase", "clean_src": clean_src, "text": text})
        t0 = time.monotonic()
        try:
            self._client.send_to_group(group, payload, content_type="application/json")
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.info(
                "PubSub phrase — group=%s %.0fms: %r",
                group, elapsed_ms, text[:80],
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.error(
                "PubSub phrase publish FAILED — group=%s %.0fms: %s",
                group, elapsed_ms, exc,
            )
            raise

    def send_close(self, session_id: str) -> None:
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, '{"type":"close"}', content_type="application/json")
                log.info("PubSub close sent — group=%s", group)
            except Exception as exc:
                log.warning("PubSub send_close FAILED — group=%s: %s", group, exc)

    def broadcast_event(self, session_id: str, event: dict) -> None:
        payload = json.dumps(event)
        event_type = event.get("type", "?")
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, payload, content_type="application/json")
                log.info("PubSub broadcast %r — group=%s", event_type, group)
            except Exception as exc:
                log.warning("PubSub broadcast %r FAILED — group=%s: %s", event_type, group, exc)
