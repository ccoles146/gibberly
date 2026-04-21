import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gibberly")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from backend.config import settings
from backend.session import SessionHandler
from backend.languages import SUPPORTED_LANGUAGES, get_target_languages

app = FastAPI(title="Gibberly Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.state.sessions: Dict[str, SessionHandler] = {}
app.state.current_session_id: Optional[str] = None
app.state.active_ws: Optional[WebSocket] = None

LISTENER_DIR = Path(__file__).parent.parent / "listener"
_VALID_SOURCE_LANGS = {"de-DE", "en-US"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/languages")
def list_languages():
    return [{"code": l["code"], "name": l["name"]} for l in SUPPORTED_LANGUAGES]


@app.get("/current-session")
def current_session():
    sid = app.state.current_session_id
    if not sid:
        raise HTTPException(status_code=404, detail="No active session")
    return {"session_id": sid}


@app.get("/session/{session_id}/info")
def session_info(session_id: str):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"source_lang": handler.source_lang}


@app.get("/negotiate")
def negotiate(session: str, lang: str = "en"):
    handler = app.state.sessions.get(session)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    token = handler.listener_tokens.get(lang)
    if not token:
        raise HTTPException(status_code=404, detail="Language not available for this session")
    return {"url": token}


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
def listener_join(session_id: str, lang: str = "en"):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"count": handler.listener_join(lang)}


@app.post("/session/{session_id}/leave")
def listener_leave(session_id: str, lang: str = "en"):
    handler = app.state.sessions.get(session_id)
    if not handler:
        return {"count": 0}
    return {"count": handler.listener_leave(lang)}


@app.post("/session/{session_id}/audio/join")
def audio_join(session_id: str, lang: str = "en"):
    handler = app.state.sessions.get(session_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"count": handler.audio_join(lang)}


@app.post("/session/{session_id}/audio/leave")
def audio_leave(session_id: str, lang: str = "en"):
    handler = app.state.sessions.get(session_id)
    if not handler:
        return {"count": 0}
    return {"count": handler.audio_leave(lang)}


@app.websocket("/ws/stream")
async def stream(websocket: WebSocket, source_lang: str = "de-DE"):
    await websocket.accept()

    if source_lang not in _VALID_SOURCE_LANGS:
        source_lang = "de-DE"

    old_ws = app.state.active_ws
    if old_ws is not None and old_ws.client_state != WebSocketState.DISCONNECTED:
        log.warning("Stale WebSocket detected — closing before starting new session")
        try:
            await old_ws.close(code=1001)
        except Exception:
            pass

    old_sid = app.state.current_session_id
    if old_sid:
        log.warning("Stopping orphaned session %s", old_sid)
        old_handler = app.state.sessions.pop(old_sid, None)
        app.state.current_session_id = None
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

    source_lang_code = source_lang.split("-")[0]
    target_languages = get_target_languages(source_lang_code)

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
    )
    app.state.sessions[handler.session_id] = handler
    app.state.current_session_id = handler.session_id
    log.info("Session %s starting STT (source_lang=%s)", handler.session_id, source_lang)
    handler.start()
    log.info("Session %s ready", handler.session_id)

    await websocket.send_json({
        "type": "session_created",
        "session_id": handler.session_id,
        "source_lang": source_lang,
        "listener_url": (
            f"http://{settings.backend_host}:{settings.backend_port}"
            f"/listen/index.html?session={handler.session_id}"
        ),
    })

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


if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
