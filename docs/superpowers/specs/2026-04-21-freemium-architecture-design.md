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

async def on_session_end(ctx: LicenceContext, audio_in_sec: float, audio_out_sec: float, language_count: int) -> None:
    """Called when session closes. Reports usage to licence server (best-effort)."""
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
8. Licence server: Cloudflare Worker + D1 (separate service, not in this repo)

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
| `deploy/azure.bicep` | Provisions Speech S0, Azure OpenAI, Web PubSub Free; outputs keys for `.env` paste |

### Modified files

| File | Change |
|------|--------|
| `backend/main.py` | Register HTTP auth middleware; call `validate_request` at WebSocket upgrade |
| `backend/session.py` | Accept `LicenceContext`; call `on_session_end` on session close |
| `operator/app.js` | Read `window.GIBBERLY_API_URL` if present (Electron compatibility shim) |
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

## Scalability Note (V1 caveat)

Sessions currently live in FastAPI process memory. For dozens of concurrent organisations this is sufficient. When horizontal scaling is needed, move session state to Redis — `SessionHandler` in `session.py` is already isolated enough for this swap without touching other modules.

---

## Verification

- `docker-compose up` starts backend; `curl localhost:8000/health` returns 200
- Bicep template deploys cleanly on a test Azure subscription
- Electron app opens operator UI, `window.GIBBERLY_API_URL` is set correctly (DevTools console)
- `X-License-Key` header present on all Electron outbound requests (DevTools Network tab)
- Self-hosted path: no licence key sent, no-op `validate_request` passes, session starts normally
- `on_session_end` called when session closes (logged in self-hosted mode)
