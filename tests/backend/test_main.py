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
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg
        importlib.reload(cfg)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app

        mock_session = MagicMock()
        mock_session.session_id = "test-uuid"
        mock_session.listener_tokens = {"en": "wss://pubsub.example.com/token"}
        app.state.sessions = {"test-uuid": mock_session}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/negotiate?session=test-uuid&lang=en")
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
                r = await client.post("/session/session-abc/join?lang=en")
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
                r = await client.post("/session/session-abc/leave?lang=en")
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


@patch("backend.main.SessionHandler")
def test_languages_endpoint_returns_list(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/languages")
                assert r.status_code == 200
                langs = r.json()
                assert isinstance(langs, list)
                assert len(langs) == 9
                assert all("code" in l and "name" in l for l in langs)
                assert all("voice" not in l for l in langs)

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_session_info_returns_source_lang(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.source_lang = "de-DE"
        app.state.sessions = {"sess1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/session/sess1/info")
                assert r.status_code == 200
                assert r.json() == {"source_lang": "de-DE"}

                r2 = await client.get("/session/nonexistent/info")
                assert r2.status_code == 404

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_negotiate_with_lang_param(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.listener_tokens = {"en": "wss://tok-en", "fr": "wss://tok-fr"}
        app.state.sessions = {"s1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/negotiate?session=s1&lang=fr")
                assert r.status_code == 200
                assert r.json()["url"] == "wss://tok-fr"

                r2 = await client.get("/negotiate?session=s1&lang=xx")
                assert r2.status_code == 404

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_audio_join_and_leave(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.audio_join.return_value = 1
        mock_handler.audio_leave.return_value = 0
        app.state.sessions = {"s1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/s1/audio/join?lang=en")
                assert r.status_code == 200
                assert r.json() == {"count": 1}
                mock_handler.audio_join.assert_called_once_with("en")

                r2 = await client.post("/session/s1/audio/leave?lang=en")
                assert r2.status_code == 200
                assert r2.json() == {"count": 0}
                mock_handler.audio_leave.assert_called_once_with("en")

                r3 = await client.post("/session/nonexistent/audio/join?lang=en")
                assert r3.status_code == 404

        asyncio.run(_test())
