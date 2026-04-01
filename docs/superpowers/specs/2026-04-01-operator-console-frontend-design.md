# Operator Console Frontend — Design Spec
**Date:** 2026-04-01
**Status:** Approved

---

## Overview

A standalone static web page that replaces the Python CLI operator console. The operator opens it in a browser on the Mac (or any PC), selects the Dante audio input device and channel, clicks Start, and the page streams 16kHz 16-bit mono PCM to the Gibberly backend over WebSocket. It displays a QR code for listeners, live listener count, elapsed time, and the last translated phrase.

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

Add `CORSMiddleware` to `backend/main.py` so the operator page (served from a different origin) can reach the HTTP endpoints:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

WebSocket CORS is not enforced by FastAPI/uvicorn, so `/ws/stream` works across origins already. No other backend changes are required.

---

## UI Layout

```
┌─────────────────────────────────────┐
│  ● LIVE  |  listeners: 2  |  04:32  │  ← status bar
├─────────────────────────────────────┤
│                                     │
│          [QR code here]             │  ← hidden until session starts
│   https://…/listen?session=…        │
│                                     │
│   "…last translated phrase…"        │
│                                     │
├─────────────────────────────────────┤
│  [Audio input ▾] [Channel ▾] [Stop] │  ← controls
└─────────────────────────────────────┘
```

### State Machine

| State | Button label | Button enabled | QR | Status bar |
|---|---|---|---|---|
| `idle` | ▶ Start | yes | hidden | OFFLINE |
| `connecting` | connecting… | no | hidden | CONNECTING… |
| `live` | ■ Stop | yes | shown | LIVE · listeners · elapsed |
| `error` | ▶ Retry | yes | hidden | error message |

### Controls

- **Audio input dropdown** — populated via `enumerateDevices()` filtered to `audioinput`. Refreshed on load. Selected value persisted to `localStorage`.
- **Channel dropdown** — visible only when selected device reports ≥ 2 channels. Options: Left / Right / Mix. Persisted to `localStorage`. Hidden for mono devices.
- **Start/Stop button** — single button, label and action depend on state.

Audio constraints applied on `getUserMedia`: `echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false` — appropriate for a line-level Dante feed.

---

## Audio Pipeline

```
getUserMedia({ deviceId, echoCancellation: false, … })
  → MediaStreamSource
  → AudioWorkletNode('gibberly-resampler', { channelMode })
  → port.postMessage(Int16Array, 320 samples = 20 ms @ 16kHz)
  → app.js sends chunk as WebSocket binary frame
```

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

`getUserMedia` requires a secure context: `https://` or `localhost`. During local development, serve the operator directory with any static server (e.g. `python3 -m http.server 9000` in `operator/`). For Azure deployment, serve from Azure Static Web Apps (free tier) over HTTPS.

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

The operator page derives the QR code content directly from `listener_url` in the `session_created` message.

---

## QR Code

Generated client-side using the bundled `qrcode-generator` library (no CDN, no network dependency). Rendered as an SVG into a `<div>` after `session_created` is received. The listener URL is also shown as a copyable text link below the QR.

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
```

### Azure
1. Deploy backend to Azure Container App / Azure Function — no code changes needed beyond `.env` values.
2. Update `operator/config.js` to point at the Azure backend URL (`wss://…`).
3. Deploy `operator/` to Azure Static Web Apps (free tier) or any static host.
