import asyncio
import uuid
from typing import Awaitable, Callable, Optional

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
        on_status: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.session_id = str(uuid.uuid4())
        if loop is None:
            raise TypeError(
                "SessionHandler requires an explicit event loop. "
                "Pass the running loop via loop=asyncio.get_running_loop() or loop=asyncio.get_event_loop()."
            )
        self._loop = loop
        self._on_status = on_status
        self.listener_count = 0
        self._first_audio_logged = False

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._translation = TranslationSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_audio_chunk=self._on_audio_chunk,
            on_phrase=self._on_phrase,
        )

    def _on_audio_chunk(self, audio_bytes: bytes) -> None:
        """Called from Azure SDK background thread — bridge to asyncio."""
        if not self._first_audio_logged:
            self._first_audio_logged = True
            print(f"[gibberly] first audio chunk: {len(audio_bytes)} bytes", flush=True)
            asyncio.run_coroutine_threadsafe(
                self._send_status({"type": "debug_audio_start", "size": len(audio_bytes)}),
                self._loop,
            )
        asyncio.run_coroutine_threadsafe(self._publish_chunk(audio_bytes), self._loop)

    def _on_phrase(self, text: str) -> None:
        """Called from Azure SDK background thread when a phrase is translated."""
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "phrase", "text": text}), self._loop
        )
        asyncio.run_coroutine_threadsafe(
            self._loop.run_in_executor(
                None, lambda: self._publisher.publish_phrase(self.session_id, text)
            ),
            self._loop,
        )

    async def _publish_chunk(self, audio_bytes: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_audio(self.session_id, audio_bytes),
        )

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except Exception:
                pass

    def listener_join(self) -> int:
        self.listener_count += 1
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def listener_leave(self) -> int:
        self.listener_count = max(0, self.listener_count - 1)
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def start(self) -> None:
        self._translation.start()

    def write(self, audio_bytes: bytes) -> None:
        self._translation.write(audio_bytes)

    def stop(self) -> None:
        self._translation.stop()
        self._publisher.send_close(self.session_id)
