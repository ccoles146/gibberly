# Streaming UX, Pause, Session Timeout & Config.js — Design Spec
_Date: 2026-04-21_

## Overview

Four related improvements to the Gibberly live-translation system:

1. **Word-by-word sliding window** on the listener page — smoother, more readable text delivery
2. **Pause button** on the operator console — keeps the session open but stops translation during intermissions
3. **Session timeout** — 60-minute backend hard limit, with STT stop/restart around pauses
4. **config.js restoration** — remove serve.py auto-generation; restore to a manually-editable file

---

## 1. Word-by-word sliding window (listener)

### How it works

Phrases still arrive from the backend as complete `{"type":"phrase","text":"..."}` JSON messages via Web PubSub. No backend changes are needed for this feature.

On receipt, the listener splits the phrase text into words and appends them to a pending **word queue**. A `setInterval` tick processes one word at a time from the queue:

- Appends the word to a `displayWords` array.
- Trims `displayWords` to the last 30 words (sliding window).
- Re-renders the reading pane as a single `<p>` element.

The interval period is controlled by a **speed multiplier slider** on the listener page, visible only while connected. The trickle interval adapts to the estimated incoming speech rate:

**Speed estimation:** Each time a phrase arrives from PubSub, the listener records `{timestamp, wordCount}`. The estimated pace is calculated over a rolling 1-minute window: `base_ms_per_word = 60000 / words_in_last_60s`. Before enough data has accumulated (< 60 s of history), the estimate defaults to 150 words/minute (400 ms/word).

**Slider:** Multiplier range 0.5× to 1.5×, default 1.0×, step 0.25×. The actual trickle interval = `base_ms_per_word / multiplier`. At 1.0× the display matches the estimated speech pace; at 1.5× words appear faster than they arrive (queue drains); at 0.5× words appear slower (queue grows). The chosen multiplier is persisted in `localStorage` under the key `gibberly_word_speed_multiplier`.

### Pause indication

When `{"type":"paused"}` arrives from PubSub:
- A "⏸ Paused" pill appears above the reading pane.
- The word queue continues draining at the normal rate (words in-flight finish displaying).
- No new words are added until `{"type":"resumed"}` is received, at which point the pill disappears.

### UI changes

- Replace `#last-phrase` with a `#reading-pane` element styled for the sliding window.
- Add `#speed-slider` (range input) and a label below the connect button, hidden until connected.
- Add `#paused-pill` (hidden by default, shown on pause).
- Remove `transcript-phrase` per-phrase formatting — the transcript section continues accumulating full phrases as before (unchanged).

---

## 2. Pause button (operator + backend)

### Operator frontend

- A **"⏸ Pause"** button is added to `#controls`, visible only while `state === 'live'`.
- On click:
  1. Stops the worklet/file reader from sending audio bytes (JS-side).
  2. Sends `{"type":"pause"}` as a JSON text frame over the existing WebSocket.
  3. Button label changes to **"▶ Resume"**.
- On resume click:
  1. Sends `{"type":"resume"}` as a JSON text frame.
  2. Resumes audio capture.
  3. Button label reverts to **"⏸ Pause"**.
- The pause button is disabled during `connecting` state and hidden in `idle`/`error`.
- A **keepalive**: while paused, the operator JS sends `{"type":"keepalive"}` every 30 s to prevent proxy idle-timeout on the WebSocket.

### Backend WS loop (`backend/main.py`)

Replace `websocket.receive_bytes()` with `websocket.receive()`, which returns a dict:

```python
data = await websocket.receive()
if "bytes" in data:
    if not handler.paused:
        handler.write(data["bytes"])
elif "text" in data:
    msg = json.loads(data["text"])
    if msg.get("type") == "pause":
        await handler.pause()
    elif msg.get("type") == "resume":
        await handler.resume()
    # "keepalive" and unknown types are silently ignored
```

### SessionHandler changes (`backend/session.py`)

New attribute: `self.paused: bool = False`

**`pause()` (async):**
1. Sets `self.paused = True`.
2. Calls `self._stt.pause_recognition()` — stops the Azure recogniser without closing the push stream.
3. Broadcasts `{"type":"paused"}` to all listener groups via PubSub.
4. Sends status `{"type":"paused"}` to the operator WS.

**`resume()` (async):**
1. Sets `self.paused = False`.
2. Calls `self._stt.resume_recognition()` — restarts continuous recognition on the existing push stream (1–2 s warmup acceptable).
3. Broadcasts `{"type":"resumed"}` to all listener groups via PubSub.
4. Sends status `{"type":"resumed"}` to the operator WS.

**`STTSession` new methods (`backend/stt.py`):**
- `pause_recognition()` — calls `stop_continuous_recognition_async().get()` without closing the push stream. Cancels any active cap timer.
- `resume_recognition()` — calls `start_continuous_recognition()`. Resets internal state (`_interim_text`, `_total_dispatched`).

`stop()` is unchanged and continues to close the push stream (used only on full session teardown).

**`write()`:** No change needed — the WS loop already gates on `handler.paused` before calling `write()`.

**`_process_chunk()`:** Adds a guard `if self.paused: return` at entry, in case an in-flight recognition completes during the pause transition.

### PubSub changes (`backend/pubsub.py`)

New method:

```python
def broadcast_event(self, session_id: str, event: dict) -> None:
    """Send a JSON event to all language groups for this session."""
    payload = json.dumps(event)
    for lang in SUPPORTED_LANGUAGES:
        group = f"session-{session_id}-{lang['code']}"
        try:
            self._client.send_to_group(group, payload, content_type="application/json")
        except Exception as exc:
            log.warning("broadcast_event to %s failed: %s", group, exc)
```

Used by `pause()` and `resume()`.

---

## 3. Session timeout & cleanup

### 60-minute backend timeout

A constant `SESSION_TIMEOUT_S` is added to `backend/config.py` (default `3600`, overridable via env var `SESSION_TIMEOUT_S`).

The WS receive loop in `main.py` is wrapped with `asyncio.timeout(settings.session_timeout_s)`:

```python
try:
    async with asyncio.timeout(settings.session_timeout_s):
        while True:
            data = await websocket.receive()
            ...
except asyncio.TimeoutError:
    log.warning("Session %s timed out after %ds", handler.session_id, settings.session_timeout_s)
    await websocket.close(code=1001)
```

The existing `finally` block handles cleanup (STT stop, send_close, state reset) — no duplication needed.

### Session cleanup on operator shutdown (verified)

The `finally` block already correctly handles:
- `WebSocketDisconnect` (browser tab closed, network drop)
- Any unhandled exception from the receive loop
- The new `asyncio.TimeoutError` path above

It calls `handler.stop()` → `_stt.stop()` + `_publisher.send_close()`, sending `{"type":"close"}` to all listener groups. Listener pages disconnect gracefully. No changes required.

---

## 4. config.js restoration

**`operator/serve.py`:** Remove the `config_js.write_text(...)` block entirely. The script becomes a pure HTTP server launcher — reads `.env` for `OPERATOR_PORT` only, starts `SimpleHTTPRequestHandler`, prints the URL.

**`operator/config.js`:** Restored to a static, human-editable file:

```js
// Edit GIBBERLY_BACKEND to point at your backend WebSocket URL.
// Use ws:// for local development, wss:// for production.
window.GIBBERLY_BACKEND = "ws://localhost:8000";
```

The `GIBBERLY_BACKEND` env var in `.env` and `.env.example` is kept for documentation purposes but no longer drives config.js.

---

## Files changed

| File | Change |
|------|--------|
| `listener/index.html` | Replace `#last-phrase` with reading pane + speed slider + paused pill |
| `listener/app.js` | Word queue, sliding window, speed slider, paused/resumed handling |
| `operator/index.html` | Add pause/resume button to `#controls` |
| `operator/app.js` | Pause/resume logic, keepalive timer, WS text frame sending |
| `operator/config.js` | Restore to static manually-editable file |
| `operator/serve.py` | Remove config.js auto-generation |
| `backend/main.py` | `receive()` loop, pause/resume dispatch, asyncio timeout |
| `backend/session.py` | `paused` flag, `pause()`, `resume()` methods |
| `backend/stt.py` | `pause_recognition()`, `resume_recognition()` methods |
| `backend/pubsub.py` | `broadcast_event()` method |
| `backend/config.py` | `SESSION_TIMEOUT_S` setting |

## Out of scope

- Backend-side word streaming (phrases still sent as complete strings)
- Transcript section changes (continues accumulating full phrases)
- Any changes to STT segmentation, LLM, or TTS pipeline
