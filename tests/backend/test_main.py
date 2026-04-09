import os
import pytest
from unittest.mock import patch

env = {
    "AZURE_SPEECH_KEY": "test-key",
    "AZURE_SPEECH_REGION": "westeurope",
    "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
    "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
    "AZURE_OPENAI_API_KEY": "oai-key",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    "AZURE_TRANSLATOR_KEY": "tr-key",
    "AZURE_TRANSLATOR_REGION": "westeurope",
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


from unittest.mock import MagicMock, patch


@patch("backend.main.SessionHandler")
def test_negotiate_returns_pubsub_url(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        mock_session = MagicMock()
        mock_session.session_id = "test-uuid"
        mock_session.listener_token = "wss://pubsub.example.com/token"
        app.state.sessions = {"test-uuid": mock_session}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/negotiate?session=test-uuid")
                assert r.status_code == 200
                assert r.json()["url"] == "wss://pubsub.example.com/token"

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_live_redirect_no_session(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        app.state.current_session_id = None

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/listen/live", follow_redirects=False)
                assert r.status_code == 503

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_live_redirect_active_session(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        app.state.current_session_id = "abc-123"

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/listen/live", follow_redirects=False)
                assert r.status_code in (302, 307)
                assert r.headers["location"] == "/listen/index.html?session=abc-123"

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_listener_join_increments_count(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.listener_join.return_value = 1
        app.state.sessions = {"session-abc": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/session-abc/join")
                assert r.status_code == 200
                assert r.json() == {"count": 1}

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_listener_join_unknown_session(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        app.state.sessions = {}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/nonexistent/join")
                assert r.status_code == 404

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_listener_leave_decrements_count(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.listener_leave.return_value = 0
        app.state.sessions = {"session-abc": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/session-abc/leave")
                assert r.status_code == 200

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_listener_leave_unknown_session(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        app.state.sessions = {}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/nonexistent/leave")
                assert r.status_code == 200
                assert r.json() == {"count": 0}

        asyncio.run(_test())
