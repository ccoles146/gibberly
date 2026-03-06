import os
import pytest
from unittest.mock import patch

env = {
    "AZURE_SPEECH_KEY": "test-key",
    "AZURE_SPEECH_REGION": "westeurope",
    "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
}


def test_health_check():
    with patch.dict(os.environ, env):
        import importlib
        import backend.config as cfg
        importlib.reload(cfg)

        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        import asyncio

        # Import app after env is patched
        import backend.main
        importlib.reload(backend.main)
        from backend.main import app

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/health")
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}

        asyncio.run(_test())
