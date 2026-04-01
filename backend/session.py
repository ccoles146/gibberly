import asyncio
import uuid
from typing import Optional

from backend.translation import TranslationSession
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates translation+synthesis → Web PubSub for one streaming session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.session_id = str(uuid.uuid4())
        if loop is None:
            raise TypeError(
                "SessionHandler requires an explicit event loop. "
                "Pass the running loop via loop=asyncio.get_running_loop() or loop=asyncio.get_event_loop()."
            )
        self._loop = loop

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._translation = TranslationSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_audio_chunk=self._on_audio_chunk,
        )

    def _on_audio_chunk(self, audio_bytes: bytes) -> None:
        """Called from Azure SDK background thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(self._publish_chunk(audio_bytes), self._loop)

    async def _publish_chunk(self, audio_bytes: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_audio(self.session_id, audio_bytes),
        )

    def start(self) -> None:
        self._translation.start()

    def write(self, audio_bytes: bytes) -> None:
        self._translation.write(audio_bytes)

    def stop(self) -> None:
        self._translation.stop()
        self._publisher.send_close(self.session_id)
