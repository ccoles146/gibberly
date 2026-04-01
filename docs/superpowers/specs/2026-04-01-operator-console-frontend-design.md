# Operator Console Frontend — Design Spec
**Date:** 2026-04-01
**Status:** Approved

---

## Overview

A standalone static web page that replaces the Python CLI operator console. The operator opens it in a browser on the Mac (or any PC), selects the Dante audio input device and channel (or a WAV file for testing), clicks Start, and the page streams 16kHz 16-bit mono PCM to the Gibberly backend over WebSocket. It displays a permanent QR code for listeners, live listener count, elapsed time, and the last translated phrase.

The page is entirely static — no build step, no server required. It is served independently of the FastAPI backend, which enables the backend to move to Azure without any changes to the operator workflow.

---

## File Structure

```
operator/
  config.js        ← only file edited per deployment
  index.html       ← UI shell
  app.js           ← session management, QR rendering, status updates
  worklet.js       ← AudioWorklet: channel select + resample to 16kHz 16-bit mono
  qrcode.min.js    ← bundled QR library (no CDN dependency)
```

### config.js

```js
window.GIBBERLY_BACKEND = "ws://192.168.178.139:8000";
// Change to wss://gibberly.azurewebsites.net for Azure deployment
```

To point at Azure, edit this one line. The rest of the operator directory is unchanged.

---

## Backend Changes

### 1. CORS middleware

Add `CORSMiddleware` to `backend/main.py` so the operator page (served from a different origin) can reach the HTTP endpoints:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

WebSocket CORS is not enforced by FastAPI/uvicorn, so `/ws/stream` works across origins already.

### 2. Stable listener URL — `/listen/live`

The QR code encodes a fixed URL (`{backend_http_root}/listen/live`) that is known before any session starts. The backend tracks the current active session and redirects accordingly:

```python
app.state.current_session_id: Optional[str] = None
```

- **On session start** (`/ws/stream` connect): set `app.state.current_session_id = handler.session_id`
- **On session end** (WebSocket disconnect): clear `app.state.current_session_id = None`

New endpoint:

```python
@app.get("/listen/live")
def live_redirect(request: Request):
    sid = app.state.current_session_id
    if not sid:
        # Return a simple "not live yet" HTML page
        return HTMLResponse("<h2>No live session at the moment.</h2>", status_code=503)
    return RedirectResponse(f"/listen/index.html?session={sid}")
```

The `listener_url` field in the `session_created` WebSocket message is **no longer used by the operator page** for QR generation — the QR URL is constructed from `config.js` alone:

```js
const liveUrl = window.GIBBERLY_BACKEND
  .replace(/^ws:/, 'http:')
  .replace(/^wss:/, 'https:') + '/listen/live';
```

---

## UI Layout

```
┌─────────────────────────────────────┐
│  ● LIVE  |  listeners: 2  |  04:32  │  ← status bar
├─────────────────────────────────────┤
│                                     │
│          [QR code here]             │  ← shown always
│   https://…/listen/live             │
│                                     │
│   "…last translated phrase…"        │
│                                     │
├─────────────────────────────────────┤
│  [Audio input ▾] [Channel ▾] [Stop] │  ← controls
└─────────────────────────────────────┘
```

The QR code is rendered on page load from the stable `/listen/live` URL and never changes.

### State Machine

| State | Button label | Button enabled | QR | Status bar |
|---|---|---|---|---|
| `idle` | ▶ Start | yes | shown (stable) | OFFLINE |
| `connecting` | connecting… | no | shown (stable) | CONNECTING… |
| `live` | ■ Stop | yes | shown (stable) | LIVE · listeners · elapsed |
| `error` | ▶ Retry | yes | shown (stable) | error message |

### Controls

- **Audio input dropdown** — populated via `enumerateDevices()` filtered to `audioinput`, plus a **"Browse file…"** option at the bottom of the list. Refreshed on load. Selected value persisted to `localStorage`.
- **Channel dropdown** — visible only when a device (not file) is selected and reports ≥ 2 channels. Options: Left / Right / Mix. Persisted to `localStorage`. Hidden for mono devices and file mode.
- **Start/Stop button** — single button, label and action depend on state.

Audio constraints applied on `getUserMedia`: `echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false` — appropriate for a line-level Dante feed.

---

## Audio Pipeline

### Device mode (Dante / DeckLink / any audio input)

```
getUserMedia({ deviceId, echoCancellation: false, … })
  → MediaStreamSource
  → AudioWorkletNode('gibberly-resampler', { channelMode })
  → port.postMessage(Int16Array, 320 samples = 20 ms @ 16kHz)
  → app.js sends chunk as WebSocket binary frame
```

### File mode ("Browse file…")

```
<input type="file"> → File → ArrayBuffer
  → chunk into 640-byte frames (320 × Int16)
  → drip-feed over WebSocket at 20 ms intervals (setTimeout)
```

The worklet is not used in file mode. Files are assumed to be 16kHz 16-bit mono PCM WAV — no resampling is performed. This mirrors the Python `--mode file` behaviour exactly.

### worklet.js — gibberly-resampler

- Receives audio blocks at the browser's native `AudioContext` sample rate (44100 or 48000 Hz on macOS).
- **Channel selection** passed as constructor option (`channelMode`: `"left"` | `"right"` | `"mix"`):
  - `left` → `inputs[0][0]`
  - `right` → `inputs[0][1]`
  - `mix` → average of `inputs[0][0]` and `inputs[0][1]`
- **Resampling**: linear interpolation from native rate to 16000 Hz using a fractional accumulator.
- Accumulates resampled float samples, converts to `Int16Array` (multiply by 32767, clamp), posts a 320-sample buffer per 20 ms tick.
- Channel mode is fixed at construction — no mid-stream switching.

320 samples at 16kHz = 640 bytes per chunk, matching the Python `FileAudioSource` output. Backend unchanged.

### Development note

`getUserMedia` requires a secure context: `https://` or `localhost`. During local development, serve the operator directory with any static server (e.g. `python3 -m http.server 9000` in `operator/`). File mode works without a secure context. For Azure deployment, serve from Azure Static Web Apps (free tier) over HTTPS.

---

## WebSocket Protocol

Unchanged from current backend contract:

**Backend → Operator (JSON):**
```json
{ "type": "session_created", "session_id": "…", "listener_url": "https://…" }
{ "type": "phrase", "text": "…" }
{ "type": "listeners", "count": 2 }
```

**Operator → Backend (binary):** raw `Int16Array` chunks, 640 bytes each.

The `listener_url` field in `session_created` is ignored by the operator page — the QR URL is derived from `config.js` instead.

---

## QR Code

Generated client-side using the bundled `qrcode-generator` library (no CDN, no network dependency). Rendered as an SVG on page load from the stable URL `{backend_http_root}/listen/live`. The URL is also shown as a copyable text link below the QR. The QR never changes — listeners can bookmark or screenshot it once and reuse it every week.

---

## Deployment

### Local / development
```
# Terminal 1 — backend
cd ~/gibberly
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — operator page
cd ~/gibberly/operator
python3 -m http.server 9000
# Open http://localhost:9000 in browser
# (use file mode for testing without getUserMedia secure context)
```

### Azure
1. Deploy backend to Azure Container App / Azure Function — no code changes needed beyond `.env` values.
2. Update `operator/config.js` to point at the Azure backend URL (`wss://…`).
3. Deploy `operator/` to Azure Static Web Apps (free tier) or any static host over HTTPS.
