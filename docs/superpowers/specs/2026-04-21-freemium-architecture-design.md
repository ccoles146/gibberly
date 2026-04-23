# Freemium Architecture Design

**Date:** 2026-04-21
**Status:** Approved

## Context

Gibberly needs to support two tiers from a single backend codebase:

- **Free / self-hosted** — users provision their own Azure resources and run the Python backend themselves; open-source under MIT
- **Paid / hosted** — churches install a Mac desktop app (Electron) that connects to a managed hosted backend; access gated by licence key

The Electron app is a thin native wrapper around the existing `operator/` web UI, not a rewrite. The backend is identical between tiers; the only difference is an injected auth module.

---

## Repo Split

| Repo | Visibility | Licence | Contents |
|------|-----------|---------|----------|
| `gibberly` | Public | MIT | backend, operator web UI, listener, console, tests, IaC |
| `gibberly-app` | Private | Proprietary | Electron wrapper, private auth module, hosted deploy config |

---

## Auth Hook (Approach B — injected at deploy time)

The public backend gains a two-function hook interface at `backend/auth.py`:

```python
from dataclasses import dataclass
from fastapi import Request

@dataclass
class LicenceContext:
    unlimited: bool = True

async def validate_request(request: Request) -> LicenceContext:
    """Called at session start. Raises HTTP 401 if key invalid/expired/exhausted."""
    return LicenceContext(unlimited=True)

async def on_session_start(ctx: LicenceContext, session_id: str) -> None:
    """Called after session start is confirmed. Registers session as active."""
    pass

async def on_session_end(ctx: LicenceContext, audio_in_sec: float, audio_out_sec: float, language_count: int) -> None:
    """Called when session closes. Reports usage and releases concurrent slot."""
    pass
```

The private `gibberly-app/auth/auth.py` overwrites this file at Docker build time:

```dockerfile
# gibberly-app/deploy/Dockerfile
FROM python:3.13-slim AS base
COPY gibberly-public/ /app/
COPY auth/auth.py /app/backend/auth.py   # inject private auth
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Licence Key Flow

1. Church admin receives licence key from website (out of scope)
2. Key entered once in Electron app → stored in OS keychain via `safeStorage`
3. Electron injects `X-License-Key` header on all requests via `session.webRequest` interceptor
4. Private `validate_request` calls a Cloudflare Worker licence server: checks key active + quota remaining
5. If valid: session proceeds; quota debited at session end via `on_session_end`
6. If quota exhausted or subscription lapsed: returns HTTP 401, Electron shows native dialog
7. **Mid-session quota exhaustion**: session is allowed to complete — no billing overages in V1
8. Licence server: Azure Functions + Table Storage (separate service, not in this repo)

### Per-customer rate limiting

The private `validate_request` enforces two limits before allowing a session to start:

1. **Concurrent session cap** — the licence server tracks how many active sessions a key has open. Default cap: 1 concurrent session (a church only has one service at a time). Attempting to start a second session returns HTTP 429 with `{reason: "concurrent_limit"}`.
2. **Quota gate** — if the key has zero remaining quota (audio input minutes exhausted for the period), returns HTTP 402 with `{reason: "quota_exhausted"}`. Mid-session exhaustion is still allowed to complete (V1 policy).

The no-op `validate_request` in the public backend always returns unlimited, so self-hosters are unaffected.

Concurrent session tracking requires the licence server to accept a `session_opened` signal at session start and a `session_closed` signal at end — `on_session_end` covers the close; a new `on_session_start` call is added:

```python
async def on_session_start(ctx: LicenceContext, session_id: str) -> None:
    """Notifies licence server that a session is now active. No-op in self-hosted."""
    pass
```

### Cost attribution

`on_session_end` is the attribution record. The licence server persists:

```
{licence_key, session_id, started_at, audio_in_sec, audio_out_sec, language_count}
```

Stored in **Azure Table Storage** (cheap, no schema, natural key-value fit): one table for licence records (key → subscription status, plan limits, period usage) and one for session history. The licence server is an **Azure Functions** HTTP-trigger app in the same resource group as the rest of the infrastructure. The no-op public version logs the values at DEBUG level so self-hosters can verify the hooks fire.

### What counts as usage

- **Audio input**: seconds of STT processing (measured in `stt.py`)
- **Audio output**: TTS synthesis seconds × number of active listener languages (measured in `tts.py` + `session.py`)

---

## Electron App (`gibberly-app`)

```
gibberly-app/
  electron/
    main.js        ← BrowserWindow, keychain, request interceptor, auto-updater stub
    preload.js     ← contextBridge exposing GIBBERLY_API_URL to renderer
  operator/        ← copy of gibberly/operator/ at build time
  auth/
    auth.py        ← private licence validation hook
  deploy/
    Dockerfile     ← injects private auth.py over public backend
    docker-compose.prod.yml
  scripts/
    build-mac.sh   ← electron-builder, sign + notarise for macOS
  package.json
```

`electron/main.js` responsibilities:
- Open `BrowserWindow` loading `operator/index.html`
- On first launch: prompt for licence key → store via `safeStorage`
- Inject `GIBBERLY_API_URL` (set at build time via env var) and stored licence key into every outbound request via `session.webRequest` interceptor — no changes to `operator/app.js` needed beyond reading `window.GIBBERLY_API_URL`
- Handle `licence_terminated` WebSocket event with a native dialog

Mac distribution requires an Apple Developer account ($99/year). GitHub Actions in the private repo handles signing + notarisation via stored certificates.

---

## Self-Hosting Changes to `gibberly`

### New files

| File | Purpose |
|------|---------|
| `backend/auth.py` | No-op hook (see above) |
| `Dockerfile` | Python 3.13 slim, installs requirements, runs uvicorn |
| `docker-compose.yml` | Single service, reads `.env`, exposes port 8000 |
| `deploy/azure.bicep` | Provisions Speech S0, Azure OpenAI, Web PubSub Standard S1; outputs keys for `.env` paste |

### Modified files

| File | Change |
|------|--------|
| `backend/main.py` | Register HTTP auth middleware; call `validate_request` at WebSocket upgrade |
| `backend/session.py` | Accept `LicenceContext`; call `on_session_start` after start, `on_session_end` on close; enforce `MAX_SESSION_HOURS` hard limit |
| `backend/config.py` | Add `max_session_hours` setting (default 3.0) |
| `backend/main.py` | Broadcast `{type: "server_restarting"}` on SIGTERM before shutdown |
| `operator/app.js` | Read `window.GIBBERLY_API_URL` if present; add `reconnecting` state with exponential backoff |
| `.env.example` | Inline comments referencing Bicep output field names |

### Self-hosting story

```bash
# 1. Provision Azure (one command)
az deployment group create \
  --resource-group gibberly-rg \
  --template-file deploy/azure.bicep

# 2. Paste output credentials into .env
cp .env.example .env
# edit .env

# 3. Run
docker-compose up
```

The existing `docs/azure-setup.md` remains as the manual fallback.

---

## Session Hard Limit

Sessions have a configurable absolute maximum duration, enforced in `SessionHandler` regardless of activity. When the limit is reached the session is closed cleanly (same path as a normal stop): `on_session_end` is called, Web PubSub receives a `{type: "session_ended", reason: "max_duration"}` event, and the operator console returns to idle.

**Default: 3 hours.** Configurable via `MAX_SESSION_HOURS` in `.env` — self-hosters can raise or lower it. The paid hosted service sets it to 3 hours and the Electron app surfaces a warning at 15 minutes remaining.

Add to `backend/config.py`:
```python
max_session_hours: float = 3.0  # MAX_SESSION_HOURS env var
```

`SessionHandler` already has a 60-minute idle timeout; the hard limit is independent — the session ends at whichever comes first.

---

## Process Reliability

Single-process failure drops all active sessions simultaneously. The fix is two-layered: fast automatic restart + graceful client reconnection, so a crash during a sermon recovers within a few seconds without operator intervention.

**Backend (docker-compose.yml):**
```yaml
services:
  backend:
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
```
Docker restarts the process immediately on crash. A cold restart takes 2–4 seconds.

**Graceful shutdown (`backend/main.py`):**
On `SIGTERM`, broadcast `{type: "server_restarting"}` to all active WebSocket sessions before closing. Clients that receive this can show "Reconnecting…" rather than an error.

**Client reconnection (`operator/app.js`):**
The existing state machine (idle → connecting → live → error) gains a `reconnecting` state. On WebSocket close (whether or not preceded by `server_restarting`), the operator console retries connection with exponential backoff (1s, 2s, 4s, max 10s). On successful reconnect the operator clicks Start again — a new session begins. Listeners auto-reconnect to Web PubSub independently (already handled by the Azure SDK client).

This makes a process crash a ~10 second interruption rather than a manual recovery event. In-memory session state is still lost on restart (Redis deferred to a later milestone).

## Security

### CORS

`CORSMiddleware` is restricted to explicit origins — never wildcard. Configurable via `CORS_ORIGINS` in `.env` (comma-separated). Default for self-hosted: `http://localhost:8000`. The paid hosted backend sets it to the production domain only. Electron's BrowserWindow origin is `null` (file://), so the Electron app bypasses CORS entirely and is not listed.

### Listener join tokens

Session URLs are not shared as bare `?session=<uuid>` links. When the operator starts a session, the backend generates a short-lived **join token** (HMAC-SHA256 of `session_id + secret + expiry`, 24-hour TTL). The QR code and listener URL embed this token: `/listen?session=<id>&token=<tok>`. The `/negotiate` endpoint validates the token before issuing a Web PubSub credential. This prevents anyone who guesses or observes a session ID from joining as a listener without the operator's QR code.

`backend/config.py` gains a `listener_token_secret` setting (random 32-byte hex, required in `.env`). The Bicep template generates one automatically.

### Rate limiting

`slowapi` applied to all public HTTP endpoints. Limits:
- `/languages`, `/health`: 60/minute per IP
- `/session/{id}/join`, `/leave`, `/audio/join`, `/audio/leave`: 20/minute per IP
- `/negotiate`: 10/minute per IP

WebSocket connections are rate-limited at the OS/reverse-proxy level (nginx `limit_conn`).

### HTTPS enforcement

The backend assumes TLS is terminated at the reverse proxy (nginx or Azure App Service). `listener_url` construction uses `https://` unconditionally in production. A `FORCE_HTTPS=true` env var (default `true`) adds an HSTS header to all responses. Self-hosters who run locally set `FORCE_HTTPS=false`.

### Debug page

`/listen/debug.html` is only served when `DEBUG=true` in `.env`. In production it returns 404.

### Security headers

All responses include:
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`

### Azure credential scope

**Self-hosted:** API keys are unavoidable — users generate their own and store them in `.env`. The Bicep template creates a dedicated resource group with the minimum required services; there is no subscription-level credential involved.

**Hosted paid backend:** The backend runs on Azure (App Service or Container Apps) and uses **Managed Identity** — no API keys in `.env` at all. The Azure SDK's `DefaultAzureCredential` is used for all three services:

| Service | Self-hosted auth | Hosted auth |
|---------|-----------------|-------------|
| Speech (STT + TTS) | `AZURE_SPEECH_KEY` | Managed Identity |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | Managed Identity |
| Web PubSub | `AZURE_WEBPUBSUB_CONNECTION_STRING` | Managed Identity |

`backend/config.py` detects whether keys are present; if absent it falls back to `DefaultAzureCredential`. The SDK clients in `stt.py`, `tts.py`, `pubsub.py`, and `llm_translator.py` are updated to accept either a key or a credential object.

This eliminates the largest class of credential-leakage risk on the hosted path — there are no keys to rotate, expose in logs, or leak via environment dumps.

### Error sanitisation

Exception strings are never forwarded to WebSocket clients or HTTP responses. Clients receive a fixed message type (e.g. `{type: "tts_error"}`); full detail is logged server-side only. `backend/main.py` installs a global exception handler enforcing this.

### Input validation

All `lang` query parameters are validated against the `SUPPORTED_LANGUAGES` list before use. Invalid values return HTTP 400. WebSocket binary frames are capped at 1 MB; larger frames are rejected and the connection closed.

### Modified files (security additions)

| File | Change |
|------|--------|
| `backend/main.py` | CORS restricted origins; HSTS + CSP + security headers middleware; rate limiting; global error sanitiser; 1 MB WS frame cap |
| `backend/config.py` | Add `cors_origins`, `listener_token_secret`, `force_https`, `debug` settings |
| `backend/auth.py` | `generate_listener_token(session_id)` and `validate_listener_token(session_id, token)` helpers |
| `operator/app.js` | Use `textContent` not `innerHTML` for all user-sourced data; sanitise console log output |
| `listener/app.js` | Use `textContent`/DOM methods for language list and transcript rendering |
| `deploy/azure.bicep` | Generate `LISTENER_TOKEN_SECRET` and output to `.env`; assign Managed Identity roles for hosted deployment |
| `backend/stt.py` | Accept `DefaultAzureCredential` when no key present |
| `backend/tts.py` | Accept `DefaultAzureCredential` when no key present |
| `backend/pubsub.py` | Accept `DefaultAzureCredential` when no key present |
| `backend/llm_translator.py` | Accept `DefaultAzureCredential` when no key present |

---

## Scalability Note (V1 caveat)

Sessions live in FastAPI process memory. For dozens of concurrent organisations this is sufficient. When horizontal scaling is needed, move session state to Redis — `SessionHandler` in `session.py` is already isolated enough for this swap without touching other modules.

---

## Verification

- `docker-compose up` starts backend; `curl localhost:8000/health` returns 200
- Bicep template deploys cleanly on a test Azure subscription
- Electron app opens operator UI, `window.GIBBERLY_API_URL` is set correctly (DevTools console)
- `X-License-Key` header present on all Electron outbound requests (DevTools Network tab)
- Self-hosted path: no licence key sent, no-op `validate_request` passes, session starts normally
- `on_session_start` and `on_session_end` called at session open/close (DEBUG log in self-hosted mode)
- Killing the backend process mid-session: Electron operator shows "Reconnecting…" and recovers within 10 seconds
- Second session start with same licence key returns HTTP 429 (paid path only)
- Azure Table Storage has a usage record after each session completes
- Listener URL without a valid join token returns HTTP 401 from `/negotiate`
- `/listen/debug.html` returns 404 when `DEBUG=false`
- `curl -X OPTIONS` with a foreign `Origin` header returns 403
- Error response bodies contain no stack traces or Azure resource names
