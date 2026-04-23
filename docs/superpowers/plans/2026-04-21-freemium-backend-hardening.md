# Freemium Backend Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the public `gibberly` repo for open-source release and paid hosted service — auth hooks, security middleware, listener join tokens, Managed Identity support, session hard limit, process reliability, frontend security fixes, and self-hosting infrastructure (Docker + Bicep).

**Architecture:** A no-op auth hook (`backend/auth.py`) is injected at the FastAPI startup; the private hosted deployment overwrites it with a licence-key validator at Docker build time. All security hardening (CORS, rate limiting, CSP, join tokens, input validation) lives in `backend/main.py` middleware. Self-hosters get a one-command Azure provisioning path via Bicep + Docker Compose.

**Tech Stack:** Python 3.13, FastAPI, slowapi (rate limiting), azure-identity (Managed Identity), HMAC-SHA256 (join tokens), Azure Bicep, Docker Compose, vanilla JS.

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `backend/auth.py` | **NEW** | LicenceContext dataclass, no-op hooks, HMAC join token helpers |
| `backend/config.py` | Modify | Add cors_origins, listener_token_secret, force_https, debug, max_session_hours; make Azure keys optional |
| `backend/main.py` | Modify | Security middleware, rate limiting, auth hook wiring, join token validation, input validation, error handler, SIGTERM, debug page gating |
| `backend/session.py` | Modify | Accept LicenceContext, call on_session_start/end, enforce MAX_SESSION_HOURS hard limit |
| `backend/stt.py` | Modify | Accept DefaultAzureCredential when speech_key absent |
| `backend/tts.py` | Modify | Accept DefaultAzureCredential when speech_key absent |
| `backend/pubsub.py` | Modify | Accept DefaultAzureCredential when connection_string absent |
| `backend/llm_translator.py` | Modify | Accept DefaultAzureCredential when api_key absent |
| `operator/app.js` | Modify | Fix backendHttp derivation, innerHTML → DOM methods, reconnecting state |
| `listener/app.js` | Modify | innerHTML → DOM methods, pass join token to /negotiate |
| `Dockerfile` | **NEW** | Python 3.13-slim image for self-hosting |
| `docker-compose.yml` | **NEW** | Single-service config with restart policy and health check |
| `deploy/azure.bicep` | **NEW** | Provisions Speech S0, OpenAI, Web PubSub Standard S1 |
| `.env.example` | Modify | Add all new settings with inline comments |
| `requirements.txt` | Modify | Add slowapi, azure-identity |
| `tests/backend/test_auth.py` | **NEW** | Tests for LicenceContext, token helpers |
| `tests/backend/test_main.py` | Modify/NEW | Tests for CORS, security headers, rate limiting, negotiate auth, lang validation |
| `tests/backend/test_session.py` | Modify | Tests for hard limit, hook callbacks |
| `tests/backend/test_config.py` | Modify/NEW | Tests for new settings |

---

## Task 1: `backend/auth.py` — no-op hook + join token helpers

**Files:**
- Create: `backend/auth.py`
- Create: `tests/backend/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/test_auth.py
import time
import pytest
from backend.auth import (
    LicenceContext,
    validate_request,
    on_session_start,
    on_session_end,
    generate_listener_token,
    validate_listener_token,
)


@pytest.mark.asyncio
async def test_validate_request_returns_unlimited_context():
    from unittest.mock import MagicMock
    request = MagicMock()
    ctx = await validate_request(request)
    assert ctx.unlimited is True


@pytest.mark.asyncio
async def test_on_session_start_is_noop():
    ctx = LicenceContext()
    await on_session_start(ctx, "sess-123")  # must not raise


@pytest.mark.asyncio
async def test_on_session_end_is_noop():
    ctx = LicenceContext()
    await on_session_end(ctx, 90.0, 30.0, 1)  # must not raise


def test_generate_and_validate_token_roundtrip():
    token = generate_listener_token("sess-abc", secret="testsecret")
    assert validate_listener_token("sess-abc", token, secret="testsecret") is True


def test_validate_token_rejects_wrong_session():
    token = generate_listener_token("sess-abc", secret="testsecret")
    assert validate_listener_token("sess-xyz", token, secret="testsecret") is False


def test_validate_token_rejects_wrong_secret():
    token = generate_listener_token("sess-abc", secret="testsecret")
    assert validate_listener_token("sess-abc", token, secret="wrongsecret") is False


def test_validate_token_rejects_expired():
    token = generate_listener_token("sess-abc", secret="testsecret", ttl_hours=-1.0)
    assert validate_listener_token("sess-abc", token, secret="testsecret") is False


def test_validate_token_rejects_malformed():
    assert validate_listener_token("sess-abc", "notavalidtoken", secret="testsecret") is False
    assert validate_listener_token("sess-abc", "", secret="testsecret") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/chris/gibberly && source .venv/bin/activate
pytest tests/backend/test_auth.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.auth'`

- [ ] **Step 3: Implement `backend/auth.py`**

```python
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from starlette.requests import HTTPConnection

log = logging.getLogger("gibberly")


@dataclass
class LicenceContext:
    unlimited: bool = True
    session_id: str = ""


async def validate_request(request: HTTPConnection) -> LicenceContext:
    """No-op for self-hosted. Private hosted version raises HTTP 401 if key invalid."""
    return LicenceContext(unlimited=True)


async def on_session_start(ctx: LicenceContext, session_id: str) -> None:
    """No-op for self-hosted. Private version registers session as active on licence server."""
    log.debug("on_session_start: session=%s", session_id)


async def on_session_end(
    ctx: LicenceContext,
    audio_in_sec: float,
    audio_out_sec: float,
    language_count: int,
) -> None:
    """No-op for self-hosted. Private version reports usage to licence server."""
    log.debug(
        "on_session_end: session=%s in=%.1fs out=%.1fs langs=%d",
        ctx.session_id, audio_in_sec, audio_out_sec, language_count,
    )


def generate_listener_token(session_id: str, secret: str, ttl_hours: float = 24.0) -> str:
    """Generate an HMAC-SHA256 signed join token for the listener page."""
    expiry = int(time.time() + ttl_hours * 3600)
    msg = f"{session_id}:{expiry}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def validate_listener_token(session_id: str, token: str, secret: str) -> bool:
    """Verify a join token is valid, unexpired, and bound to this session_id."""
    try:
        expiry_str, sig = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if time.time() > expiry:
        return False
    msg = f"{session_id}:{expiry}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_auth.py -v
```
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py tests/backend/test_auth.py
git commit -m "feat: add auth hook interface and listener join token helpers"
```

---

## Task 2: `backend/config.py` — new settings + optional Azure keys

**Files:**
- Modify: `backend/config.py`
- Create: `tests/backend/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/test_config.py
import os
import importlib
import pytest

BASE_ENV = {
    "AZURE_SPEECH_KEY": "sk",
    "AZURE_SPEECH_REGION": "westeurope",
    "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://t.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
    "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
    "AZURE_OPENAI_API_KEY": "oai-key",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    "LISTENER_TOKEN_SECRET": "testsecret32bytesxxxxxxxxxxxxxxx",
}


def _reload(extra=None):
    env = {**BASE_ENV, **(extra or {})}
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, env, clear=True):
        import backend.config as cfg
        importlib.reload(cfg)
        return cfg.settings


def test_defaults():
    s = _reload()
    assert s.cors_origins == ["http://localhost:8000"]
    assert s.force_https is True
    assert s.debug is False
    assert s.max_session_hours == 3.0


def test_cors_origins_parsed_from_env():
    s = _reload({"CORS_ORIGINS": "https://a.com,https://b.com"})
    assert s.cors_origins == ["https://a.com", "https://b.com"]


def test_listener_token_secret_required():
    env = {k: v for k, v in BASE_ENV.items() if k != "LISTENER_TOKEN_SECRET"}
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(os.environ, env, clear=True):
        import backend.config as cfg
        with pytest.raises(ValueError, match="LISTENER_TOKEN_SECRET"):
            cfg._load()


def test_max_session_hours_from_env():
    s = _reload({"MAX_SESSION_HOURS": "2.5"})
    assert s.max_session_hours == 2.5


def test_azure_keys_optional():
    env = {k: v for k, v in BASE_ENV.items()
           if k not in ("AZURE_SPEECH_KEY", "AZURE_OPENAI_API_KEY")}
    s = _reload(env)
    assert s.azure_speech_key is None
    assert s.azure_openai_api_key is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/backend/test_config.py -v
```
Expected: failures on missing `cors_origins`, `listener_token_secret`, `max_session_hours` attributes.

- [ ] **Step 3: Rewrite `backend/config.py`**

```python
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Azure credentials — all optional (absent = use Managed Identity)
    azure_speech_key: Optional[str]
    azure_speech_region: str
    azure_webpubsub_connection_string: Optional[str]
    azure_openai_endpoint: Optional[str]
    azure_openai_api_key: Optional[str]
    azure_openai_deployment: Optional[str]
    # Server
    backend_host: str
    backend_port: int
    # Security
    cors_origins: list
    listener_token_secret: str
    force_https: bool
    debug: bool
    # Tuning
    stt_silence_timeout_ms: int
    stt_time_cap_s: float
    llm_context_window: int
    session_timeout_s: int
    max_session_hours: float


def _load() -> Settings:
    secret = os.environ.get("LISTENER_TOKEN_SECRET")
    if not secret:
        raise ValueError("LISTENER_TOKEN_SECRET is required")

    region = os.environ.get("AZURE_SPEECH_REGION")
    if not region:
        raise ValueError("AZURE_SPEECH_REGION is required")

    cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:8000")
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

    return Settings(
        azure_speech_key=os.environ.get("AZURE_SPEECH_KEY") or None,
        azure_speech_region=region,
        azure_webpubsub_connection_string=os.environ.get("AZURE_WEBPUBSUB_CONNECTION_STRING") or None,
        azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT") or None,
        azure_openai_api_key=os.environ.get("AZURE_OPENAI_API_KEY") or None,
        azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT") or None,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
        cors_origins=cors_origins,
        listener_token_secret=secret,
        force_https=os.environ.get("FORCE_HTTPS", "true").lower() == "true",
        debug=os.environ.get("DEBUG", "false").lower() == "true",
        stt_silence_timeout_ms=int(os.environ.get("STT_SILENCE_TIMEOUT_MS", "1000")),
        stt_time_cap_s=float(os.environ.get("STT_TIME_CAP_S", "8.0")),
        llm_context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", "5")),
        session_timeout_s=int(os.environ.get("SESSION_TIMEOUT_S", "3600")),
        max_session_hours=float(os.environ.get("MAX_SESSION_HOURS", "3.0")),
    )


settings = _load()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_config.py -v
```
Expected: 5 passed

- [ ] **Step 5: Verify existing tests still pass**

```bash
pytest tests/ -v --ignore=tests/backend/test_auth.py --ignore=tests/backend/test_config.py 2>&1 | tail -20
```
Expected: all previously passing tests still pass (some may need env patching update for `LISTENER_TOKEN_SECRET`).

- [ ] **Step 6: Fix any broken tests**

Existing tests that use `patch.dict(os.environ, env)` for backend.main need `LISTENER_TOKEN_SECRET` added to their `env` dict. Find and update them:

```bash
grep -rn "AZURE_SPEECH_KEY" tests/ --include="*.py" -l
```

For each file found, add `"LISTENER_TOKEN_SECRET": "testsecret32bytesxxxxxxxxxxxxxxx"` to the env dict.

- [ ] **Step 7: Commit**

```bash
git add backend/config.py tests/backend/test_config.py tests/
git commit -m "feat: extend config with security and session settings, make Azure keys optional"
```

---

## Task 3: Security middleware — CORS, headers, rate limiting

**Files:**
- Modify: `backend/main.py` (lines 1–21 imports + middleware block)
- Modify: `requirements.txt`
- Create/Modify: `tests/backend/test_main.py`

- [ ] **Step 1: Add dependencies to `requirements.txt`**

Add after the `fastapi` line:
```
slowapi==0.1.9
azure-identity==1.16.0
```

Install:
```bash
pip install slowapi==0.1.9 azure-identity==1.16.0
```

- [ ] **Step 2: Write failing security tests**

```python
# tests/backend/test_main.py  (create or append)
import os, importlib, asyncio, pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

ENV = {
    "AZURE_SPEECH_KEY": "sk",
    "AZURE_SPEECH_REGION": "westeurope",
    "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://t.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
    "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
    "AZURE_OPENAI_API_KEY": "oai-key",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    "LISTENER_TOKEN_SECRET": "testsecret32bytesxxxxxxxxxxxxxxx",
    "CORS_ORIGINS": "https://allowed.example.com",
}


def _app():
    with patch.dict(os.environ, ENV):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as m; importlib.reload(m)
        return m.app


def test_security_headers_present():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["x-frame-options"] == "DENY"
            assert "default-src" in r.headers["content-security-policy"]
    asyncio.run(_run())


def test_cors_blocks_disallowed_origin():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.options(
                "/health",
                headers={"Origin": "https://evil.example.com",
                         "Access-Control-Request-Method": "GET"},
            )
            assert "https://evil.example.com" not in r.headers.get("access-control-allow-origin", "")
    asyncio.run(_run())


def test_cors_allows_configured_origin():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health", headers={"Origin": "https://allowed.example.com"})
            assert r.headers.get("access-control-allow-origin") == "https://allowed.example.com"
    asyncio.run(_run())
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/backend/test_main.py::test_security_headers_present tests/backend/test_main.py::test_cors_blocks_disallowed_origin -v
```
Expected: FAIL — no security headers, CORS is wildcard.

- [ ] **Step 4: Update imports and middleware in `backend/main.py`**

Replace lines 1–21 with:

```python
import asyncio
import json
import logging
import signal
from pathlib import Path
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gibberly")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.websockets import WebSocketState

from backend.config import settings
from backend.session import SessionHandler
from backend.languages import SUPPORTED_LANGUAGES, get_target_languages
from backend.auth import (
    validate_request,
    on_session_start,
    on_session_end,
    generate_listener_token,
    validate_listener_token,
    LicenceContext,
)

app = FastAPI(title="Gibberly Backend")

# ── Rate limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-License-Key"],
)


# ── Security headers ─────────────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        )
        if settings.force_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Global error handler (no stack traces to clients) ────────────────────────
@app.exception_handler(Exception)
async def _generic_error(request: Request, exc: Exception):
    log.error("Unhandled error on %s: %s", request.url, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.state.sessions: Dict[str, SessionHandler] = {}
app.state.current_session_id: Optional[str] = None
app.state.active_ws: Optional[WebSocket] = None

LISTENER_DIR = Path(__file__).parent.parent / "listener"
_VALID_SOURCE_LANGS = {"de-DE", "en-US"}
_VALID_LANG_CODES = {lang["code"] for lang in SUPPORTED_LANGUAGES}


def _validate_lang(lang: str) -> str:
    if lang not in _VALID_LANG_CODES:
        raise HTTPException(status_code=400, detail="Invalid language code")
    return lang
```

- [ ] **Step 5: Run security tests to verify they pass**

```bash
pytest tests/backend/test_main.py::test_security_headers_present tests/backend/test_main.py::test_cors_blocks_disallowed_origin tests/backend/test_main.py::test_cors_allows_configured_origin -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/main.py requirements.txt tests/backend/test_main.py
git commit -m "feat: add security headers, restricted CORS, rate limiting middleware"
```

---

## Task 4: Endpoint hardening — input validation, negotiate token, debug gating, SIGTERM

**Files:**
- Modify: `backend/main.py` (endpoint definitions, routes, startup)

- [ ] **Step 1: Write failing tests**

Append to `tests/backend/test_main.py`:

```python
def test_negotiate_requires_token():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Without token param — should fail
            r = await c.get("/negotiate?session=fakeid&lang=en")
            assert r.status_code in (401, 422)
    asyncio.run(_run())


def test_negotiate_rejects_invalid_token():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/negotiate?session=fakeid&lang=en&token=badtoken")
            assert r.status_code == 401
    asyncio.run(_run())


def test_listener_join_rejects_invalid_lang():
    app = _app()
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/session/fakeid/join?lang=../../etc/passwd")
            assert r.status_code == 400
    asyncio.run(_run())


def test_debug_page_returns_404_when_debug_false():
    app = _app()  # ENV has no DEBUG=true
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/listen/debug.html")
            assert r.status_code == 404
    asyncio.run(_run())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/backend/test_main.py::test_negotiate_requires_token tests/backend/test_main.py::test_negotiate_rejects_invalid_token tests/backend/test_main.py::test_listener_join_rejects_invalid_lang -v
```
Expected: failures (negotiate has no token param, join has no lang validation).

- [ ] **Step 3: Replace all endpoint definitions in `backend/main.py`**

Replace from `@app.get("/health")` through `@app.websocket("/ws/stream")` with:

```python
@app.get("/health")
@limiter.limit("60/minute")
async def health(request: Request):
    return {"status": "ok"}


@app.get("/languages")
@limiter.limit("60/minute")
async def list_languages(request: Request):
    return [{"code": l["code"], "name": l["name"]} for l in SUPPORTED_LANGUAGES]


@app.get("/current-session")
@limiter.limit("60/minute")
async def current_session(request: Request):
    sid = app.state.current_session_id
    if not sid:
        raise HTTPException(status_code=404, detail="No active session")
    return {"session_id": sid}


@app.get("/session/{session_id}/info")
@limiter.limit("60/minute")
async def session_info(request: Request, session_id: str):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"source_lang": handler.source_lang}


@app.get("/negotiate")
@limiter.limit("10/minute")
async def negotiate(request: Request, session: str, lang: str = "en", token: str = Query(...)):
    if not validate_listener_token(session, token, settings.listener_token_secret):
        raise HTTPException(status_code=401, detail="Invalid or expired listener token")
    handler = app.state.sessions.get(session)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    lang = _validate_lang(lang)
    pubsub_url = handler.listener_tokens.get(lang)
    if not pubsub_url:
        raise HTTPException(status_code=404, detail="Language not available for this session")
    return {"url": pubsub_url}


@app.get("/listen/live")
async def live_redirect():
    sid = app.state.current_session_id
    if not sid:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:3rem'>"
            "<h2>No live session at the moment.</h2>"
            "<p>The service will be available when the operator starts a session.</p>"
            "</body></html>",
            status_code=503,
        )
    tok = generate_listener_token(sid, settings.listener_token_secret)
    return RedirectResponse(f"/listen/index.html?session={sid}&token={tok}", status_code=302)


@app.post("/session/{session_id}/join")
@limiter.limit("20/minute")
async def listener_join(request: Request, session_id: str, lang: str = "en"):
    lang = _validate_lang(lang)
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"count": handler.listener_join(lang)}


@app.post("/session/{session_id}/leave")
@limiter.limit("20/minute")
async def listener_leave(request: Request, session_id: str, lang: str = "en"):
    lang = _validate_lang(lang)
    handler = app.state.sessions.get(session_id)
    if not handler:
        return {"count": 0}
    return {"count": handler.listener_leave(lang)}


@app.post("/session/{session_id}/audio/join")
@limiter.limit("20/minute")
async def audio_join(request: Request, session_id: str, lang: str = "en"):
    lang = _validate_lang(lang)
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"count": handler.audio_join(lang)}


@app.post("/session/{session_id}/audio/leave")
@limiter.limit("20/minute")
async def audio_leave(request: Request, session_id: str, lang: str = "en"):
    lang = _validate_lang(lang)
    handler = app.state.sessions.get(session_id)
    if not handler:
        return {"count": 0}
    return {"count": handler.audio_leave(lang)}
```

- [ ] **Step 4: Add debug page gating and SIGTERM handler before the StaticFiles mount (end of file)**

Replace the last 2 lines of `backend/main.py` (the `if LISTENER_DIR.exists():` block) with:

```python
async def _broadcast_restart() -> None:
    ws = app.state.active_ws
    if ws is not None and ws.client_state != WebSocketState.DISCONNECTED:
        try:
            await ws.send_json({"type": "server_restarting"})
        except Exception:
            pass


@app.on_event("startup")
async def _setup_sigterm():
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.create_task(_broadcast_restart()),
    )


if not settings.debug:
    @app.get("/listen/debug.html")
    async def _debug_disabled():
        raise HTTPException(status_code=404)

if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
```

- [ ] **Step 5: Run all new endpoint tests**

```bash
pytest tests/backend/test_main.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: harden endpoints — join tokens, input validation, debug gating, SIGTERM broadcast"
```

---

## Task 5: WebSocket auth + session hooks + hard limit in `backend/main.py` and `backend/session.py`

**Files:**
- Modify: `backend/main.py` (the `stream` WebSocket handler)
- Modify: `backend/session.py`
- Modify: `tests/backend/test_session.py`

- [ ] **Step 1: Write failing session tests**

Append to `tests/backend/test_session.py`:

```python
@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_on_session_start_called(mock_pub, mock_stt, mock_llm, mock_tts):
    from unittest.mock import AsyncMock, MagicMock
    from backend.auth import LicenceContext
    mock_pub.return_value = MagicMock()
    mock_pub.return_value.get_listener_token.return_value = "tok"
    mock_stt.return_value = MagicMock()
    mock_llm.return_value = MagicMock()
    mock_tts.return_value = MagicMock()

    on_start = AsyncMock()
    loop = asyncio.new_event_loop()
    ctx = LicenceContext()
    handler = _make_handler(loop, licence_ctx=ctx, on_session_start=on_start)
    loop.run_until_complete(handler._call_on_session_start())
    on_start.assert_called_once_with(ctx, handler.session_id)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_on_session_end_called_with_metrics(mock_pub, mock_stt, mock_llm, mock_tts):
    from unittest.mock import AsyncMock, MagicMock
    from backend.auth import LicenceContext
    mock_pub.return_value = MagicMock()
    mock_pub.return_value.get_listener_token.return_value = "tok"
    mock_stt.return_value = MagicMock()
    mock_llm.return_value = MagicMock()
    mock_tts.return_value = MagicMock()

    on_end = AsyncMock()
    loop = asyncio.new_event_loop()
    ctx = LicenceContext()
    handler = _make_handler(loop, licence_ctx=ctx, on_session_end=on_end)
    handler._audio_in_sec = 60.0
    handler._audio_out_sec = 20.0
    loop.run_until_complete(handler._call_on_session_end())
    on_end.assert_called_once_with(ctx, 60.0, 20.0, 1)  # 1 = len(ENGLISH_ONLY)
    loop.close()
```

Update `_make_handler` in `tests/backend/test_session.py` to pass `licence_ctx`, `on_session_start`, `on_session_end`:

```python
def _make_handler(loop, on_status=None, target_languages=None,
                  licence_ctx=None, on_session_start=None, on_session_end=None):
    from backend.session import SessionHandler
    from backend.auth import LicenceContext
    return SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        target_languages=target_languages or ENGLISH_ONLY,
        loop=loop,
        on_status=on_status,
        licence_ctx=licence_ctx or LicenceContext(),
        on_session_start_hook=on_session_start,
        on_session_end_hook=on_session_end,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/backend/test_session.py::test_on_session_start_called tests/backend/test_session.py::test_on_session_end_called_with_metrics -v
```
Expected: TypeError — SessionHandler doesn't accept `licence_ctx`.

- [ ] **Step 3: Update `backend/session.py` — add licence hooks and hard limit**

Add imports at top of `backend/session.py`:
```python
from typing import Awaitable, Callable, Optional
from backend.auth import LicenceContext, on_session_start as _default_on_start, on_session_end as _default_on_end
```

Update `SessionHandler.__init__` signature — add after `on_status` param:
```python
    licence_ctx: Optional[LicenceContext] = None,
    on_session_start_hook: Optional[Callable] = None,
    on_session_end_hook: Optional[Callable] = None,
    max_session_hours: float = 3.0,
```

Add to `__init__` body after `self._on_status = on_status`:
```python
        from backend.auth import LicenceContext as _LC
        self._licence_ctx = licence_ctx or _LC()
        self._on_session_start_hook = on_session_start_hook or _default_on_start
        self._on_session_end_hook = on_session_end_hook or _default_on_end
        self._max_session_hours = max_session_hours
        self._audio_in_sec: float = 0.0
        self._audio_out_sec: float = 0.0
```

Add these methods to `SessionHandler`:
```python
    async def _call_on_session_start(self) -> None:
        self._licence_ctx.session_id = self.session_id
        await self._on_session_start_hook(self._licence_ctx, self.session_id)

    async def _call_on_session_end(self) -> None:
        await self._on_session_end_hook(
            self._licence_ctx,
            self._audio_in_sec,
            self._audio_out_sec,
            len(self._target_languages),
        )
```

- [ ] **Step 4: Update `backend/main.py` WebSocket handler**

In the `stream` function, replace `await websocket.accept()` (line 116) with auth check before accept:

```python
@app.websocket("/ws/stream")
async def stream(websocket: WebSocket, source_lang: str = "de-DE"):
    try:
        licence_ctx = await validate_request(websocket)
    except HTTPException as exc:
        await websocket.close(code=1008)
        return

    await websocket.accept()
```

Update `SessionHandler(...)` construction in `stream` to pass the new params:

```python
    handler = SessionHandler(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        pubsub_cs=settings.azure_webpubsub_connection_string,
        openai_endpoint=settings.azure_openai_endpoint,
        openai_api_key=settings.azure_openai_api_key,
        openai_deployment=settings.azure_openai_deployment,
        target_languages=target_languages,
        source_lang=source_lang,
        silence_timeout_ms=settings.stt_silence_timeout_ms,
        time_cap_s=settings.stt_time_cap_s,
        context_window=settings.llm_context_window,
        loop=loop,
        on_status=send_status,
        licence_ctx=licence_ctx,
        max_session_hours=settings.max_session_hours,
    )
```

After `handler.start()` and before the `session_created` send, add:

```python
    await asyncio.get_running_loop().run_in_executor(None, lambda: None)  # yield
    asyncio.create_task(handler._call_on_session_start())
```

Update the `listener_url` in `session_created` to use https and embed join token:

```python
    scheme = "https" if settings.force_https else "http"
    tok = generate_listener_token(handler.session_id, settings.listener_token_secret)
    await websocket.send_json({
        "type": "session_created",
        "session_id": handler.session_id,
        "source_lang": source_lang,
        "listener_url": (
            f"{scheme}://{settings.backend_host}:{settings.backend_port}"
            f"/listen/index.html?session={handler.session_id}&token={tok}"
        ),
    })
```

Replace the `asyncio.timeout(settings.session_timeout_s)` block with a hard limit that uses `max_session_hours`:

```python
    hard_limit_s = int(settings.max_session_hours * 3600)
    try:
        async with asyncio.timeout(min(settings.session_timeout_s, hard_limit_s)):
            while True:
                data = await websocket.receive()
                raw_bytes = data.get("bytes")
                raw_text = data.get("text")
                if raw_bytes:
                    if len(raw_bytes) > 1_048_576:
                        log.warning("Session %s: oversized frame (%d bytes), closing", handler.session_id, len(raw_bytes))
                        await websocket.close(code=1009)
                        break
                    if not handler.paused:
                        handler.write(raw_bytes)
                        handler._audio_in_sec += len(raw_bytes) / (16000 * 2)  # 16kHz 16-bit mono
                elif raw_text:
                    try:
                        msg = json.loads(raw_text)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    else:
                        if msg.get("type") == "pause":
                            await handler.pause()
                        elif msg.get("type") == "resume":
                            await handler.resume()
                        else:
                            log.debug("Session %s — unrecognised WS message type: %s", handler.session_id, msg.get("type"))
    except asyncio.TimeoutError:
        log.warning("Session %s timed out after %ds", handler.session_id, hard_limit_s)
        try:
            await websocket.send_json({"type": "session_ended", "reason": "max_duration"})
            await websocket.close(code=1001)
        except Exception:
            pass
```

Add `on_session_end` call in the `finally` block, before `handler.stop()`:

```python
    finally:
        app.state.sessions.pop(handler.session_id, None)
        if app.state.current_session_id == handler.session_id:
            app.state.current_session_id = None
        if app.state.active_ws is websocket:
            app.state.active_ws = None
        log.info("Session %s stopping…", handler.session_id)
        try:
            await handler._call_on_session_end()
        except Exception as exc:
            log.error("Session %s on_session_end error: %s", handler.session_id, exc)
        try:
            await loop.run_in_executor(None, handler.stop)
            log.info("Session %s stopped", handler.session_id)
        except Exception as exc:
            log.error("Session %s stop error: %s", handler.session_id, exc)
```

- [ ] **Step 5: Run all session and main tests**

```bash
pytest tests/backend/test_session.py tests/backend/test_main.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/session.py tests/backend/test_session.py
git commit -m "feat: WebSocket auth hook, session lifecycle hooks, hard session time limit"
```

---

## Task 6: Managed Identity — optional credentials in Azure SDK clients

**Files:**
- Modify: `backend/stt.py`
- Modify: `backend/tts.py`
- Modify: `backend/pubsub.py`
- Modify: `backend/llm_translator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/test_managed_identity.py  (new file)
import pytest
from unittest.mock import patch, MagicMock


def test_stt_uses_key_when_present():
    import azure.cognitiveservices.speech as speechsdk
    with patch.object(speechsdk, "SpeechConfig", return_value=MagicMock()) as mock_cfg:
        from backend.stt import STTSession
        STTSession(speech_key="mykey", speech_region="westeurope",
                   on_text=lambda t: None)
        call_kwargs = mock_cfg.call_args
        assert call_kwargs.kwargs.get("subscription") == "mykey"


def test_stt_uses_managed_identity_when_no_key():
    import azure.cognitiveservices.speech as speechsdk
    with patch("azure.identity.DefaultAzureCredential") as mock_cred, \
         patch.object(speechsdk, "SpeechConfig", return_value=MagicMock()) as mock_cfg:
        mock_cred.return_value.get_token.return_value = MagicMock(token="bearer-tok")
        from backend import stt as stt_mod
        import importlib; importlib.reload(stt_mod)
        stt_mod.STTSession(speech_key=None, speech_region="westeurope",
                           on_text=lambda t: None)
        call_kwargs = mock_cfg.call_args
        assert call_kwargs.kwargs.get("auth_token") == "bearer-tok"


def test_llm_uses_key_when_present():
    with patch("openai.AzureOpenAI") as mock_client:
        from backend.llm_translator import LLMTranslator
        LLMTranslator("https://ep", "mykey", "dep", target_languages=[], context_window=5)
        assert mock_client.call_args.kwargs.get("api_key") == "mykey"


def test_llm_uses_managed_identity_when_no_key():
    with patch("openai.AzureOpenAI") as mock_client, \
         patch("azure.identity.DefaultAzureCredential"):
        from backend import llm_translator as lt
        import importlib; importlib.reload(lt)
        lt.LLMTranslator("https://ep", None, "dep", target_languages=[], context_window=5)
        assert mock_client.call_args.kwargs.get("api_key") is None
        assert "azure_ad_token_provider" in mock_client.call_args.kwargs
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/backend/test_managed_identity.py -v
```
Expected: tests for `no_key` paths fail (no managed identity support yet).

- [ ] **Step 3: Update `backend/stt.py`**

Find the `SpeechConfig` construction in `STTSession.__init__` and replace with:

```python
        if speech_key:
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=speech_region
            )
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default").token
            speech_config = speechsdk.SpeechConfig(
                auth_token=token, region=speech_region
            )
```

Update `TTSSynthesizer.__init__` in `backend/tts.py` the same way:

```python
        if speech_key:
            self._speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=speech_region
            )
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default").token
            self._speech_config = speechsdk.SpeechConfig(
                auth_token=token, region=speech_region
            )
```

- [ ] **Step 4: Update `backend/llm_translator.py`**

Find the `AzureOpenAI` client construction and replace with:

```python
        from openai import AzureOpenAI
        if openai_api_key:
            self._client = AzureOpenAI(
                azure_endpoint=openai_endpoint,
                api_key=openai_api_key,
                api_version="2024-02-01",
            )
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._client = AzureOpenAI(
                azure_endpoint=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-02-01",
            )
```

- [ ] **Step 5: Update `backend/pubsub.py`**

Replace `__init__` with:

```python
    def __init__(self, connection_string: Optional[str], hub: str = "sermon"):
        if connection_string:
            normalized_cs = connection_string.replace("AccessKey=", "accesskey=")
            self._client = WebPubSubServiceClient.from_connection_string(
                normalized_cs, hub=hub
            )
        else:
            import os
            from azure.identity import DefaultAzureCredential
            endpoint = os.environ.get("AZURE_WEBPUBSUB_ENDPOINT")
            if not endpoint:
                raise ValueError(
                    "AZURE_WEBPUBSUB_ENDPOINT is required when "
                    "AZURE_WEBPUBSUB_CONNECTION_STRING is not set"
                )
            self._client = WebPubSubServiceClient(
                endpoint=endpoint, hub=hub, credential=DefaultAzureCredential()
            )
```

Add `from typing import Optional` to `pubsub.py` imports.

- [ ] **Step 6: Run managed identity tests**

```bash
pytest tests/backend/test_managed_identity.py -v
```
Expected: all pass

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v 2>&1 | tail -30
```
Expected: all previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add backend/stt.py backend/tts.py backend/pubsub.py backend/llm_translator.py tests/backend/test_managed_identity.py
git commit -m "feat: support Managed Identity in all Azure SDK clients when keys absent"
```

---

## Task 7: `operator/app.js` — security fixes + reconnection state

**Files:**
- Modify: `operator/app.js`

- [ ] **Step 1: Fix `backendHttp` derivation (line 26)**

Find:
```javascript
  const backendHttp = backendWs.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
```
Replace with:
```javascript
  const url = backendWs.replace(/^wss?:\/\//, '');
  const isLocal = url.startsWith('localhost') || url.startsWith('127.0.0.1');
  const backendHttp = (isLocal ? 'http://' : 'https://') + url;
```

- [ ] **Step 2: Fix `deviceSelect` innerHTML (lines 78 and 88)**

Find (line 78):
```javascript
      deviceSelect.innerHTML = '<option value="">No audio devices found</option>';
```
Replace with:
```javascript
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No audio devices found';
      deviceSelect.replaceChildren(opt);
```

Find (line 88):
```javascript
    deviceSelect.innerHTML = '';
```
Replace with:
```javascript
    deviceSelect.replaceChildren();
```

- [ ] **Step 3: Fix `qrCanvas.innerHTML` (line 32)**

The QR code library generates HTML via `qr.createTableTag()`. This is safe (library-generated, not user data) but wrap it in a container to avoid direct innerHTML on the canvas element:

Find:
```javascript
    qrCanvas.innerHTML = qr.createTableTag(4, 0);
```
Replace with:
```javascript
    const qrTable = document.createElement('div');
    qrTable.innerHTML = qr.createTableTag(4, 0);  // library output, not user data
    qrCanvas.replaceChildren(qrTable);
```

- [ ] **Step 5: Fix `lastPhraseEl.innerHTML` (line 226)**

Find:
```javascript
      lastPhraseEl.innerHTML = parts.map(p => `<div>${p}</div>`).join('');
```
Replace with:
```javascript
      lastPhraseEl.replaceChildren(
        ...parts.map(p => { const d = document.createElement('div'); d.textContent = p; return d; })
      );
```

- [ ] **Step 6: Add reconnecting state with exponential backoff**

Find the WebSocket `onclose` handler in `operator/app.js`. It will look something like:
```javascript
    ws.onclose = () => { setState('idle'); ... }
```

Replace the close handler with:
```javascript
    let _reconnectDelay = 1000;
    ws.onclose = (ev) => {
      if (ev.code === 1000 || ev.code === 1001) {
        setState('idle');
        _reconnectDelay = 1000;
        return;
      }
      setState('reconnecting');
      setTimeout(() => {
        _reconnectDelay = Math.min(_reconnectDelay * 2, 10000);
        connect();  // re-enter the connect function
      }, _reconnectDelay);
    };
```

Add `'reconnecting'` to the `setState` function's visual mapping (status dot colour and text). Find the `setState` function and add:
```javascript
    case 'reconnecting':
      statusDot.className = 'status-dot status-reconnecting';
      statusText.textContent = 'Reconnecting…';
      actionBtn.disabled = true;
      break;
```

Add CSS for `.status-reconnecting` in `operator/index.html`:
```css
.status-reconnecting { background: #f59e0b; animation: pulse 1s infinite; }
```

- [ ] **Step 7: Handle `server_restarting` message**

In the WebSocket `onmessage` handler, add a case alongside the existing `pause`/`resume` handlers:

```javascript
      } else if (msg.type === 'server_restarting') {
        setState('reconnecting');
      }
```

- [ ] **Step 8: Manual smoke test**

```bash
cd /home/chris/gibberly && source .venv/bin/activate
uvicorn backend.main:app --reload
```
Open `http://localhost:8000/listen/index.html` in browser — confirm no JS errors in console.

- [ ] **Step 9: Commit**

```bash
git add operator/app.js operator/index.html
git commit -m "fix: operator console security — DOM methods, backendHttp, reconnecting state"
```

---

## Task 8: `listener/app.js` — innerHTML fixes + join token passthrough

**Files:**
- Modify: `listener/app.js`

- [ ] **Step 1: Fix `langSelect` innerHTML (lines 136 and 148)**

Find (line 136):
```javascript
      langSelect.innerHTML = '';
```
Replace with:
```javascript
      langSelect.replaceChildren();
```

Find (line 148):
```javascript
      langSelect.innerHTML = '<option value="en">English</option>';
```
Replace with:
```javascript
      const defaultOpt = document.createElement('option');
      defaultOpt.value = 'en';
      defaultOpt.textContent = 'English';
      langSelect.replaceChildren(defaultOpt);
```

- [ ] **Step 2: Read join token from query string and pass to `/negotiate`**

Find where the listener reads the query string for `session`. It will look like:
```javascript
  const params = new URLSearchParams(location.search);
  const sessionId = params.get('session');
```

Add:
```javascript
  const joinToken = params.get('token') || '';
```

Find the `/negotiate` fetch call. It will look like:
```javascript
  const r = await fetch(`/negotiate?session=${sessionId}&lang=${lang}`);
```
Replace with:
```javascript
  const r = await fetch(`/negotiate?session=${encodeURIComponent(sessionId)}&lang=${encodeURIComponent(lang)}&token=${encodeURIComponent(joinToken)}`);
```

- [ ] **Step 3: Manual smoke test**

With the backend running, navigate to `http://localhost:8000/listen/live` — confirm redirect includes `?session=...&token=...` and the listener page loads without console errors.

- [ ] **Step 4: Commit**

```bash
git add listener/app.js
git commit -m "fix: listener page — DOM methods, pass join token to /negotiate"
```

---

## Task 9: Dockerfile + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY listener/ ./listener/
COPY operator/ ./operator/

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 15s
```

- [ ] **Step 3: Build and verify**

```bash
cd /home/chris/gibberly
docker compose build
docker compose up -d
curl -s http://localhost:8000/health
docker compose down
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose for self-hosted deployment"
```

---

## Task 10: `deploy/azure.bicep` + `.env.example`

**Files:**
- Create: `deploy/azure.bicep`
- Modify: `.env.example`

- [ ] **Step 1: Create `deploy/azure.bicep`**

```bicep
@description('Location for all resources')
param location string = resourceGroup().location

@description('Prefix for resource names')
param prefix string = 'gibberly'

// ── Speech ───────────────────────────────────────────────────────────────────
resource speech 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${prefix}-speech'
  location: location
  kind: 'SpeechServices'
  sku: { name: 'S0' }
  properties: { publicNetworkAccess: 'Enabled' }
}

// ── Azure OpenAI ─────────────────────────────────────────────────────────────
resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${prefix}-openai'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: { publicNetworkAccess: 'Enabled' }
}

resource gpt4omini 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: 'gpt-4o-mini'
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: '2024-07-18' }
  }
  sku: { name: 'Standard', capacity: 10 }
}

// ── Web PubSub ───────────────────────────────────────────────────────────────
resource pubsub 'Microsoft.SignalRService/webPubSub@2023-02-01' = {
  name: '${prefix}-pubsub'
  location: location
  sku: { name: 'Standard_S1', capacity: 1 }
  properties: { publicNetworkAccess: 'Enabled' }
}

// ── Outputs for .env ─────────────────────────────────────────────────────────
output AZURE_SPEECH_KEY string = speech.listKeys().key1
output AZURE_SPEECH_REGION string = location
output AZURE_OPENAI_ENDPOINT string = openai.properties.endpoint
output AZURE_OPENAI_API_KEY string = openai.listKeys().key1
output AZURE_OPENAI_DEPLOYMENT string = 'gpt-4o-mini'
output AZURE_WEBPUBSUB_CONNECTION_STRING string = pubsub.listKeys().primaryConnectionString
output LISTENER_TOKEN_SECRET string = uniqueString(pubsub.id, 'listener-token')
```

- [ ] **Step 2: Update `.env.example`**

Replace the contents of `.env.example` with:

```bash
# ── Azure credentials (from: az deployment group create --template-file deploy/azure.bicep) ──

# Bicep output: AZURE_SPEECH_KEY
AZURE_SPEECH_KEY=

# Bicep output: AZURE_SPEECH_REGION (e.g. westeurope)
AZURE_SPEECH_REGION=

# Bicep output: AZURE_WEBPUBSUB_CONNECTION_STRING
AZURE_WEBPUBSUB_CONNECTION_STRING=

# Bicep output: AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_ENDPOINT=

# Bicep output: AZURE_OPENAI_API_KEY
AZURE_OPENAI_API_KEY=

# Bicep output: AZURE_OPENAI_DEPLOYMENT (default: gpt-4o-mini)
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# ── Security (required) ───────────────────────────────────────────────────────

# Bicep output: LISTENER_TOKEN_SECRET — 32+ char random string, signs listener QR codes
LISTENER_TOKEN_SECRET=

# Allowed CORS origins, comma-separated (default: http://localhost:8000)
# CORS_ORIGINS=https://yourdomain.com

# Set to false for local HTTP development (default: true)
# FORCE_HTTPS=true

# Enable /listen/debug.html diagnostic page (default: false, never enable in production)
# DEBUG=false

# ── Session limits ────────────────────────────────────────────────────────────

# Hard maximum session duration in hours (default: 3.0)
# MAX_SESSION_HOURS=3.0

# Idle timeout in seconds before session is closed (default: 3600)
# SESSION_TIMEOUT_S=3600

# ── Server ────────────────────────────────────────────────────────────────────

# BACKEND_HOST=0.0.0.0
# BACKEND_PORT=8000

# ── STT tuning ────────────────────────────────────────────────────────────────

# STT_SILENCE_TIMEOUT_MS=1000
# STT_TIME_CAP_S=8.0

# ── LLM tuning ───────────────────────────────────────────────────────────────

# LLM_CONTEXT_WINDOW=5
```

- [ ] **Step 3: Commit**

```bash
git add deploy/azure.bicep .env.example
git commit -m "feat: Azure Bicep self-hosting template and improved .env.example"
```

---

## Task 11: Run full test suite + final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /home/chris/gibberly && source .venv/bin/activate
pytest tests/ -v 2>&1 | tee /tmp/test-results.txt
tail -5 /tmp/test-results.txt
```
Expected: all tests pass, 0 failures.

- [ ] **Step 2: Verify Docker build still passes**

```bash
docker compose build 2>&1 | tail -5
```
Expected: `Successfully built` (or equivalent).

- [ ] **Step 3: Verify no secrets in codebase**

```bash
grep -r "AZURE_SPEECH_KEY\s*=" backend/ --include="*.py" | grep -v "os.environ" | grep -v "settings\."
git ls-files .env
```
Expected: no hardcoded key values, `.env` not tracked.

- [ ] **Step 4: Final commit**

```bash
git add .
git status  # review — should be clean
git commit -m "chore: final verification pass — all tests green, no secrets in repo" --allow-empty
```

---

## Out of Scope (separate plan)

- `gibberly-app` private Electron repo scaffolding
- Licence server (Azure Functions + Table Storage)
- Redis session state for horizontal scaling
