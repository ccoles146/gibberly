import asyncio
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.session import SessionHandler

app = FastAPI(title="Gibberly Backend")
app.state.sessions: Dict[str, SessionHandler] = {}

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


@app.websocket("/ws/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    handler = SessionHandler(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        pubsub_cs=settings.azure_webpubsub_connection_string,
        loop=loop,
    )
    app.state.sessions[handler.session_id] = handler
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


if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
