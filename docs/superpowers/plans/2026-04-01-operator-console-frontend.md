# Operator Console Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone static operator console web page that captures audio from a browser-selectable input device, resamples to 16kHz 16-bit mono PCM, streams it to the Gibberly backend over WebSocket, and displays a permanent QR code, listener count, and last translated phrase.

**Architecture:** A static `operator/` directory (no build step) served independently of the FastAPI backend. The backend gains a `/listen/live` redirect endpoint that always points to the current active session, making the QR code stable across restarts. An AudioWorklet handles client-side resampling; a file mode bypasses it for testing.

**Tech Stack:** Vanilla JS, Web Audio API (AudioWorklet), WebSocket API, `qrcode-generator` (bundled), FastAPI (CORSMiddleware + new route), pytest + httpx for backend tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/main.py` | CORS, `/listen/live` route, `current_session_id` state |
| Modify | `tests/backend/test_main.py` | Tests for new backend routes |
| Create | `operator/config.js` | Backend URL constant (only file changed per deployment) |
| Create | `operator/index.html` | UI shell — markup and styles |
| Create | `operator/qrcode.min.js` | Bundled QR library (fetched once, committed) |
| Create | `operator/worklet.js` | AudioWorklet processor: channel select + linear resample to 16kHz |
| Create | `operator/app.js` | Device enumeration, state machine, QR render, WebSocket, audio pipeline, file mode |

---

## Task 1: Backend — `/listen/live` + `current_session_id`

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/backend/test_main.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/backend/test_main.py`:

```python
@patch("backend.main.SessionHandler")
def test_live_redirect_no_session(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd ~/gibberly && source .venv/bin/activate
pytest tests/backend/test_main.py::test_live_redirect_no_session tests/backend/test_main.py::test_live_redirect_active_session -v
```

Expected: both fail with `404` or `AttributeError`.

- [ ] **Step 3: Implement `/listen/live` and `current_session_id` in `backend/main.py`**

Replace the top of `backend/main.py` with:

```python
import asyncio
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.session import SessionHandler

app = FastAPI(title="Gibberly Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.state.sessions: Dict[str, SessionHandler] = {}
app.state.current_session_id: Optional[str] = None

LISTENER_DIR = Path(__file__).parent.parent / "listener"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/negotiate")
def negotiate(session: str):
    handler = app.state.sessions.get(session)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"url": handler.listener_token}


@app.get("/listen/live")
def live_redirect():
    sid = app.state.current_session_id
    if not sid:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:3rem'>"
            "<h2>No live session at the moment.</h2>"
            "<p>The service will be available when the operator starts a session.</p>"
            "</body></html>",
            status_code=503,
        )
    return RedirectResponse(f"/listen/index.html?session={sid}", status_code=302)


@app.post("/session/{session_id}/join")
def listener_join(session_id: str):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"count": handler.listener_join()}


@app.post("/session/{session_id}/leave")
def listener_leave(session_id: str):
    handler = app.state.sessions.get(session_id)
    if not handler:
        return {"count": 0}
    return {"count": handler.listener_leave()}


@app.websocket("/ws/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()

    async def send_status(msg: dict) -> None:
        await websocket.send_json(msg)

    handler = SessionHandler(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        pubsub_cs=settings.azure_webpubsub_connection_string,
        loop=loop,
        on_status=send_status,
    )
    app.state.sessions[handler.session_id] = handler
    app.state.current_session_id = handler.session_id
    handler.start()

    await websocket.send_json({
        "type": "session_created",
        "session_id": handler.session_id,
        "listener_url": (
            f"http://{settings.backend_host}:{settings.backend_port}"
            f"/listen/index.html?session={handler.session_id}"
        ),
    })

    try:
        while True:
            data = await websocket.receive_bytes()
            handler.write(data)
    except WebSocketDisconnect:
        pass
    finally:
        handler.stop()
        app.state.sessions.pop(handler.session_id, None)
        if app.state.current_session_id == handler.session_id:
            app.state.current_session_id = None


if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
```

Note: `/listen/live` **must** be defined before `app.mount("/listen", …)` — FastAPI routes registered first take precedence over static file mounts.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/backend/test_main.py -v
```

Expected: all existing tests plus both new tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: add /listen/live redirect and CORS middleware"
```

---

## Task 2: operator/config.js + operator/index.html

**Files:**
- Create: `operator/config.js`
- Create: `operator/index.html`

- [ ] **Step 1: Create `operator/config.js`**

```js
// Edit this line to point at your backend.
// Local dev:  ws://192.168.178.139:8000
// Azure:      wss://your-app.azurewebsites.net
window.GIBBERLY_BACKEND = "ws://localhost:8000";
```

- [ ] **Step 2: Create `operator/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gibberly — Operator Console</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111; color: #f0f0f0;
      min-height: 100vh;
      display: flex; flex-direction: column; align-items: center;
      padding: 1.5rem 1rem;
      gap: 1.5rem;
    }

    /* Status bar */
    #status-bar {
      width: 100%; max-width: 480px;
      display: flex; align-items: center; gap: 1rem;
      background: #1e1e1e; border-radius: 0.75rem;
      padding: 0.75rem 1.25rem;
      font-size: 0.9rem;
    }
    #status-dot {
      width: 10px; height: 10px; border-radius: 50%;
      background: #555; flex-shrink: 0;
    }
    #status-dot.live { background: #22c55e; }
    #status-dot.connecting { background: #f59e0b; }
    #status-dot.error { background: #ef4444; }
    #status-text { flex: 1; color: #aaa; }
    #stat-listeners { color: #f0f0f0; }
    #stat-elapsed  { color: #f0f0f0; font-variant-numeric: tabular-nums; }

    /* QR section */
    #qr-section {
      width: 100%; max-width: 480px;
      background: #1e1e1e; border-radius: 0.75rem;
      padding: 1.5rem; text-align: center;
    }
    #qr-canvas { margin: 0 auto 1rem; }
    #qr-canvas table { margin: 0 auto; }
    #live-url {
      font-size: 0.8rem; color: #60a5fa;
      word-break: break-all; text-decoration: none;
    }
    #live-url:hover { text-decoration: underline; }

    /* Phrase */
    #last-phrase {
      width: 100%; max-width: 480px;
      min-height: 3rem;
      font-size: 1rem; color: #d1d5db;
      font-style: italic; text-align: center;
      padding: 0 0.5rem;
    }

    /* Controls */
    #controls {
      width: 100%; max-width: 480px;
      display: flex; gap: 0.75rem; align-items: center;
      flex-wrap: wrap;
    }
    select {
      flex: 1; min-width: 0;
      background: #2a2a2a; color: #f0f0f0;
      border: 1px solid #444; border-radius: 0.5rem;
      padding: 0.6rem 0.75rem; font-size: 0.9rem;
      cursor: pointer;
    }
    #channel-select { max-width: 100px; flex: none; }
    #file-input { display: none; }

    #action-btn {
      flex: none;
      padding: 0.6rem 1.5rem;
      background: #2563eb; color: #fff;
      border: none; border-radius: 0.5rem;
      font-size: 0.95rem; cursor: pointer;
      transition: background 0.15s;
    }
    #action-btn:hover:not(:disabled) { background: #1d4ed8; }
    #action-btn:disabled { background: #444; cursor: default; }
    #action-btn.stop { background: #dc2626; }
    #action-btn.stop:hover:not(:disabled) { background: #b91c1c; }
  </style>
</head>
<body>
  <div id="status-bar">
    <div id="status-dot"></div>
    <span id="status-text">OFFLINE</span>
    <span id="stat-listeners" style="display:none">listeners: <span id="listener-count">0</span></span>
    <span id="stat-elapsed"  style="display:none"><span id="elapsed">00:00</span></span>
  </div>

  <div id="qr-section">
    <div id="qr-canvas"></div>
    <a id="live-url" href="#" target="_blank"></a>
  </div>

  <p id="last-phrase"></p>

  <div id="controls">
    <select id="device-select"><option value="">Loading devices…</option></select>
    <select id="channel-select" style="display:none">
      <option value="left">Left</option>
      <option value="right">Right</option>
      <option value="mix">Mix</option>
    </select>
    <input type="file" id="file-input" accept=".wav">
    <button id="action-btn">▶ Start</button>
  </div>

  <script src="config.js"></script>
  <script src="qrcode.min.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Verify the page opens without errors**

```bash
cd ~/gibberly/operator
python3 -m http.server 9000
```

Open `http://localhost:9000` in a browser. Expected: page renders with status bar, empty QR section, controls visible. Console should show no JS errors (qrcode.min.js will 404 — that's expected at this stage).

- [ ] **Step 4: Commit**

```bash
git add operator/config.js operator/index.html
git commit -m "feat: add operator console HTML shell and config"
```

---

## Task 3: Bundle qrcode-generator library

**Files:**
- Create: `operator/qrcode.min.js`

- [ ] **Step 1: Fetch the library from npm CDN and save it**

```bash
cd ~/gibberly/operator
curl -L "https://unpkg.com/qrcode-generator@1.4.4/qrcode.js" -o qrcode.min.js
```

Verify the file starts with `var qrcode` or similar — it should be ~30KB:

```bash
head -3 operator/qrcode.min.js
wc -c operator/qrcode.min.js
```

- [ ] **Step 2: Verify the library works**

Open `http://localhost:9000` (if still running). The 404 for `qrcode.min.js` should be gone. Open the browser console — no errors expected.

- [ ] **Step 3: Commit**

```bash
git add operator/qrcode.min.js
git commit -m "chore: bundle qrcode-generator 1.4.4"
```

---

## Task 4: operator/worklet.js — AudioWorklet resampler

**Files:**
- Create: `operator/worklet.js`

No automated tests for the worklet (AudioWorklet runs in a dedicated thread and requires a real browser). Manual verification is in Task 6.

- [ ] **Step 1: Create `operator/worklet.js`**

```js
/**
 * gibberly-resampler AudioWorklet processor.
 *
 * Accepts audio at the browser's native sample rate, selects a channel,
 * resamples to 16000 Hz using linear interpolation, accumulates samples,
 * and posts a 320-sample Int16Array (20 ms) to the main thread each tick.
 *
 * Constructor options:
 *   channelMode: "left" | "right" | "mix"  (default: "left")
 */
class GibberlyResampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._channelMode = (options.processorOptions || {}).channelMode || "left";
    this._targetRate = 16000;
    this._accumulator = [];   // float samples waiting to be posted
    this._phase = 0;          // fractional position in the input stream
    this._prevSample = 0;     // last sample from previous block (for interpolation)
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    // Select / mix channels
    let mono;
    if (this._channelMode === "mix" && input.length >= 2) {
      const l = input[0], r = input[1];
      mono = new Float32Array(l.length);
      for (let i = 0; i < l.length; i++) mono[i] = (l[i] + r[i]) * 0.5;
    } else if (this._channelMode === "right" && input.length >= 2) {
      mono = input[1];
    } else {
      mono = input[0];
    }

    // Linear interpolation resample: native rate → 16000 Hz
    const ratio = sampleRate / this._targetRate;  // sampleRate is global in AudioWorklet
    let phase = this._phase;
    let prev = this._prevSample;

    while (phase < mono.length) {
      const idx = Math.floor(phase);
      const frac = phase - idx;
      const curr = idx < mono.length ? mono[idx] : mono[mono.length - 1];
      const interp = prev + frac * (curr - prev);
      this._accumulator.push(interp);
      phase += ratio;

      // Update prev for next interpolation step
      if (Math.floor(phase) > idx) {
        prev = idx < mono.length ? mono[idx] : prev;
      }
    }

    this._prevSample = mono[mono.length - 1];
    this._phase = phase - mono.length;  // carry over fractional phase

    // Post 320-sample chunks (20 ms at 16kHz)
    while (this._accumulator.length >= 320) {
      const chunk = this._accumulator.splice(0, 320);
      const int16 = new Int16Array(320);
      for (let i = 0; i < 320; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        int16[i] = s < 0 ? s * 32768 : s * 32767;
      }
      this.port.postMessage(int16.buffer, [int16.buffer]);
    }

    return true;  // keep processor alive
  }
}

registerProcessor("gibberly-resampler", GibberlyResampler);
```

- [ ] **Step 2: Commit**

```bash
git add operator/worklet.js
git commit -m "feat: add AudioWorklet resampler for 16kHz PCM output"
```

---

## Task 5: operator/app.js — QR render + device enumeration + state machine

**Files:**
- Create: `operator/app.js`

This task builds the static/idle parts of the page. The WebSocket and audio pipeline come in Tasks 6–7.

- [ ] **Step 1: Create `operator/app.js`**

```js
(function () {
  // ── DOM refs ────────────────────────────────────────────────────────────────
  const statusDot      = document.getElementById('status-dot');
  const statusText     = document.getElementById('status-text');
  const statListeners  = document.getElementById('stat-listeners');
  const statElapsed    = document.getElementById('stat-elapsed');
  const listenerCount  = document.getElementById('listener-count');
  const elapsedEl      = document.getElementById('elapsed');
  const qrCanvas       = document.getElementById('qr-canvas');
  const liveUrlEl      = document.getElementById('live-url');
  const lastPhraseEl   = document.getElementById('last-phrase');
  const deviceSelect   = document.getElementById('device-select');
  const channelSelect  = document.getElementById('channel-select');
  const fileInput      = document.getElementById('file-input');
  const actionBtn      = document.getElementById('action-btn');

  // ── Config ──────────────────────────────────────────────────────────────────
  const backendWs  = window.GIBBERLY_BACKEND;                     // e.g. ws://host:8000
  const backendHttp = backendWs.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
  const liveUrl    = backendHttp + '/listen/live';

  // ── QR code (rendered once on load, never changes) ──────────────────────────
  (function renderQr() {
    const qr = qrcode(0, 'M');
    qr.addData(liveUrl);
    qr.make();
    qrCanvas.innerHTML = qr.createTableTag(4, 0);
    liveUrlEl.textContent = liveUrl;
    liveUrlEl.href = liveUrl;
  })();

  // ── State machine ──────────────────────────────────────────────────────────
  // States: idle | connecting | live | error
  let state = 'idle';

  function setState(s, msg) {
    state = s;
    statusDot.className = s === 'live' ? 'live' : s === 'connecting' ? 'connecting' : s === 'error' ? 'error' : '';
    statusText.textContent = msg || { idle: 'OFFLINE', connecting: 'CONNECTING…', live: 'LIVE', error: 'Error' }[s];
    actionBtn.disabled = s === 'connecting';
    actionBtn.textContent = s === 'live' ? '■ Stop' : s === 'error' ? '▶ Retry' : '▶ Start';
    actionBtn.className = s === 'live' ? 'stop' : '';
    statListeners.style.display = s === 'live' ? '' : 'none';
    statElapsed.style.display   = s === 'live' ? '' : 'none';
  }

  setState('idle');

  // ── Device enumeration ─────────────────────────────────────────────────────
  const FILE_OPTION_VALUE = '__file__';
  const STORAGE_DEVICE    = 'gibberly_device';
  const STORAGE_CHANNEL   = 'gibberly_channel';

  async function populateDevices() {
    // Request permission so device labels are populated
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
    } catch (_) { /* permission denied — labels will be generic */ }

    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs  = devices.filter(d => d.kind === 'audioinput');

    deviceSelect.innerHTML = '';
    inputs.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.deviceId;
      opt.textContent = d.label || `Microphone (${d.deviceId.slice(0, 8)})`;
      deviceSelect.appendChild(opt);
    });

    const fileOpt = document.createElement('option');
    fileOpt.value = FILE_OPTION_VALUE;
    fileOpt.textContent = 'Browse file…';
    deviceSelect.appendChild(fileOpt);

    // Restore saved device
    const saved = localStorage.getItem(STORAGE_DEVICE);
    if (saved && [...deviceSelect.options].some(o => o.value === saved)) {
      deviceSelect.value = saved;
    }

    updateChannelVisibility();
  }

  function updateChannelVisibility() {
    const isFile = deviceSelect.value === FILE_OPTION_VALUE;
    channelSelect.style.display = isFile ? 'none' : '';
    if (isFile) {
      // Trigger file picker when "Browse file…" is selected
      fileInput.click();
    } else {
      localStorage.setItem(STORAGE_DEVICE, deviceSelect.value);
    }
    const savedCh = localStorage.getItem(STORAGE_CHANNEL);
    if (savedCh) channelSelect.value = savedCh;
  }

  deviceSelect.addEventListener('change', updateChannelVisibility);
  channelSelect.addEventListener('change', () => {
    localStorage.setItem(STORAGE_CHANNEL, channelSelect.value);
  });
  fileInput.addEventListener('change', () => {
    if (!fileInput.files.length) {
      // User cancelled — revert to first real device
      deviceSelect.selectedIndex = 0;
      updateChannelVisibility();
    }
  });

  populateDevices();

  // ── Elapsed timer ──────────────────────────────────────────────────────────
  let elapsedTimer = null;
  let startTime    = 0;

  function startTimer() {
    startTime = Date.now();
    elapsedTimer = setInterval(() => {
      const s = Math.floor((Date.now() - startTime) / 1000);
      const m = Math.floor(s / 60);
      elapsedEl.textContent = `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
    }, 1000);
  }

  function stopTimer() {
    clearInterval(elapsedTimer);
    elapsedEl.textContent = '00:00';
  }

  // ── Status message handler (filled in Task 6) ─────────────────────────────
  function handleStatusMessage(msg) {
    if (msg.type === 'phrase') {
      lastPhraseEl.textContent = `"${msg.text}"`;
    } else if (msg.type === 'listeners') {
      listenerCount.textContent = msg.count;
    }
  }

  // ── Session management (filled in Tasks 6–7) ──────────────────────────────
  let stopSession = null;  // set when a session is active; call to stop it

  actionBtn.addEventListener('click', () => {
    if (state === 'live' && stopSession) {
      stopSession();
    } else if (state !== 'connecting') {
      startSession();
    }
  });

  function startSession() {
    setState('connecting');
    const isFile = deviceSelect.value === FILE_OPTION_VALUE;
    if (isFile) {
      startFileSession();
    } else {
      startDeviceSession();
    }
  }

  // Stubs — implemented in Tasks 6 and 7
  function startDeviceSession() { setState('error', 'Device session not yet implemented'); }
  function startFileSession()   { setState('error', 'File session not yet implemented'); }

  // Expose for Tasks 6–7
  window._gibberly = { setState, startTimer, stopTimer, handleStatusMessage, backendWs };
})();
```

- [ ] **Step 2: Verify the page in the browser**

Open `http://localhost:9000`. Expected:
- QR code renders showing the `/listen/live` URL
- Device dropdown populates (may prompt for mic permission)
- "Browse file…" appears at the bottom of the device list
- Start button is enabled; clicking it shows "File session not yet implemented" error

- [ ] **Step 3: Commit**

```bash
git add operator/app.js
git commit -m "feat: operator console — QR render, device enumeration, state machine"
```

---

## Task 6: operator/app.js — WebSocket + device audio pipeline

**Files:**
- Modify: `operator/app.js`

Replace the two stub functions `startDeviceSession` and `startFileSession` (and the `window._gibberly` export line) with the full implementation below.

- [ ] **Step 1: Replace stubs in `operator/app.js`**

Find and replace from `// Stubs — implemented in Tasks 6 and 7` to the end of the IIFE:

```js
  // ── Shared WebSocket session setup ─────────────────────────────────────────
  function openWebSocket(onOpen) {
    const ws = new WebSocket(backendWs + '/ws/stream');
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      // First message from server will be session_created
    };

    ws.onmessage = (evt) => {
      if (typeof evt.data === 'string') {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (msg.type === 'session_created') {
          setState('live');
          startTimer();
          lastPhraseEl.textContent = '';
          listenerCount.textContent = '0';
          onOpen(ws);
        } else {
          handleStatusMessage(msg);
        }
      }
    };

    ws.onerror = () => setState('error', 'Connection error');
    ws.onclose = () => {
      if (state === 'live' || state === 'connecting') setState('idle');
      stopTimer();
      stopSession = null;
    };

    return ws;
  }

  // ── Device audio pipeline ──────────────────────────────────────────────────
  async function startDeviceSession() {
    const deviceId   = deviceSelect.value;
    const channelMode = channelSelect.value || 'left';
    let audioCtx, workletNode, stream;

    const ws = openWebSocket(async (activeWs) => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: { exact: deviceId },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            sampleRate: { ideal: 48000 },
          }
        });

        audioCtx = new AudioContext();
        await audioCtx.audioWorklet.addModule('worklet.js');

        workletNode = new AudioWorkletNode(audioCtx, 'gibberly-resampler', {
          processorOptions: { channelMode },
        });

        workletNode.port.onmessage = (e) => {
          if (activeWs.readyState === WebSocket.OPEN) {
            activeWs.send(e.data);
          }
        };

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(workletNode);
        // Do NOT connect workletNode to destination — we don't want local playback

      } catch (err) {
        setState('error', err.message);
        activeWs.close();
      }
    });

    stopSession = () => {
      if (workletNode) workletNode.disconnect();
      if (stream) stream.getTracks().forEach(t => t.stop());
      if (audioCtx) audioCtx.close();
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }

  // ── File audio pipeline ────────────────────────────────────────────────────
  function startFileSession() {
    const file = fileInput.files[0];
    if (!file) { setState('idle'); return; }

    const ws = openWebSocket((activeWs) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        // Standard PCM WAV: skip 44-byte header, treat rest as 16kHz 16-bit mono Int16
        const buf    = e.target.result;
        const pcm    = new Int16Array(buf, 44);  // skip WAV header
        let offset   = 0;
        const CHUNK  = 320;  // 20 ms at 16kHz

        function sendNext() {
          if (offset >= pcm.length || activeWs.readyState !== WebSocket.OPEN) {
            if (activeWs.readyState === WebSocket.OPEN) activeWs.close();
            return;
          }
          const chunk = pcm.slice(offset, offset + CHUNK);
          activeWs.send(chunk.buffer);
          offset += CHUNK;
          setTimeout(sendNext, 20);
        }

        sendNext();
      };
      reader.readAsArrayBuffer(file);
    });

    stopSession = () => {
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }
```

- [ ] **Step 2: Manual verification — file mode (no secure context needed)**

With the backend running (`uvicorn backend.main:app --host 0.0.0.0 --port 8000`):

1. Open `http://localhost:9000`
2. Select "Browse file…" → choose `~/gibberly/test_audio.wav`
3. Click ▶ Start
4. Expected: status changes to CONNECTING… then LIVE, elapsed timer starts, QR visible
5. File streams in ~20ms chunks; session ends when file exhausted (WS closes → OFFLINE)

- [ ] **Step 3: Commit**

```bash
git add operator/app.js
git commit -m "feat: operator console — WebSocket session, device and file audio pipelines"
```

---

## Task 7: Smoke test the full stack

This task has no code changes. It verifies the complete flow before shipping.

- [ ] **Step 1: Start the backend**

```bash
cd ~/gibberly && source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: Verify `/listen/live` with no session**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/listen/live
```

Expected: `503`

- [ ] **Step 3: Open operator page and start a file session**

```bash
cd ~/gibberly/operator && python3 -m http.server 9000
```

Open `http://localhost:9000`, select "Browse file…", choose `test_audio.wav`, click Start.

- [ ] **Step 4: Verify `/listen/live` now redirects**

In a second terminal:
```bash
curl -s -o /dev/null -w "%{http_code}\n%{redirect_url}" http://localhost:8000/listen/live
```

Expected:
```
302
http://localhost:8000/listen/index.html?session=<uuid>
```

- [ ] **Step 5: Run full test suite**

```bash
cd ~/gibberly && source .venv/bin/activate
pytest -v
```

Expected: all 20+ tests pass.

- [ ] **Step 6: Commit smoke test confirmation (no code change — amend if needed)**

If any minor fixes were needed during smoke testing, commit them:
```bash
git add -p
git commit -m "fix: smoke test corrections"
```

---

## Self-Review Notes

- `/listen/live` route is defined before `app.mount("/listen", …)` — FastAPI routes win over static mounts when defined first. ✓
- File mode skips WAV header by offsetting `Int16Array` by 44 bytes — assumes standard PCM WAV. Wrong-format files produce garbled audio (same as Python CLI). ✓
- `workletNode` is not connected to `audioCtx.destination` — no local echo. ✓
- `getUserMedia` secure context requirement: file mode works on `http://localhost`, device mode requires `https://` or `localhost`. ✓
- `current_session_id` cleared only if it matches the closing session's ID — safe if two sessions somehow overlap. ✓
- QR rendered on page load from `config.js` — no session needed. ✓
