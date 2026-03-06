import asyncio
import os
from pathlib import Path
from typing import Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import settings

app = FastAPI(title="Gibberly Backend")
app.state.sessions = {}

LISTENER_DIR = Path(__file__).parent.parent / "listener"


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve listener page (mounted later once listener/ dir exists)
if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
