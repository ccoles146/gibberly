# Option C Prototype Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a working end-to-end prototype of the live sermon translation pipeline using a local FastAPI backend, Azure Speech Translation + TTS, Azure Web PubSub, and a browser listener page.

**Architecture:** Python console streams PCM audio over WebSocket to a local FastAPI backend. The backend feeds audio to Azure Speech Translation (de-DE → en), synthesises each translated phrase via Azure TTS, and publishes the WAV bytes to listeners via Azure Web PubSub. The listener page is served by the backend and plays audio via the Web Audio API.

**Tech Stack:** Python 3.11+, FastAPI, azure-cognitiveservices-speech, azure-messaging-webpubsubservice, sounddevice, soundfile, qrcode, websockets, pytest, pytest-asyncio

---

## Project Structure

```
gibberly/
├── backend/
│   ├── main.py          # FastAPI app + WebSocket endpoint + static mount
│   ├── config.py        # Settings from .env
│   ├── session.py       # SessionHandler: wires translation → TTS → pubsub
│   ├── translation.py   # Azure Speech Translation wrapper
│   ├── tts.py           # Azure TTS wrapper
│   └── pubsub.py        # Web PubSub publisher + negotiate helper
├── console/
│   ├── main.py          # CLI entry point (device select, start/stop)
│   ├── audio.py         # Mic capture or file playback → PCM chunks
│   └── ui.py            # ASCII QR code + status printer
├── listener/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── backend/
│   │   ├── test_config.py
│   │   ├── test_session.py
│   │   ├── test_translation.py
│   │   ├── test_tts.py
│   │   └── test_pubsub.py
│   └── console/
│       ├── test_audio.py
│       └── test_ui.py
├── docs/
├── .env.example
├── requirements.txt
└── README.md
```

---

## Task 1: Azure Provisioning Guide

**Files:**
- Create: `docs/azure-setup.md`

**Step 1: Write the guide**

Create `docs/azure-setup.md` with the following content:

```markdown
# Azure Setup Guide

You need two Azure resources: **Speech** (for STT + translation + TTS) and **Web PubSub** (to relay audio to listeners). Both can be created in the Azure Portal in about 5 minutes.

## Prerequisites
- Azure account. For nonprofits: apply at https://www.microsoft.com/en-us/nonprofits/azure before this step.

## 1. Create a Speech Resource

1. Go to https://portal.azure.com → **Create a resource** → search **Speech**.
2. Select **Speech** (Microsoft) → **Create**.
3. Fill in:
   - **Subscription**: your subscription
   - **Resource group**: create new, name it `gibberly-rg`
   - **Region**: `West Europe` (or nearest to your church)
   - **Name**: `gibberly-speech`
   - **Pricing tier**: `S0` (Free tier F0 is limited to 5 hrs/month — use S0 for real use)
4. Click **Review + create** → **Create**.
5. Once deployed, go to the resource → **Keys and Endpoint**.
6. Copy **KEY 1** and **Location/Region** (e.g. `westeurope`).

## 2. Create a Web PubSub Resource

1. **Create a resource** → search **Web PubSub** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Resource name**: `gibberly-pubsub`
   - **Region**: same as Speech
   - **Pricing tier**: **Free** (supports 20k messages/day, 1 unit — sufficient for prototype)
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Settings → Keys**.
5. Copy the **Connection string** (Primary).

## 3. Configure a Hub

1. In the Web PubSub resource, go to **Settings → Hub Settings**.
2. Click **+ Add** → Hub name: `sermon` → **Anonymous connect**: Allow → **Save**.
   - "Anonymous connect" lets listeners connect without a signed token — fine for prototype; lock down for production.

## 4. Populate .env

In the gibberly project root, copy `.env.example` to `.env` and fill in:

```
AZURE_SPEECH_KEY=<KEY 1 from Speech resource>
AZURE_SPEECH_REGION=<region, e.g. westeurope>
AZURE_WEBPUBSUB_CONNECTION_STRING=<connection string from Web PubSub>
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

## 5. Verify

Run the backend health check:
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
# {"status":"ok"}
```
```

**Step 2: No tests for docs — commit**

```bash
git add docs/azure-setup.md
git commit -m "docs: add Azure provisioning guide"
```

---

## Task 2: Project Skeleton

**Files:**
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `README.md`
- Create: `tests/__init__.py`, `tests/backend/__init__.py`, `tests/console/__init__.py`

**Step 1: Create `.env.example`**

```
AZURE_SPEECH_KEY=your_speech_key_here
AZURE_SPEECH_REGION=westeurope
AZURE_WEBPUBSUB_CONNECTION_STRING=Endpoint=https://...
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

**Step 2: Create `requirements.txt`**

```
# Backend
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-dotenv==1.0.1
azure-cognitiveservices-speech==1.41.1
azure-messaging-webpubsubservice==1.2.0

# Console
sounddevice==0.5.1
soundfile==0.12.1
numpy==2.0.0
websockets==13.0
qrcode[pil]==7.4.2
Pillow==10.4.0

# Testing
pytest==8.3.0
pytest-asyncio==0.24.0
httpx==0.27.0
```

**Step 3: Create `README.md`**

```markdown
# Gibberly — Live Sermon Translation

Real-time German → English sermon translation via Azure Speech + Web PubSub.

## Quick Start

### 1. Provision Azure resources
See `docs/azure-setup.md`.

### 2. Install dependencies
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# Fill in Azure keys — see docs/azure-setup.md
```

### 4. Run the backend
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 5. Run the console (from a second terminal)
```bash
# Use microphone
python -m console.main --mode mic

# Use audio file
python -m console.main --mode file --file path/to/audio.wav
```

### 6. Listen
Scan the QR code shown in the console, or open the URL in a browser.

## Testing
```bash
pytest tests/ -v
```
```

**Step 4: Create test init files**

Create empty `tests/__init__.py`, `tests/backend/__init__.py`, `tests/console/__init__.py`.

**Step 5: Install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 6: Run tests (should be zero tests, no failures)**

```bash
pytest tests/ -v
```
Expected: `no tests ran`

**Step 7: Commit**

```bash
git add .env.example requirements.txt README.md tests/
git commit -m "chore: project skeleton with dependencies and test structure"
```

---

## Task 3: Backend Config

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/config.py`
- Create: `tests/backend/test_config.py`

**Step 1: Write failing test**

`tests/backend/test_config.py`:
```python
import os
import pytest
from unittest.mock import patch


def test_config_loads_from_env():
    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc123;Version=1.0;",
        "BACKEND_HOST": "0.0.0.0",
        "BACKEND_PORT": "8000",
    }
    with patch.dict(os.environ, env, clear=True):
        # Re-import to pick up patched env
        import importlib
        import backend.config as config_module
        importlib.reload(config_module)
        from backend.config import settings

        assert settings.azure_speech_key == "test-key"
        assert settings.azure_speech_region == "westeurope"
        assert settings.backend_port == 8000


def test_config_raises_on_missing_speech_key():
    env = {
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
    }
    with patch.dict(os.environ, env, clear=True):
        import importlib
        import backend.config as config_module
        with pytest.raises(Exception):
            importlib.reload(config_module)
```

**Step 2: Run to verify it fails**

```bash
pytest tests/backend/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.config'`

**Step 3: Write `backend/config.py`**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    azure_speech_key: str
    azure_speech_region: str
    azure_webpubsub_connection_string: str
    backend_host: str
    backend_port: int


def _load() -> Settings:
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    pubsub_cs = os.environ.get("AZURE_WEBPUBSUB_CONNECTION_STRING")

    if not key:
        raise ValueError("AZURE_SPEECH_KEY is required")
    if not region:
        raise ValueError("AZURE_SPEECH_REGION is required")
    if not pubsub_cs:
        raise ValueError("AZURE_WEBPUBSUB_CONNECTION_STRING is required")

    return Settings(
        azure_speech_key=key,
        azure_speech_region=region,
        azure_webpubsub_connection_string=pubsub_cs,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
    )


settings = _load()
```

Also create empty `backend/__init__.py`.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_config.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add backend/__init__.py backend/config.py tests/backend/test_config.py
git commit -m "feat: backend config loaded from .env with validation"
```

---

## Task 4: Backend Health Check + App Skeleton

**Files:**
- Create: `backend/main.py`
- Create: `tests/backend/test_main.py`

**Step 1: Write failing test**

`tests/backend/test_main.py`:
```python
import os
import pytest
from unittest.mock import patch

# Patch env before any import of backend modules
env = {
    "AZURE_SPEECH_KEY": "test-key",
    "AZURE_SPEECH_REGION": "westeurope",
    "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
}

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_health_check():
    with patch.dict(os.environ, env):
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        import importlib
        import backend.config as cfg
        importlib.reload(cfg)
        from backend.main import app
        import asyncio

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/health")
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}

        asyncio.run(_test())
```

**Step 2: Run to verify it fails**

```bash
pytest tests/backend/test_main.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.main'`

**Step 3: Write `backend/main.py`**

```python
import asyncio
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Gibberly Backend")

LISTENER_DIR = Path(__file__).parent.parent / "listener"


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve listener page
if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_main.py -v
```
Expected: `1 passed`

**Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: FastAPI app skeleton with health check"
```

---

## Task 5: Web PubSub Publisher

**Files:**
- Create: `backend/pubsub.py`
- Create: `tests/backend/test_pubsub.py`

**Step 1: Write failing tests**

`tests/backend/test_pubsub.py`:
```python
import pytest
from unittest.mock import MagicMock, patch


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_sends_binary_to_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")

    audio = b"\x00\x01\x02\x03"
    publisher.publish_audio("abc123", audio)

    mock_client.send_to_group.assert_called_once_with(
        "session-abc123", audio, content_type="application/octet-stream"
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_get_listener_url_returns_websocket_url(mock_client_class):
    mock_client = MagicMock()
    mock_client.get_client_access_token.return_value = {
        "url": "wss://test.webpubsub.azure.com/client/hubs/sermon?access_token=token123"
    }
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    url = publisher.get_listener_token("session42")

    assert url.startswith("wss://")
    mock_client.get_client_access_token.assert_called_once_with(
        groups=["session-session42"],
        roles=["webpubsub.joinLeaveGroup.session-session42"],
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_send_close_sends_json_to_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.send_close("sess1")

    mock_client.send_to_group.assert_called_once_with(
        "session-sess1", '{"type":"close"}', content_type="application/json"
    )
```

**Step 2: Run to verify they fail**

```bash
pytest tests/backend/test_pubsub.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.pubsub'`

**Step 3: Write `backend/pubsub.py`**

```python
from azure.messaging.webpubsubservice import WebPubSubServiceClient


class PubSubPublisher:
    def __init__(self, connection_string: str, hub: str = "sermon"):
        self._client = WebPubSubServiceClient.from_connection_string(
            connection_string, hub=hub
        )

    def publish_audio(self, session_id: str, audio_bytes: bytes) -> None:
        group = f"session-{session_id}"
        self._client.send_to_group(group, audio_bytes, content_type="application/octet-stream")

    def get_listener_token(self, session_id: str) -> str:
        group = f"session-{session_id}"
        result = self._client.get_client_access_token(
            groups=[group],
            roles=[f"webpubsub.joinLeaveGroup.{group}"],
        )
        return result["url"]

    def send_close(self, session_id: str) -> None:
        group = f"session-{session_id}"
        self._client.send_to_group(group, '{"type":"close"}', content_type="application/json")
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_pubsub.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add backend/pubsub.py tests/backend/test_pubsub.py
git commit -m "feat: Web PubSub publisher with audio relay and session close"
```

---

## Task 6: Azure TTS Wrapper

**Files:**
- Create: `backend/tts.py`
- Create: `tests/backend/test_tts.py`

**Step 1: Write failing tests**

`tests/backend/test_tts.py`:
```python
import pytest
from unittest.mock import MagicMock, patch


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_returns_audio_bytes(mock_config, mock_synthesizer_class):
    import azure.cognitiveservices.speech as speechsdk

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b"RIFF...wav-bytes"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synthesizer_class.return_value = mock_synth

    from backend.tts import synthesize
    audio = synthesize("Hello world", speech_key="key", speech_region="westeurope")

    assert audio == b"RIFF...wav-bytes"
    mock_synth.speak_text_async.assert_called_once_with("Hello world")


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_raises_on_failure(mock_config, mock_synthesizer_class):
    import azure.cognitiveservices.speech as speechsdk

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.Canceled
    mock_result.cancellation_details.error_details = "quota exceeded"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synthesizer_class.return_value = mock_synth

    from backend.tts import synthesize
    with pytest.raises(RuntimeError, match="quota exceeded"):
        synthesize("Hello", speech_key="key", speech_region="westeurope")
```

**Step 2: Run to verify they fail**

```bash
pytest tests/backend/test_tts.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.tts'`

**Step 3: Write `backend/tts.py`**

```python
import azure.cognitiveservices.speech as speechsdk

VOICE = "en-US-JennyNeural"


def synthesize(text: str, speech_key: str, speech_region: str) -> bytes:
    """Synthesise English text to WAV bytes using Azure Neural TTS."""
    config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    config.speech_synthesis_voice_name = VOICE
    # audio_config=None → output to memory (result.audio_data)
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    result = synth.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data

    raise RuntimeError(
        f"TTS failed: {result.cancellation_details.error_details}"
    )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_tts.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add backend/tts.py tests/backend/test_tts.py
git commit -m "feat: Azure TTS wrapper returning WAV bytes"
```

---

## Task 7: Speech Translation Wrapper

**Files:**
- Create: `backend/translation.py`
- Create: `tests/backend/test_translation.py`

**Step 1: Write failing tests**

`tests/backend/test_translation.py`:
```python
import pytest
from unittest.mock import MagicMock, call, patch


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
def test_session_starts_continuous_recognition(
    mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.translation import TranslationSession
    session = TranslationSession(speech_key="k", speech_region="r", on_translation=lambda t: None)
    session.start()

    mock_recognizer.start_continuous_recognition.assert_called_once()


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
def test_write_pushes_bytes_to_stream(
    mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream

    from backend.translation import TranslationSession
    session = TranslationSession(speech_key="k", speech_region="r", on_translation=lambda t: None)
    session.write(b"\x01\x02\x03")

    mock_stream.write.assert_called_once_with(b"\x01\x02\x03")


@patch("backend.translation.speechsdk.translation.TranslationRecognizer")
@patch("backend.translation.speechsdk.translation.SpeechTranslationConfig")
@patch("backend.translation.speechsdk.audio.AudioConfig")
@patch("backend.translation.speechsdk.audio.PushAudioInputStream")
def test_recognized_callback_fires_on_translation(
    mock_stream_class, mock_audio_config, mock_config_class, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk

    captured = []
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.translation import TranslationSession
    session = TranslationSession(
        speech_key="k", speech_region="r", on_translation=captured.append
    )

    # Simulate the SDK firing the recognized event
    evt = MagicMock()
    evt.result.translations = {"en": "Peace be with you"}
    # The session registers a handler via recognizer.recognized.connect(handler)
    # Grab the registered handler and call it directly
    handler = mock_recognizer.recognized.connect.call_args[0][0]
    handler(evt)

    assert captured == ["Peace be with you"]
```

**Step 2: Run to verify they fail**

```bash
pytest tests/backend/test_translation.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.translation'`

**Step 3: Write `backend/translation.py`**

```python
from typing import Callable
import azure.cognitiveservices.speech as speechsdk


class TranslationSession:
    """Wraps Azure Speech Translation for a single streaming session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_translation: Callable[[str], None],
    ):
        fmt = speechsdk.audio.AudioStreamFormat.get_wave_format_pcm(16000, 16, 1)
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.translation.SpeechTranslationConfig(
            subscription=speech_key, region=speech_region
        )
        config.speech_recognition_language = "de-DE"
        config.add_target_language("en")

        self._recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=config, audio_config=audio_config
        )
        self._recognizer.recognized.connect(
            lambda evt: self._on_recognized(evt, on_translation)
        )

    def _on_recognized(self, evt, on_translation: Callable[[str], None]) -> None:
        translation = evt.result.translations.get("en", "")
        if translation:
            on_translation(translation)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_translation.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add backend/translation.py tests/backend/test_translation.py
git commit -m "feat: Azure Speech Translation wrapper with PushAudioInputStream"
```

---

## Task 8: Session Handler (wires translation → TTS → pubsub)

**Files:**
- Create: `backend/session.py`
- Create: `tests/backend/test_session.py`

**Step 1: Write failing tests**

`tests/backend/test_session.py`:
```python
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_deps():
    """Returns (mock_translation_session, mock_tts_synthesize, mock_publisher)."""
    with patch("backend.session.TranslationSession") as mock_ts_class, \
         patch("backend.session.synthesize") as mock_synth, \
         patch("backend.session.PubSubPublisher") as mock_pub_class:

        mock_ts = MagicMock()
        mock_ts_class.return_value = mock_ts

        mock_pub = MagicMock()
        mock_pub_class.return_value = mock_pub
        mock_pub.get_listener_token.return_value = "wss://pubsub.example.com/token123"

        mock_synth.return_value = b"RIFF...wav"

        yield mock_ts_class, mock_synth, mock_pub_class, mock_ts, mock_pub


def test_session_has_unique_id(mock_deps):
    from backend.session import SessionHandler
    s1 = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    s2 = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    assert s1.session_id != s2.session_id


def test_session_listener_url_contains_session_id(mock_deps):
    *_, mock_ts, mock_pub = mock_deps
    from backend.session import SessionHandler
    handler = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    url = handler.listener_token
    assert url == "wss://pubsub.example.com/token123"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id)


def test_write_audio_forwards_to_translation_session(mock_deps):
    *_, mock_ts, mock_pub = mock_deps
    from backend.session import SessionHandler
    handler = SessionHandler(speech_key="k", speech_region="r", pubsub_cs="cs")
    handler.start()
    handler.write(b"\xde\xad\xbe\xef")
    mock_ts.write.assert_called_once_with(b"\xde\xad\xbe\xef")


def test_on_translation_synthesizes_and_publishes(mock_deps):
    mock_ts_class, mock_synth, mock_pub_class, mock_ts, mock_pub = mock_deps
    loop = asyncio.new_event_loop()

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="k", speech_region="r", pubsub_cs="cs", loop=loop
    )
    handler.start()

    # Grab the on_translation callback passed to TranslationSession
    on_translation = mock_ts_class.call_args[1]["on_translation"]

    # Fire it (simulates SDK callback on background thread)
    on_translation("Guten Morgen")

    # Run the loop to process the coroutine
    loop.run_until_complete(asyncio.sleep(0.05))

    mock_synth.assert_called_once_with("Guten Morgen", speech_key="k", speech_region="r")
    mock_pub.publish_audio.assert_called_once_with(handler.session_id, b"RIFF...wav")
    loop.close()
```

**Step 2: Run to verify they fail**

```bash
pytest tests/backend/test_session.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.session'`

**Step 3: Write `backend/session.py`**

```python
import asyncio
import uuid
from typing import Optional

from backend.translation import TranslationSession
from backend.tts import synthesize
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates translation → TTS → Web PubSub for one streaming session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.session_id = str(uuid.uuid4())
        self._speech_key = speech_key
        self._speech_region = speech_region
        self._loop = loop or asyncio.get_event_loop()

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._translation = TranslationSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_translation=self._on_translation,
        )

    def _on_translation(self, text: str) -> None:
        """Called from Azure SDK background thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(self._synthesize_and_publish(text), self._loop)

    async def _synthesize_and_publish(self, text: str) -> None:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None, synthesize, text, self._speech_key, self._speech_region
        )
        await loop.run_in_executor(
            None, self._publisher.publish_audio, self.session_id, audio_bytes
        )

    def start(self) -> None:
        self._translation.start()

    def write(self, audio_bytes: bytes) -> None:
        self._translation.write(audio_bytes)

    def stop(self) -> None:
        self._translation.stop()
        self._publisher.send_close(self.session_id)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/backend/test_session.py -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add backend/session.py tests/backend/test_session.py
git commit -m "feat: SessionHandler wiring translation → TTS → Web PubSub"
```

---

## Task 9: Backend WebSocket Endpoint + Negotiate Route

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/backend/test_main.py`

**Step 1: Add failing tests to `tests/backend/test_main.py`**

Append to the existing test file:

```python
@patch("backend.main.SessionHandler")
def test_negotiate_returns_pubsub_url(mock_session_class):
    mock_session = MagicMock()
    mock_session.session_id = "test-uuid"
    mock_session.listener_token = "wss://pubsub.example.com/token"
    mock_session_class.return_value = mock_session

    import asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from backend.main import app

    async def _test():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First establish a session via ws (mocked), then negotiate
            # For simplicity: hit negotiate with a known session id via app state
            app.state.sessions = {"test-uuid": mock_session}
            r = await client.get("/negotiate?session=test-uuid")
            assert r.status_code == 200
            assert r.json()["url"] == "wss://pubsub.example.com/token"

    asyncio.run(_test())
```

**Step 2: Run to verify it fails**

```bash
pytest tests/backend/test_main.py::test_negotiate_returns_pubsub_url -v
```
Expected: `FAILED` (no /negotiate endpoint)

**Step 3: Update `backend/main.py`**

```python
import asyncio
import os
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

    # Send session info to the console
    await websocket.send_json({
        "type": "session_created",
        "session_id": handler.session_id,
        "listener_url": f"http://{settings.backend_host}:{settings.backend_port}/listen/index.html?session={handler.session_id}",
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
```

**Step 4: Run all backend tests**

```bash
pytest tests/backend/ -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: WebSocket stream endpoint and negotiate route"
```

---

## Task 10: Listener Page

**Files:**
- Create: `listener/index.html`
- Create: `listener/app.js`

No unit tests for static HTML/JS in this prototype — verified manually in Task 12.

**Step 1: Create `listener/index.html`**

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
    }
    h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
    #status { font-size: 0.9rem; color: #888; margin-bottom: 2rem; }
    #listen-btn {
      padding: 1.2rem 3rem; font-size: 1.2rem;
      background: #2563eb; color: #fff;
      border: none; border-radius: 2rem; cursor: pointer;
    }
    #listen-btn:disabled { background: #444; cursor: default; }
    #last-phrase { margin-top: 2rem; font-size: 1rem; color: #aaa; text-align: center; }
  </style>
</head>
<body>
  <h1>Live Translation</h1>
  <p id="status">Tap to connect</p>
  <button id="listen-btn">Listen</button>
  <p id="last-phrase"></p>
  <script src="app.js"></script>
</body>
</html>
```

**Step 2: Create `listener/app.js`**

```javascript
(function () {
  const btn = document.getElementById('listen-btn');
  const statusEl = document.getElementById('status');
  const phraseEl = document.getElementById('last-phrase');

  const params = new URLSearchParams(window.location.search);
  const session = params.get('session');
  if (!session) {
    statusEl.textContent = 'No session ID in URL.';
    btn.disabled = true;
    return;
  }

  let audioCtx = null;
  let nextPlayTime = 0;
  let ws = null;

  function setStatus(msg) { statusEl.textContent = msg; }

  async function getNegotiateUrl() {
    const res = await fetch(`/negotiate?session=${session}`);
    if (!res.ok) throw new Error('Session not found');
    const { url } = await res.json();
    return url;
  }

  function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const buf = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  async function playWav(arrayBuffer) {
    try {
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const src = audioCtx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(audioCtx.destination);
      const now = audioCtx.currentTime;
      const startAt = Math.max(now, nextPlayTime);
      src.start(startAt);
      nextPlayTime = startAt + audioBuffer.duration;
    } catch (e) {
      console.warn('Audio decode error:', e);
    }
  }

  async function connect() {
    btn.disabled = true;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    setStatus('Connecting…');

    let pubsubUrl;
    try {
      pubsubUrl = await getNegotiateUrl();
    } catch (e) {
      setStatus('Failed to get session: ' + e.message);
      btn.disabled = false;
      return;
    }

    // Connect with the Web PubSub subprotocol so we can receive group messages
    ws = new WebSocket(pubsubUrl, 'json.webpubsub.azure.v1');

    ws.onopen = () => {
      setStatus('Connected — waiting for audio…');
      // Join the session group
      ws.send(JSON.stringify({ type: 'joinGroup', group: `session-${session}` }));
    };

    ws.onmessage = async (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === 'message' && msg.dataType === 'binary') {
        const buf = base64ToArrayBuffer(msg.data);
        await playWav(buf);
      }

      if (msg.type === 'message' && msg.dataType === 'json' && msg.data?.type === 'close') {
        setStatus('Session ended.');
        ws.close();
      }
    };

    ws.onerror = () => setStatus('Connection error. Retrying…');

    ws.onclose = () => {
      setStatus('Disconnected. Reload to reconnect.');
    };
  }

  btn.addEventListener('click', connect);
})();
```

**Step 3: Commit**

```bash
git add listener/
git commit -m "feat: listener page with Web Audio API and Web PubSub group subscription"
```

---

## Task 11: Console Audio Module

**Files:**
- Create: `console/__init__.py`
- Create: `console/audio.py`
- Create: `tests/console/test_audio.py`

**Step 1: Write failing tests**

`tests/console/test_audio.py`:
```python
import numpy as np
import pytest
from unittest.mock import patch, MagicMock


def test_file_source_yields_pcm_chunks(tmp_path):
    import soundfile as sf
    # Create a 0.5s test WAV at 16kHz mono
    samples = np.zeros(8000, dtype=np.int16)
    wav_path = tmp_path / "test.wav"
    sf.write(str(wav_path), samples, 16000, subtype="PCM_16")

    from console.audio import FileAudioSource
    source = FileAudioSource(str(wav_path), chunk_ms=100)
    chunks = list(source.chunks())

    # 0.5s at 100ms chunks = ~5 chunks
    assert len(chunks) == 5
    # Each chunk: 100ms * 16000 samples/s * 2 bytes/sample = 3200 bytes
    assert all(len(c) == 3200 for c in chunks)


def test_file_source_resamples_to_16khz(tmp_path):
    import soundfile as sf
    # Create a 44.1kHz file — should be resampled
    samples = np.zeros(22050, dtype=np.int16)  # 0.5s at 44.1kHz
    wav_path = tmp_path / "hifi.wav"
    sf.write(str(wav_path), samples, 44100, subtype="PCM_16")

    from console.audio import FileAudioSource
    source = FileAudioSource(str(wav_path), chunk_ms=100)
    chunks = list(source.chunks())

    # After resampling to 16kHz: 0.5s = 8000 samples = 5 chunks of 3200 bytes
    assert len(chunks) == 5
```

**Step 2: Run to verify they fail**

```bash
pytest tests/console/test_audio.py -v
```
Expected: `ModuleNotFoundError: No module named 'console.audio'`

**Step 3: Write `console/audio.py`**

Note: resampling requires `scipy`. Add to `requirements.txt`:
```
scipy==1.14.0
```

Then reinstall: `pip install -r requirements.txt`

```python
from typing import Iterator
import numpy as np
import soundfile as sf
import sounddevice as sd


SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


class FileAudioSource:
    """Streams a WAV file as 16kHz mono PCM chunks."""

    def __init__(self, path: str, chunk_ms: int = 100):
        self._path = path
        self._chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    def chunks(self) -> Iterator[bytes]:
        data, sr = sf.read(self._path, dtype=DTYPE, always_2d=False)
        # Convert stereo → mono
        if data.ndim == 2:
            data = data.mean(axis=1).astype(DTYPE)
        # Resample to 16kHz if needed
        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            target_len = int(len(data) * SAMPLE_RATE / sr)
            data = resample(data, target_len).astype(DTYPE)

        for i in range(0, len(data) - self._chunk_samples + 1, self._chunk_samples):
            yield data[i : i + self._chunk_samples].tobytes()


class MicAudioSource:
    """Streams live microphone input as 16kHz mono PCM chunks."""

    def __init__(self, device: int = None, chunk_ms: int = 100):
        self._device = device
        self._chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    def chunks(self) -> Iterator[bytes]:
        """Yields chunks until KeyboardInterrupt."""
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=self._chunk_samples,
            device=self._device,
            channels=CHANNELS,
            dtype=DTYPE,
        ) as stream:
            while True:
                data, _ = stream.read(self._chunk_samples)
                yield bytes(data)


def list_devices() -> list[dict]:
    """Return available input audio devices."""
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/console/test_audio.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add console/__init__.py console/audio.py tests/console/test_audio.py requirements.txt
git commit -m "feat: console audio module — file source with resampling and mic source"
```

---

## Task 12: Console UI Module

**Files:**
- Create: `console/ui.py`
- Create: `tests/console/test_ui.py`

**Step 1: Write failing tests**

`tests/console/test_ui.py`:
```python
def test_qr_lines_are_non_empty():
    from console.ui import qr_lines
    lines = qr_lines("https://example.com")
    assert len(lines) > 5
    assert all(isinstance(l, str) for l in lines)


def test_status_line_contains_key_fields():
    from console.ui import format_status
    line = format_status(
        connected=True,
        listener_count=2,
        elapsed_s=90,
        last_phrase="Hello world",
    )
    assert "LIVE" in line
    assert "2" in line
    assert "1:30" in line
    assert "Hello world" in line
```

**Step 2: Run to verify they fail**

```bash
pytest tests/console/test_ui.py -v
```
Expected: `ModuleNotFoundError: No module named 'console.ui'`

**Step 3: Write `console/ui.py`**

```python
import io
import qrcode


def qr_lines(url: str) -> list[str]:
    """Return the QR code for `url` as a list of ASCII art strings."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf)
    return buf.getvalue().splitlines()


def format_status(
    connected: bool,
    listener_count: int,
    elapsed_s: int,
    last_phrase: str,
) -> str:
    state = "LIVE" if connected else "OFFLINE"
    mins, secs = divmod(elapsed_s, 60)
    phrase = (last_phrase[:60] + "…") if len(last_phrase) > 60 else last_phrase
    return f"[{state}] listeners={listener_count}  elapsed={mins}:{secs:02d}  last=\"{phrase}\""
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/console/test_ui.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add console/ui.py tests/console/test_ui.py
git commit -m "feat: console UI — ASCII QR code and status line formatter"
```

---

## Task 13: Console Main (CLI entry point)

**Files:**
- Create: `console/main.py`

No unit tests for the top-level CLI glue — covered by Task 14 end-to-end test.

**Step 1: Create `console/main.py`**

```python
"""
Operator console — streams audio to the Gibberly backend.

Usage:
  python -m console.main --mode file --file audio/test.wav
  python -m console.main --mode mic [--device 0]
  python -m console.main --list-devices
"""

import argparse
import asyncio
import json
import sys
import time
import threading

import websockets

from console.audio import FileAudioSource, MicAudioSource, list_devices
from console.ui import qr_lines, format_status


def parse_args():
    p = argparse.ArgumentParser(description="Gibberly operator console")
    p.add_argument("--backend", default="ws://localhost:8000", help="Backend WebSocket base URL")
    p.add_argument("--mode", choices=["mic", "file"], default="mic")
    p.add_argument("--file", help="Path to WAV file (--mode file)")
    p.add_argument("--device", type=int, default=None, help="Audio input device index")
    p.add_argument("--list-devices", action="store_true")
    return p.parse_args()


async def run(args):
    if args.list_devices:
        for d in list_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']} ch)")
        return

    uri = f"{args.backend}/ws/stream"
    print(f"Connecting to {uri} …")

    async with websockets.connect(uri) as ws:
        # Receive session info
        raw = await ws.recv()
        session = json.loads(raw)
        print(f"\nSession: {session['session_id']}")

        listener_url = session["listener_url"]
        print(f"Listener URL: {listener_url}\n")
        for line in qr_lines(listener_url):
            print(line)

        print("\nStreaming audio. Press Ctrl+C to stop.\n")

        start_time = time.time()
        last_phrase = ""

        # Audio source
        if args.mode == "file":
            if not args.file:
                print("--file is required for --mode file")
                sys.exit(1)
            source = FileAudioSource(args.file)
        else:
            source = MicAudioSource(device=args.device)

        # Stream in a thread so we can update status line
        async def stream_chunks():
            nonlocal last_phrase
            for chunk in source.chunks():
                await ws.send(chunk)
                elapsed = int(time.time() - start_time)
                status = format_status(
                    connected=True,
                    listener_count=0,   # TODO: pull from backend stats endpoint
                    elapsed_s=elapsed,
                    last_phrase=last_phrase,
                )
                print(f"\r{status}", end="", flush=True)

        try:
            await stream_chunks()
        except KeyboardInterrupt:
            pass
        finally:
            print("\nStopping session…")


def main():
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add console/main.py
git commit -m "feat: console CLI — streams mic or file audio with QR display and status"
```

---

## Task 14: End-to-End Smoke Test

This task verifies the whole pipeline with a real audio file and real Azure credentials. It is manual, not automated — you need `.env` populated with valid Azure keys first.

**Prerequisites:**
- `.env` populated (see `docs/azure-setup.md`)
- A German WAV test file. If you don't have one, create a silent placeholder:
  ```bash
  python -c "
  import numpy as np, soundfile as sf
  sf.write('test_audio.wav', np.zeros(48000, dtype=np.int16), 16000, subtype='PCM_16')
  "
  ```
  Better: download a short German speech sample. One option:
  ```bash
  # Any German TTS sample — even Azure TTS can generate one for testing:
  python -c "
  from dotenv import load_dotenv; load_dotenv()
  import os, azure.cognitiveservices.speech as speechsdk
  cfg = speechsdk.SpeechConfig(subscription=os.environ['AZURE_SPEECH_KEY'], region=os.environ['AZURE_SPEECH_REGION'])
  cfg.speech_synthesis_voice_name = 'de-DE-KatjaNeural'
  synth = speechsdk.SpeechSynthesizer(speech_config=cfg)
  synth.speak_text_async('Guten Morgen. Dies ist ein Test der Übersetzung.').get()
  " > test_audio_tts.py
  # This generates audio through the default speaker — record it, or use the file output approach below
  ```

  Easiest: use Azure TTS to write a WAV file directly:
  ```bash
  python -c "
  from dotenv import load_dotenv; load_dotenv()
  import os, azure.cognitiveservices.speech as speechsdk
  cfg = speechsdk.SpeechConfig(subscription=os.environ['AZURE_SPEECH_KEY'], region=os.environ['AZURE_SPEECH_REGION'])
  cfg.speech_synthesis_voice_name = 'de-DE-KatjaNeural'
  audio_cfg = speechsdk.audio.AudioOutputConfig(filename='test_audio.wav')
  synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=audio_cfg)
  synth.speak_text_async('Guten Morgen. Willkommen im Gottesdienst. Dies ist ein Test der Übersetzung.').get()
  print('Written test_audio.wav')
  "
  ```

**Step 1: Start the backend**

Terminal 1:
```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Expected output: `Uvicorn running on http://0.0.0.0:8000`

**Step 2: Open the listener page**

In a browser: `http://localhost:8000/listen/index.html?session=` — the session ID will come from the console in the next step, but open the base URL now to confirm it loads.

Expected: Listener page loads with "Tap to connect" and a Listen button.

**Step 3: Run the console with the test file**

Terminal 2:
```bash
source .venv/bin/activate
python -m console.main --mode file --file test_audio.wav
```

Expected:
- QR code printed to terminal
- Status line updating
- Listener URL printed (e.g. `http://0.0.0.0:8000/listen/index.html?session=<uuid>`)

**Step 4: Open listener URL and tap Listen**

Copy the listener URL from the console output, open in browser, tap **Listen**.

Expected: English translation of the German audio plays through the browser within 5 seconds of the file starting.

**Step 5: Run all automated tests to confirm nothing is broken**

```bash
pytest tests/ -v
```
Expected: all pass

**Step 6: Final commit**

```bash
git add test_audio.wav  # only if you want to commit the test file
git commit -m "test: end-to-end smoke test verified — pipeline working"
```

---

## Appendix: Running on Windows (with microphone)

On your Windows PC, the same `requirements.txt` applies. Install Python 3.11+ from python.org.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Fill in .env with Azure keys

# List audio devices
python -m console.main --list-devices

# Stream from microphone (use device index from above)
python -m console.main --mode mic --device 0 --backend ws://<linux-box-ip>:8000
```

The backend stays on the Linux dev machine. The console runs on Windows and points `--backend` at the Linux box's IP.

---

## Appendix: Common Issues

**`sounddevice` PortAudio error on Linux:** Install system dependency first:
```bash
sudo apt-get install libportaudio2
```

**`azure-cognitiveservices-speech` install fails:** The SDK has a native binary component. On Linux, it requires:
```bash
sudo apt-get install libssl-dev ca-certificates
```

**Web PubSub `joinGroup` fails:** Ensure "Anonymous connect" is enabled on the `sermon` hub in the Azure Portal (see `docs/azure-setup.md` step 3). Also ensure the hub name in `pubsub.py` matches exactly.

**TTS returns empty audio:** Check that your Speech resource is `S0` tier. The `F0` free tier blocks Neural voices in some regions.
