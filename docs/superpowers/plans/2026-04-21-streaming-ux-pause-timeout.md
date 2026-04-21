# Streaming UX, Pause, Session Timeout & Config.js Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add word-by-word sliding window to the listener, a pause button to the operator, a 60-minute session timeout, and restore config.js to a manually-editable file.

**Architecture:** Backend gains `pause()`/`resume()` on `SessionHandler` (with STT stop/restart), a `broadcast_event()` on `PubSubPublisher`, and an `asyncio.timeout` around the WS receive loop. Operator frontend sends JSON control frames over the existing WebSocket and tracks a keepalive during pause. Listener frontend splits phrases into a word queue, trickles at an adaptive rate (estimated from a 1-minute rolling window × a user-controlled multiplier), and shows a paused pill when the session is paused.

**Tech Stack:** Python 3.13, FastAPI/Starlette, asyncio, pytest + unittest.mock; Vanilla JS, Web Audio API.

---

## File Map

| File | Change |
|------|--------|
| `backend/config.py` | Add `session_timeout_s: int` field and env var |
| `backend/stt.py` | Add `pause_recognition()`, `resume_recognition()` |
| `backend/pubsub.py` | Add `broadcast_event()` |
| `backend/session.py` | Add `paused` flag, `pause()`, `resume()`, guard in `_process_chunk()` |
| `backend/main.py` | Replace `receive_bytes()` with `receive()`, asyncio timeout, pause/resume dispatch |
| `operator/config.js` | Restore to static manually-editable file |
| `operator/serve.py` | Remove config.js auto-generation |
| `operator/index.html` | Add pause/resume button + CSS |
| `operator/app.js` | Pause/resume logic, keepalive timer, module-scope `activeWs` |
| `listener/index.html` | Replace `#last-phrase` with reading pane, add speed slider + paused pill |
| `listener/app.js` | Word queue, sliding window, adaptive speed, paused/resumed handling |
| `tests/backend/test_config.py` | Add `session_timeout_s` tests |
| `tests/backend/test_stt.py` | Add `pause_recognition`/`resume_recognition` tests |
| `tests/backend/test_pubsub.py` | Add `broadcast_event` test |
| `tests/backend/test_session.py` | Add pause/resume/guard tests |

---

## Task 1: Add `session_timeout_s` to config

**Files:**
- Modify: `backend/config.py`
- Modify: `tests/backend/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/backend/test_config.py`:

```python
def test_config_session_timeout_defaults_to_3600():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.session_timeout_s == 3600


def test_config_session_timeout_overridable():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "SESSION_TIMEOUT_S": "1800",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.session_timeout_s == 1800
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd ~/gibberly && source .venv/bin/activate
pytest tests/backend/test_config.py::test_config_session_timeout_defaults_to_3600 tests/backend/test_config.py::test_config_session_timeout_overridable -v
```

Expected: FAIL — `Settings has no field 'session_timeout_s'`

- [ ] **Step 3: Add the field to `backend/config.py`**

In the `Settings` dataclass, add after `llm_context_window`:

```python
    session_timeout_s: int
```

In `_load()`, add after the `llm_context_window=...` line:

```python
        session_timeout_s=int(os.environ.get("SESSION_TIMEOUT_S", "3600")),
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/backend/test_config.py -v
```

Expected: all config tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config.py tests/backend/test_config.py
git commit -m "feat: add SESSION_TIMEOUT_S config setting"
```

---

## Task 2: Add `pause_recognition` / `resume_recognition` to STTSession

**Files:**
- Modify: `backend/stt.py`
- Modify: `tests/backend/test_stt.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_stt.py`:

```python
@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_pause_recognition_stops_recognizer_without_closing_stream(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.pause_recognition()

    mock_recognizer.stop_continuous_recognition_async.assert_called_once()
    mock_recognizer.stop_continuous_recognition_async.return_value.get.assert_called_once()
    mock_stream.close.assert_not_called()


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_resume_recognition_starts_recognizer(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.resume_recognition()

    mock_recognizer.start_continuous_recognition.assert_called_once()
    mock_stream.close.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/backend/test_stt.py::test_pause_recognition_stops_recognizer_without_closing_stream tests/backend/test_stt.py::test_resume_recognition_starts_recognizer -v
```

Expected: FAIL — `STTSession has no attribute 'pause_recognition'`

- [ ] **Step 3: Add the methods to `backend/stt.py`**

Add after the `stop()` method (before the last line of the class):

```python
    def pause_recognition(self) -> None:
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            self._interim_text = ""
            self._total_dispatched = ""
        try:
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            pass

    def resume_recognition(self) -> None:
        with self._lock:
            self._interim_text = ""
            self._total_dispatched = ""
        self._recognizer.start_continuous_recognition()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/backend/test_stt.py -v
```

Expected: all STT tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stt.py tests/backend/test_stt.py
git commit -m "feat: add pause_recognition/resume_recognition to STTSession"
```

---

## Task 3: Add `broadcast_event` to PubSubPublisher

**Files:**
- Modify: `backend/pubsub.py`
- Modify: `tests/backend/test_pubsub.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/test_pubsub.py`:

```python
@patch("backend.pubsub.WebPubSubServiceClient")
def test_broadcast_event_sends_to_all_lang_groups(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    from backend.languages import SUPPORTED_LANGUAGES
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.broadcast_event("sess1", {"type": "paused"})

    assert mock_client.send_to_group.call_count == len(SUPPORTED_LANGUAGES)
    called_groups = {c[0][0] for c in mock_client.send_to_group.call_args_list}
    for lang in SUPPORTED_LANGUAGES:
        assert f"session-sess1-{lang['code']}" in called_groups

    # Verify payload is JSON with correct type
    first_call = mock_client.send_to_group.call_args_list[0]
    payload = json.loads(first_call[0][1])
    assert payload == {"type": "paused"}
    assert first_call[1]["content_type"] == "application/json"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/backend/test_pubsub.py::test_broadcast_event_sends_to_all_lang_groups -v
```

Expected: FAIL — `PubSubPublisher has no attribute 'broadcast_event'`

- [ ] **Step 3: Add `broadcast_event` to `backend/pubsub.py`**

Add after the `send_close` method:

```python
    def broadcast_event(self, session_id: str, event: dict) -> None:
        payload = json.dumps(event)
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, payload, content_type="application/json")
            except Exception as exc:
                log.warning("broadcast_event to %s failed: %s", group, exc)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/backend/test_pubsub.py -v
```

Expected: all pubsub tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pubsub.py tests/backend/test_pubsub.py
git commit -m "feat: add broadcast_event to PubSubPublisher"
```

---

## Task 4: Add pause/resume to SessionHandler

**Files:**
- Modify: `backend/session.py`
- Modify: `tests/backend/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_session.py`:

```python
@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_pause_sets_paused_flag_and_broadcasts(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler.pause())

    assert handler.paused is True
    mock_stt.pause_recognition.assert_called_once()
    mock_pub.broadcast_event.assert_called_once_with(handler.session_id, {"type": "paused"})
    assert any(m.get("type") == "paused" for m in statuses)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_resume_clears_paused_flag_and_broadcasts(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    handler.paused = True
    loop.run_until_complete(handler.resume())

    assert handler.paused is False
    mock_stt.resume_recognition.assert_called_once()
    mock_pub.broadcast_event.assert_called_once_with(handler.session_id, {"type": "resumed"})
    assert any(m.get("type") == "resumed" for m in statuses)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_dropped_when_paused(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.paused = True
    loop.run_until_complete(handler._process_chunk("Gut"))

    mock_llm.translate.assert_not_called()
    mock_pub.publish_phrase.assert_not_called()
    loop.close()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/backend/test_session.py::test_pause_sets_paused_flag_and_broadcasts tests/backend/test_session.py::test_resume_clears_paused_flag_and_broadcasts tests/backend/test_session.py::test_process_chunk_dropped_when_paused -v
```

Expected: FAIL — `SessionHandler has no attribute 'paused'`

- [ ] **Step 3: Add `paused` flag to `SessionHandler.__init__`**

In `backend/session.py`, inside `__init__` after `self.audio_active_count: dict[str, int] = {}`, add:

```python
        self.paused: bool = False
```

- [ ] **Step 4: Add `pause()` and `resume()` methods**

Add after `_send_status()` (before `listener_join`):

```python
    async def pause(self) -> None:
        self.paused = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stt.pause_recognition)
        await loop.run_in_executor(
            None, lambda: self._publisher.broadcast_event(self.session_id, {"type": "paused"})
        )
        await self._send_status({"type": "paused"})

    async def resume(self) -> None:
        self.paused = False
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stt.resume_recognition)
        await loop.run_in_executor(
            None, lambda: self._publisher.broadcast_event(self.session_id, {"type": "resumed"})
        )
        await self._send_status({"type": "resumed"})
```

- [ ] **Step 5: Add guard at top of `_process_chunk`**

Replace the first line of `_process_chunk`:

```python
    async def _process_chunk(self, raw_src: str) -> None:
        try:
```

with:

```python
    async def _process_chunk(self, raw_src: str) -> None:
        if self.paused:
            return
        try:
```

- [ ] **Step 6: Run all session tests**

```bash
pytest tests/backend/test_session.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/session.py tests/backend/test_session.py
git commit -m "feat: add pause/resume to SessionHandler"
```

---

## Task 5: Update WS receive loop in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add `import json` to `backend/main.py`**

Add `import json` after `import asyncio` at the top of the file (line 2):

```python
import asyncio
import json
import logging
```

- [ ] **Step 2: Replace the receive loop**

In the `stream()` WebSocket handler, replace the entire `try/except/finally` block:

```python
    try:
        while True:
            data = await websocket.receive_bytes()
            handler.write(data)
    except WebSocketDisconnect:
        log.info("Session %s — operator disconnected", handler.session_id)
    except Exception as exc:
        log.error("Session %s — unexpected error: %s", handler.session_id, exc)
    finally:
        app.state.sessions.pop(handler.session_id, None)
        if app.state.current_session_id == handler.session_id:
            app.state.current_session_id = None
        if app.state.active_ws is websocket:
            app.state.active_ws = None
        log.info("Session %s stopping…", handler.session_id)
        try:
            await loop.run_in_executor(None, handler.stop)
            log.info("Session %s stopped", handler.session_id)
        except Exception as exc:
            log.error("Session %s stop error: %s", handler.session_id, exc)
```

with:

```python
    try:
        async with asyncio.timeout(settings.session_timeout_s):
            while True:
                data = await websocket.receive()
                raw_bytes = data.get("bytes")
                raw_text = data.get("text")
                if raw_bytes:
                    if not handler.paused:
                        handler.write(raw_bytes)
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
    except asyncio.TimeoutError:
        log.warning(
            "Session %s timed out after %ds",
            handler.session_id, settings.session_timeout_s,
        )
        try:
            await websocket.close(code=1001)
        except Exception:
            pass
    except WebSocketDisconnect:
        log.info("Session %s — operator disconnected", handler.session_id)
    except Exception as exc:
        log.error("Session %s — unexpected error: %s", handler.session_id, exc)
    finally:
        app.state.sessions.pop(handler.session_id, None)
        if app.state.current_session_id == handler.session_id:
            app.state.current_session_id = None
        if app.state.active_ws is websocket:
            app.state.active_ws = None
        log.info("Session %s stopping…", handler.session_id)
        try:
            await loop.run_in_executor(None, handler.stop)
            log.info("Session %s stopped", handler.session_id)
        except Exception as exc:
            log.error("Session %s stop error: %s", handler.session_id, exc)
```

- [ ] **Step 3: Run existing main tests to confirm nothing broke**

```bash
pytest tests/backend/test_main.py -v
```

Expected: all PASS

- [ ] **Step 4: Run the full test suite**

```bash
pytest -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: pause/resume dispatch and 60-minute session timeout in WS loop"
```

---

## Task 6: Restore config.js and clean up serve.py

**Files:**
- Modify: `operator/config.js`
- Modify: `operator/serve.py`

- [ ] **Step 1: Restore `operator/config.js` to a static file**

Replace the entire contents of `operator/config.js` with:

```js
// Edit GIBBERLY_BACKEND to point at your backend WebSocket URL.
// Use ws:// for local development, wss:// for production (Azure App Service etc).
window.GIBBERLY_BACKEND = "ws://localhost:8000";
```

- [ ] **Step 2: Remove config.js auto-generation from `operator/serve.py`**

Replace the entire contents of `operator/serve.py` with:

```python
#!/usr/bin/env python3
"""
Operator console dev server.

Serves the operator/ directory over HTTP on OPERATOR_PORT (default 9000).
Edit operator/config.js to set GIBBERLY_BACKEND before starting.

Usage:
  cd ~/gibberly
  python3 operator/serve.py
"""
import http.server
import os
import pathlib

env_file = pathlib.Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

port = int(os.environ.get("OPERATOR_PORT", "9000"))

os.chdir(pathlib.Path(__file__).parent)
print(f"Serving operator console at http://localhost:{port}")
print("Edit operator/config.js to change GIBBERLY_BACKEND.")
http.server.test(
    HandlerClass=http.server.SimpleHTTPRequestHandler,
    port=port,
    bind="localhost",
)
```

- [ ] **Step 3: Commit**

```bash
git add operator/config.js operator/serve.py
git commit -m "feat: restore config.js to static file, remove serve.py auto-generation"
```

---

## Task 7: Operator pause/resume button

**Files:**
- Modify: `operator/index.html`
- Modify: `operator/app.js`

- [ ] **Step 1: Add CSS and button to `operator/index.html`**

In the `<style>` block, after the `#action-btn.stop:hover` rule, add:

```css
    #pause-btn {
      flex: none;
      padding: 0.6rem 1.5rem;
      background: #374151; color: #f0f0f0;
      border: none; border-radius: 0.5rem;
      font-size: 0.95rem; cursor: pointer;
      transition: background 0.15s;
      display: none;
    }
    #pause-btn:hover:not(:disabled) { background: #4b5563; }
    #pause-btn:disabled { background: #1f2937; color: #4b5563; cursor: default; }
    #pause-btn.active { background: #065f46; color: #d1fae5; }
```

In the `#controls` div, after `<button id="action-btn">▶ Start</button>`, add:

```html
    <button id="pause-btn" disabled>⏸ Pause</button>
```

- [ ] **Step 2: Rewrite `operator/app.js`**

Replace the entire contents of `operator/app.js` with the following. The changes vs the original are: `activeWs` and `paused` at module scope; `pauseBtn` DOM ref; `setState` updated; `startKeepalive`/`stopKeepalive`; `pauseBtn` click handler; worklet `onmessage` checks `paused`; file `sendNext` checks `paused` with `resumeCapture`; `openWebSocket` sets `activeWs`.

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
  const pauseBtn       = document.getElementById('pause-btn');
  const debugLinkEl    = document.getElementById('debug-link');
  const sourceLangSelect = document.getElementById('source-lang-select');

  // ── Config ──────────────────────────────────────────────────────────────────
  const backendWs  = window.GIBBERLY_BACKEND;
  const backendHttp = backendWs.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
  const liveUrl    = backendHttp + '/listen/live';

  // ── QR code ─────────────────────────────────────────────────────────────────
  (function renderQr() {
    const qr = qrcode(0, 'M');
    qr.addData(liveUrl);
    qr.make();
    qrCanvas.innerHTML = qr.createTableTag(4, 0);
    liveUrlEl.textContent = liveUrl;
    liveUrlEl.href = liveUrl;
  })();

  // ── State machine ──────────────────────────────────────────────────────────
  let state = 'idle';

  function setState(s, msg) {
    state = s;
    statusDot.className = s === 'live' ? 'live' : s === 'connecting' ? 'connecting' : s === 'error' ? 'error' : '';
    statusText.textContent = msg || { idle: 'OFFLINE', connecting: 'CONNECTING…', live: 'LIVE', error: 'ERROR' }[s];
    actionBtn.disabled = s === 'connecting';
    actionBtn.textContent = s === 'live' ? '■ Stop' : s === 'error' ? '▶ Retry' : '▶ Start';
    actionBtn.className = s === 'live' ? 'stop' : '';
    statListeners.style.display = s === 'live' ? '' : 'none';
    statElapsed.style.display   = s === 'live' ? '' : 'none';
    if (sourceLangSelect) sourceLangSelect.disabled = (s === 'live' || s === 'connecting');
    pauseBtn.style.display = s === 'live' ? '' : 'none';
    if (s !== 'live') {
      paused = false;
      pauseBtn.textContent = '⏸ Pause';
      pauseBtn.className = '';
      pauseBtn.disabled = true;
    }
  }

  setState('idle');

  // ── Device enumeration ─────────────────────────────────────────────────────
  const FILE_OPTION_VALUE = '__file__';
  const STORAGE_DEVICE    = 'gibberly_device';
  const STORAGE_CHANNEL   = 'gibberly_channel';

  async function populateDevices() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
    } catch (_) {}

    let devices;
    try {
      devices = await navigator.mediaDevices.enumerateDevices();
    } catch (err) {
      deviceSelect.innerHTML = '<option value="">No audio devices found</option>';
      const fileOpt = document.createElement('option');
      fileOpt.value = '__file__';
      fileOpt.textContent = 'Browse file…';
      deviceSelect.appendChild(fileOpt);
      updateChannelVisibility(false);
      return;
    }
    const inputs = devices.filter(d => d.kind === 'audioinput');

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

    const saved = localStorage.getItem(STORAGE_DEVICE);
    if (saved && [...deviceSelect.options].some(o => o.value === saved)) {
      deviceSelect.value = saved;
    }

    updateChannelVisibility(false);
  }

  function updateChannelVisibility(fromUserAction = true) {
    const isFile = deviceSelect.value === FILE_OPTION_VALUE;
    channelSelect.style.display = isFile ? 'none' : '';
    if (isFile) {
      if (fromUserAction) fileInput.click();
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
      deviceSelect.selectedIndex = 0;
      updateChannelVisibility();
    }
  });

  populateDevices();

  // ── Debug link ─────────────────────────────────────────────────────────────
  (async function initDebugLink() {
    try {
      const res = await fetch(backendHttp + '/current-session');
      if (res.ok) {
        const { session_id } = await res.json();
        debugLinkEl.href = `${backendHttp}/listen/debug.html?session=${session_id}`;
      }
    } catch (_) {}
  })();

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
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = null;
    elapsedEl.textContent = '00:00';
  }

  // ── Pause / keepalive ──────────────────────────────────────────────────────
  let paused          = false;
  let activeWs        = null;
  let resumeCapture   = null;
  let keepaliveTimer  = null;

  function startKeepalive() {
    keepaliveTimer = setInterval(() => {
      if (activeWs && activeWs.readyState === WebSocket.OPEN) {
        activeWs.send(JSON.stringify({ type: 'keepalive' }));
      }
    }, 30000);
  }

  function stopKeepalive() {
    if (keepaliveTimer) clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }

  pauseBtn.addEventListener('click', () => {
    if (!activeWs || activeWs.readyState !== WebSocket.OPEN) return;
    if (!paused) {
      paused = true;
      pauseBtn.textContent = '▶ Resume';
      pauseBtn.className = 'active';
      activeWs.send(JSON.stringify({ type: 'pause' }));
      startKeepalive();
    } else {
      paused = false;
      pauseBtn.textContent = '⏸ Pause';
      pauseBtn.className = '';
      stopKeepalive();
      activeWs.send(JSON.stringify({ type: 'resume' }));
      if (resumeCapture) resumeCapture();
    }
  });

  // ── Status message handler ─────────────────────────────────────────────────
  function handleStatusMessage(msg) {
    console.log('[gibberly] msg:', msg.type, msg);
    if (msg.type === 'phrase') {
      const en = msg.en_text || msg.text || '';
      const parts = [];
      if (msg.raw_src || msg.raw_de) parts.push(`raw: ${msg.raw_src || msg.raw_de}`);
      if (msg.clean_src || msg.clean_de) parts.push(`clean: ${msg.clean_src || msg.clean_de}`);
      parts.push(`en: ${en}`);
      lastPhraseEl.innerHTML = parts.map(p => `<div>${p}</div>`).join('');
    } else if (msg.type === 'llm_fallback') {
      console.warn(`[gibberly] LLM fallback — chunk: ${msg.chunk}`);
    } else if (msg.type === 'tts_error') {
      console.error(`[gibberly] TTS failed — ${msg.error}`);
    } else if (msg.type === 'pubsub_error') {
      console.error(`[gibberly] PubSub publish failed — ${msg.error}`);
    } else if (msg.type === 'listeners') {
      listenerCount.textContent = msg.count;
    } else if (msg.type === 'debug_audio_start') {
      console.log('[gibberly] synthesis started — first audio chunk, bytes:', msg.size);
    }
  }

  // ── Session management ─────────────────────────────────────────────────────
  let stopSession = null;

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

  // ── Shared WebSocket session setup ─────────────────────────────────────────
  function openWebSocket(onOpen) {
    const sourceLang = sourceLangSelect ? sourceLangSelect.value : 'de-DE';
    const ws = new WebSocket(`${backendWs}/ws/stream?source_lang=${sourceLang}`);
    ws.binaryType = 'arraybuffer';
    activeWs = ws;

    ws.onmessage = (evt) => {
      if (typeof evt.data === 'string') {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (msg.type === 'session_created') {
          setState('live');
          pauseBtn.disabled = false;
          startTimer();
          lastPhraseEl.textContent = '';
          listenerCount.textContent = '0';
          debugLinkEl.href = `${backendHttp}/listen/debug.html?session=${msg.session_id}`;
          onOpen(ws);
        } else {
          handleStatusMessage(msg);
        }
      }
    };

    ws.onerror = () => {
      setState('error', 'Connection error');
    };

    ws.onclose = () => {
      activeWs = null;
      stopKeepalive();
      paused = false;
      resumeCapture = null;
      if (state === 'live' || state === 'connecting') setState('idle');
      stopTimer();
      stopSession = null;
    };

    return ws;
  }

  // ── Device audio pipeline ──────────────────────────────────────────────────
  async function startDeviceSession() {
    const deviceId    = deviceSelect.value;
    const channelMode = channelSelect.value || 'left';
    let audioCtx, workletNode, stream;
    resumeCapture = null;

    const ws = openWebSocket(async (activeWsRef) => {
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
          if (activeWsRef.readyState === WebSocket.OPEN && !paused) {
            activeWsRef.send(e.data);
          }
        };

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(workletNode);

      } catch (err) {
        setState('error', err.message);
        stopSession = null;
        activeWsRef.close();
      }
    });

    stopSession = () => {
      stopKeepalive();
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

    let driveTimer = null;

    const ws = openWebSocket((activeWsRef) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const buf  = e.target.result;
        const pcm  = new Int16Array(buf, 44);
        let offset = 0;
        const CHUNK = 320;

        function sendNext() {
          if (offset >= pcm.length || activeWsRef.readyState !== WebSocket.OPEN) {
            if (activeWsRef.readyState === WebSocket.OPEN) activeWsRef.close();
            driveTimer = null;
            return;
          }
          if (paused) {
            driveTimer = null;
            return;
          }
          const chunk = pcm.slice(offset, offset + CHUNK);
          activeWsRef.send(chunk.buffer);
          offset += CHUNK;
          driveTimer = setTimeout(sendNext, 20);
        }

        resumeCapture = () => { if (driveTimer === null) sendNext(); };
        sendNext();
      };
      reader.readAsArrayBuffer(file);
    });

    stopSession = () => {
      stopKeepalive();
      clearTimeout(driveTimer);
      resumeCapture = null;
      ws.close();
      setState('idle');
      stopTimer();
      stopSession = null;
    };
  }
})();
```

- [ ] **Step 3: Commit**

```bash
git add operator/index.html operator/app.js
git commit -m "feat: pause/resume button on operator console"
```

---

## Task 8: Listener word-by-word sliding window

**Files:**
- Modify: `listener/index.html`
- Modify: `listener/app.js`

- [ ] **Step 1: Update `listener/index.html`**

Replace the entire file with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gibberly — Live Translation</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f0f0f; color: #f0f0f0;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      min-height: 100vh; padding: 2rem;
      gap: 1rem;
    }
    h1 { font-size: 1.4rem; }
    #status { font-size: 0.9rem; color: #888; }
    #lang-row {
      display: flex; align-items: center; gap: 0.75rem;
    }
    #lang-select {
      background: #1e1e1e; color: #f0f0f0;
      border: 1px solid #444; border-radius: 0.5rem;
      padding: 0.5rem 0.75rem; font-size: 0.9rem; cursor: pointer;
    }
    #lang-select:disabled { opacity: 0.5; cursor: default; }
    #connect-btn {
      padding: 1rem 2.5rem; font-size: 1.1rem;
      background: #2563eb; color: #fff;
      border: none; border-radius: 2rem; cursor: pointer;
    }
    #connect-btn:disabled { background: #444; cursor: default; }
    #connect-btn.stop { background: #dc2626; }
    #audio-btn {
      padding: 0.6rem 1.5rem; font-size: 0.9rem;
      background: #1e1e1e; color: #f0f0f0;
      border: 1px solid #444; border-radius: 1.5rem; cursor: pointer;
      display: none;
    }
    #audio-btn.active { background: #065f46; border-color: #059669; color: #d1fae5; }
    #reading-pane-wrapper {
      width: 100%; max-width: 480px;
      display: flex; flex-direction: column;
      align-items: center; gap: 0.4rem;
      min-height: 4rem;
    }
    #paused-pill {
      display: none;
      background: #374151; color: #9ca3af;
      border-radius: 1rem; padding: 0.2rem 0.75rem;
      font-size: 0.8rem;
    }
    #reading-pane {
      font-size: 1.15rem; color: #f0f0f0;
      line-height: 1.7; text-align: center;
      min-height: 2.5rem; word-break: break-word;
    }
    #speed-row {
      display: none;
      width: 100%; max-width: 480px;
      text-align: center;
    }
    #speed-row label { font-size: 0.8rem; color: #6b7280; }
    #speed-slider { width: 60%; margin-top: 0.25rem; cursor: pointer; }
    #debug { font-size: 0.75rem; color: #555; text-align: center; font-family: monospace; }
    #mute-warning {
      display: none;
      background: #78350f; color: #fef3c7;
      border: 1px solid #b45309; border-radius: 0.75rem;
      padding: 0.9rem 1.2rem; font-size: 0.9rem; text-align: center;
      max-width: 320px;
    }
    #transcript-section {
      width: 100%; max-width: 480px;
      background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 0.75rem;
      padding: 0.75rem 1rem;
    }
    #transcript-section summary {
      cursor: pointer; color: #6b7280; font-size: 0.85rem;
      user-select: none; list-style: none; display: flex;
      justify-content: space-between; align-items: center;
    }
    #transcript-section summary::-webkit-details-marker { display: none; }
    #transcript-list {
      margin-top: 0.75rem; max-height: 40vh; overflow-y: auto;
      display: flex; flex-direction: column; gap: 0.4rem;
    }
    .transcript-phrase {
      font-size: 0.9rem; color: #e2e8f0; line-height: 1.4;
      padding: 0.3rem 0; border-bottom: 1px solid #2a2a2a;
    }
    .transcript-phrase:last-child { border-bottom: none; }
    #dl-transcript {
      margin-top: 0.75rem; padding: 0.4rem 1rem;
      background: #065f46; color: #d1fae5;
      border: none; border-radius: 0.4rem; cursor: pointer;
      font-size: 0.8rem; font-family: inherit;
    }
    #dl-transcript:disabled { opacity: 0.4; cursor: default; }
  </style>
</head>
<body>
  <h1>Live Translation</h1>
  <p id="status">Choose language and connect</p>

  <div id="lang-row">
    <select id="lang-select"><option value="">Loading…</option></select>
  </div>

  <button id="connect-btn">Connect</button>
  <button id="audio-btn">&#x1F50A; Unmute audio</button>

  <div id="reading-pane-wrapper">
    <div id="paused-pill">⏸ Paused</div>
    <p id="reading-pane"></p>
  </div>

  <div id="speed-row">
    <label for="speed-slider">Speed: <span id="speed-label">1.0×</span></label><br>
    <input type="range" id="speed-slider" min="0.5" max="1.5" step="0.25" value="1.0">
  </div>

  <div id="mute-warning">
    &#x1F514; <strong>No sound?</strong> Check the silent switch on the left side of your iPhone — if it shows orange, flip it up.
  </div>
  <p id="debug"></p>

  <details id="transcript-section">
    <summary>
      <span>Transcript (<span id="transcript-count">0</span> phrases)</span>
      <span style="font-size:0.75rem; color:#4b5563;">tap to expand</span>
    </summary>
    <div id="transcript-list"></div>
    <button id="dl-transcript" disabled>Download Transcript</button>
  </details>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Rewrite `listener/app.js`**

Replace the entire contents of `listener/app.js` with:

```js
(function () {
  const connectBtn      = document.getElementById('connect-btn');
  const audioBtn        = document.getElementById('audio-btn');
  const statusEl        = document.getElementById('status');
  const readingPaneEl   = document.getElementById('reading-pane');
  const pausedPill      = document.getElementById('paused-pill');
  const speedRow        = document.getElementById('speed-row');
  const speedSlider     = document.getElementById('speed-slider');
  const speedLabel      = document.getElementById('speed-label');
  const debugEl         = document.getElementById('debug');
  const muteWarningEl   = document.getElementById('mute-warning');
  const langSelect      = document.getElementById('lang-select');
  const transcriptList  = document.getElementById('transcript-list');
  const transcriptCount = document.getElementById('transcript-count');
  const dlTranscriptBtn = document.getElementById('dl-transcript');

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

  const params  = new URLSearchParams(window.location.search);
  const session = params.get('session');
  if (!session) {
    statusEl.textContent = 'No session ID in URL.';
    connectBtn.disabled = true;
    return;
  }

  // ── Transcript ─────────────────────────────────────────────────────────────
  const phrases = [];

  function addPhrase(text) {
    phrases.push(text);
    transcriptCount.textContent = phrases.length;
    const div = document.createElement('div');
    div.className = 'transcript-phrase';
    div.textContent = text;
    transcriptList.appendChild(div);
    dlTranscriptBtn.disabled = false;
  }

  dlTranscriptBtn.addEventListener('click', () => {
    if (!phrases.length) return;
    const blob = new Blob([phrases.join('\n')], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), {
      href: url, download: `gibberly-transcript-${session}-${Date.now()}.txt`
    }).click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });

  // ── Word queue / sliding window ────────────────────────────────────────────
  const MAX_DISPLAY_WORDS = 30;
  const DEFAULT_BASE_MS   = 400;   // fallback: 150 wpm
  const SPEED_KEY         = 'gibberly_word_speed_multiplier';

  let displayWords  = [];
  let wordQueue     = [];
  let tickTimer     = null;
  const phraseHistory = [];   // [{ts: ms, count: n}]

  function estimateBaseMsPerWord() {
    const now    = Date.now();
    const cutoff = now - 60000;
    while (phraseHistory.length && phraseHistory[0].ts < cutoff) phraseHistory.shift();
    if (phraseHistory.length < 2) return DEFAULT_BASE_MS;
    const totalWords = phraseHistory.reduce((s, e) => s + e.count, 0);
    const windowMs   = phraseHistory[phraseHistory.length - 1].ts - phraseHistory[0].ts;
    if (windowMs < 1000) return DEFAULT_BASE_MS;
    return windowMs / totalWords;
  }

  function getTrickleInterval() {
    const multiplier = parseFloat(speedSlider.value);
    return estimateBaseMsPerWord() / multiplier;
  }

  function startTick() {
    if (tickTimer !== null) return;
    function tick() {
      if (wordQueue.length > 0) {
        const word = wordQueue.shift();
        displayWords.push(word);
        if (displayWords.length > MAX_DISPLAY_WORDS) displayWords.shift();
        readingPaneEl.textContent = displayWords.join(' ');
      }
      if (wordQueue.length > 0) {
        tickTimer = setTimeout(tick, getTrickleInterval());
      } else {
        tickTimer = null;
      }
    }
    tickTimer = setTimeout(tick, getTrickleInterval());
  }

  function onPhrase(text) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (!words.length) return;
    phraseHistory.push({ ts: Date.now(), count: words.length });
    wordQueue.push(...words);
    addPhrase(text);
    startTick();
  }

  function clearReadingPane() {
    wordQueue    = [];
    displayWords = [];
    if (tickTimer !== null) { clearTimeout(tickTimer); tickTimer = null; }
    readingPaneEl.textContent = '';
  }

  // ── Speed slider ───────────────────────────────────────────────────────────
  const savedSpeed = parseFloat(localStorage.getItem(SPEED_KEY) || '1');
  speedSlider.value = savedSpeed;
  speedLabel.textContent = savedSpeed % 1 === 0 ? savedSpeed + '×' : savedSpeed + '×';

  speedSlider.addEventListener('input', () => {
    const v = parseFloat(speedSlider.value);
    speedLabel.textContent = v + '×';
    localStorage.setItem(SPEED_KEY, v);
  });

  // ── Language selector ──────────────────────────────────────────────────────
  let chosenLang = 'en';

  async function loadLanguages() {
    try {
      const [langsRes, infoRes] = await Promise.all([
        fetch('/languages'),
        fetch(`/session/${session}/info`),
      ]);
      const langs = langsRes.ok ? await langsRes.json() : [];
      const sourceLang = infoRes.ok ? (await infoRes.json()).source_lang : null;
      const sourceCode = sourceLang ? sourceLang.split('-')[0] : null;

      const filtered = sourceCode ? langs.filter(l => l.code !== sourceCode) : langs;

      langSelect.innerHTML = '';
      filtered.forEach(l => {
        const opt = document.createElement('option');
        opt.value = l.code;
        opt.textContent = l.name;
        langSelect.appendChild(opt);
      });

      const enOpt = filtered.find(l => l.code === 'en');
      chosenLang = enOpt ? 'en' : (filtered[0]?.code || 'en');
      langSelect.value = chosenLang;
    } catch (e) {
      langSelect.innerHTML = '<option value="en">English</option>';
    }
  }

  langSelect.addEventListener('change', () => { chosenLang = langSelect.value; });
  loadLanguages();

  // ── Connection state ───────────────────────────────────────────────────────
  function dbg(msg) { if (debugEl) debugEl.textContent = msg; }

  let audioCtx     = null;
  let nextPlayTime = 0;
  let ws           = null;
  let connected    = false;
  let audioActive  = false;

  function setStatus(msg) { statusEl.textContent = msg; }

  function setConnected(state) {
    connected              = state;
    connectBtn.textContent = state ? 'Disconnect' : 'Connect';
    connectBtn.className   = state ? 'stop' : '';
    connectBtn.disabled    = false;
    langSelect.disabled    = state;
    audioBtn.style.display = state ? 'block' : 'none';
    speedRow.style.display = state ? '' : 'none';
    if (!state) {
      audioBtn.textContent = '\uD83D\uDD0A Unmute audio';
      audioBtn.className = '';
      pausedPill.style.display = 'none';
      clearReadingPane();
    }
  }

  // ── Audio playback ─────────────────────────────────────────────────────────
  async function playAudio(arrayBuffer) {
    if (!audioCtx) return;
    let audioBuffer;
    try {
      audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    } catch (e) {
      dbg('decode error: ' + e.message);
      return;
    }
    const src    = audioCtx.createBufferSource();
    src.buffer   = audioBuffer;
    src.connect(audioCtx.destination);
    const now     = audioCtx.currentTime;
    const startAt = Math.max(now, nextPlayTime);
    src.start(startAt);
    nextPlayTime = startAt + audioBuffer.duration;
  }

  function base64ToArrayBuffer(b64) {
    const bin  = atob(b64);
    const buf  = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  // ── Audio mute/unmute ──────────────────────────────────────────────────────
  audioBtn.addEventListener('click', async () => {
    if (!audioActive) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      nextPlayTime = 0;
      fetch(`/session/${session}/audio/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = true;
      audioBtn.textContent = '\uD83D\uDD07 Mute audio';
      audioBtn.className = 'active';
      if (isIOS && muteWarningEl) muteWarningEl.style.display = 'block';
    } else {
      if (audioCtx) { audioCtx.suspend(); }
      fetch(`/session/${session}/audio/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = false;
      audioBtn.textContent = '\uD83D\uDD0A Unmute audio';
      audioBtn.className = '';
      if (muteWarningEl) muteWarningEl.style.display = 'none';
    }
  });

  // ── Connect / disconnect ───────────────────────────────────────────────────
  function disconnect(reason) {
    if (muteWarningEl) muteWarningEl.style.display = 'none';
    if (audioActive && audioCtx) {
      audioCtx.close();
      audioCtx = null;
      fetch(`/session/${session}/audio/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = false;
    }
    nextPlayTime = 0;
    if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
    ws = null;
    setStatus(reason || 'Disconnected.');
    setConnected(false);
  }

  async function connect() {
    connectBtn.disabled = true;
    setStatus('Connecting…');
    nextPlayTime = 0;

    let pubsubUrl;
    try {
      const res = await fetch(`/negotiate?session=${session}&lang=${chosenLang}`);
      if (!res.ok) throw new Error('Session not found');
      pubsubUrl = (await res.json()).url;
    } catch (e) {
      setStatus('Failed to connect: ' + e.message);
      connectBtn.disabled = false;
      return;
    }

    ws = new WebSocket(pubsubUrl, 'json.webpubsub.azure.v1');

    ws.onopen = () => {
      setConnected(true);
      setStatus('Connected — reading transcript…');
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}-${chosenLang}` }));
      fetch(`/session/${session}/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
    };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        dbg(`audio bytes: ${buf.byteLength} | ctx: ${audioCtx?.state}`);
        playAudio(buf);
      }

      if (msg.type === 'message' && (msg.dataType === 'json' || msg.dataType === 'text')) {
        let d = msg.data;
        if (typeof d === 'string') { try { d = JSON.parse(d); } catch { d = null; } }
        if (d?.type === 'close') {
          disconnect('Session ended.');
        } else if (d?.type === 'phrase') {
          const text = d.text || '';
          if (text) onPhrase(text);
        } else if (d?.type === 'paused') {
          pausedPill.style.display = 'block';
        } else if (d?.type === 'resumed') {
          pausedPill.style.display = 'none';
        }
      }
    };

    ws.onerror = () => setStatus('Connection error.');

    ws.onclose = (evt) => {
      fetch(`/session/${session}/leave?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      const wasConnected = connected;
      connected = false;
      if (muteWarningEl) muteWarningEl.style.display = 'none';
      if (wasConnected) {
        setStatus('Disconnected.');
      } else {
        const reason = evt.code ? ` (code ${evt.code})` : '';
        setStatus(`Could not connect${reason}. Try again.`);
      }
      setConnected(false);
    };
  }

  connectBtn.addEventListener('click', () => {
    if (connected) disconnect();
    else connect();
  });
})();
```

- [ ] **Step 3: Commit**

```bash
git add listener/index.html listener/app.js
git commit -m "feat: word-by-word sliding window with adaptive speed on listener"
```

---

## Task 9: Audio level meter on operator panel

**Files:**
- Modify: `operator/worklet.js`
- Modify: `operator/index.html`
- Modify: `operator/app.js`

This task builds directly on the code produced by Task 7. Complete Task 7 first.

- [ ] **Step 1: Add RMS level posting to `operator/worklet.js`**

In the constructor, after `this._prevSample = 0;`, add:

```js
    this._levelCounter  = 0;
    this._levelInterval = 20;  // post a level message every 20 process() calls (~18/s at 48 kHz)
```

At the end of `process()`, just before `return true;`, add:

```js
    // Post level ~18 times/second (throttled)
    this._levelCounter++;
    if (this._levelCounter >= this._levelInterval) {
      this._levelCounter = 0;
      let sumSq = 0;
      for (let i = 0; i < mono.length; i++) sumSq += mono[i] * mono[i];
      this.port.postMessage({ type: 'level', rms: Math.sqrt(sumSq / mono.length) });
    }
```

- [ ] **Step 2: Add meter HTML and CSS to `operator/index.html`**

In the `<style>` block, after the `#pause-btn.active` rule, add:

```css
    #audio-meter {
      display: none;
      width: 100%; max-width: 480px;
      height: 6px;
      background: #1f2937;
      border-radius: 3px;
      overflow: hidden;
    }
    #audio-meter-bar {
      height: 100%; width: 0%;
      background: #22c55e;
      border-radius: 3px;
      transition: width 0.06s ease-out;
    }
```

In the `<body>`, after `</div>` closing `#controls`, add:

```html
  <div id="audio-meter"><div id="audio-meter-bar"></div></div>
```

- [ ] **Step 3: Add meter logic to `operator/app.js`**

**3a.** In the DOM refs section (after `const sourceLangSelect = ...`), add:

```js
  const audioMeter    = document.getElementById('audio-meter');
  const audioMeterBar = document.getElementById('audio-meter-bar');
```

**3b.** In the pause/keepalive section (after `let keepaliveTimer = null;`), add:

```js
  let levelDecayTimer = null;

  function setAudioLevel(rms) {
    const visual = Math.min(1, rms * 6);  // amplify: speech RMS is typically 0.02–0.15
    audioMeterBar.style.width = (visual * 100) + '%';
    if (levelDecayTimer) clearTimeout(levelDecayTimer);
    levelDecayTimer = setTimeout(() => {
      audioMeterBar.style.width = '0%';
      levelDecayTimer = null;
    }, 150);
  }

  function clearAudioLevel() {
    if (levelDecayTimer) { clearTimeout(levelDecayTimer); levelDecayTimer = null; }
    audioMeterBar.style.width = '0%';
  }
```

**3c.** In `setState`, after `pauseBtn.style.display = s === 'live' ? '' : 'none';`, add:

```js
    audioMeter.style.display = s === 'live' ? '' : 'none';
    if (s !== 'live') clearAudioLevel();
```

**3d.** In `openWebSocket`'s `ws.onclose` handler, after `stopKeepalive();`, add:

```js
      clearAudioLevel();
```

**3e.** In `startDeviceSession`, replace the `workletNode.port.onmessage` handler:

```js
        workletNode.port.onmessage = (e) => {
          if (e.data instanceof ArrayBuffer) {
            if (activeWsRef.readyState === WebSocket.OPEN && !paused) {
              activeWsRef.send(e.data);
            }
          } else if (e.data?.type === 'level') {
            setAudioLevel(e.data.rms);
          }
        };
```

**3f.** In `startFileSession`'s `sendNext` function, after `const chunk = pcm.slice(offset, offset + CHUNK);`, add:

```js
          let sumSq = 0;
          for (let i = 0; i < chunk.length; i++) {
            const s = chunk[i] / 32768;
            sumSq += s * s;
          }
          setAudioLevel(Math.sqrt(sumSq / chunk.length));
```

**3g.** In `startFileSession`'s `stopSession` lambda, after `stopKeepalive();`, add:

```js
      clearAudioLevel();
```

- [ ] **Step 4: Commit**

```bash
git add operator/worklet.js operator/index.html operator/app.js
git commit -m "feat: audio level meter on operator panel"
```

---

## Final check

- [ ] **Run the full test suite one last time**

```bash
cd ~/gibberly && source .venv/bin/activate
pytest -v
```

Expected: all tests PASS, no warnings about new code.
