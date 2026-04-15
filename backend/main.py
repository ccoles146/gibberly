import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gibberly")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from backend.config import settings
from backend.session import SessionHandler

app = FastAPI(title="Gibberly Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.state.sessions: Dict[str, SessionHandler] = {}
app.state.current_session_id: Optional[str] = None
app.state.active_ws: Optional[WebSocket] = None

LISTENER_DIR = Path(__file__).parent.parent / "listener"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/current-session")
def current_session():
    sid = app.state.current_session_id
    if not sid:
        raise HTTPException(status_code=404, detail="No active session")
    return {"session_id": sid}


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

    # Close any stale connection from a previous console that didn't disconnect cleanly.
    old_ws = app.state.active_ws
    if old_ws is not None and old_ws.client_state != WebSocketState.DISCONNECTED:
        log.warning("Stale WebSocket detected — closing before starting new session")
        try:
            await old_ws.close(code=1001)
        except Exception:
            pass

    # Stop and discard any session left over from the stale connection.
    old_sid = app.state.current_session_id
    if old_sid:
        log.warning("Stopping orphaned session %s", old_sid)
        old_handler = app.state.sessions.pop(old_sid, None)
        app.state.current_session_id = None  # clear state before stop, not after
        if old_handler:
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, old_handler.stop)
                log.info("Orphaned session %s stopped", old_sid)
            except Exception as exc:
                log.error("Error stopping orphaned session %s: %s", old_sid, exc)

    app.state.active_ws = websocket
    loop = asyncio.get_event_loop()

    async def send_status(msg: dict) -> None:
        await websocket.send_json(msg)

    handler = SessionHandler(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        pubsub_cs=settings.azure_webpubsub_connection_string,
        openai_endpoint=settings.azure_openai_endpoint,
        openai_api_key=settings.azure_openai_api_key,
        openai_deployment=settings.azure_openai_deployment,
        silence_timeout_ms=settings.stt_silence_timeout_ms,
        time_cap_s=settings.stt_time_cap_s,
        context_window=settings.llm_context_window,
        loop=loop,
        on_status=send_status,
    )
    app.state.sessions[handler.session_id] = handler
    app.state.current_session_id = handler.session_id
    log.info("Session %s starting STT", handler.session_id)
    handler.start()
    log.info("Session %s ready", handler.session_id)

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
        log.info("Session %s — operator disconnected (WebSocketDisconnect)", handler.session_id)
    except Exception as exc:
        log.error("Session %s — unexpected error in receive loop: %s", handler.session_id, exc)
    finally:
        # Clear state immediately so a reconnecting console never sees stale session.
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
            log.error("Session %s stop error (state already cleared): %s", handler.session_id, exc)


if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
