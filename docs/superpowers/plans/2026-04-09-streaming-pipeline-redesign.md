# Streaming Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace word-level timer chunking with recognized-event buffering, combine LLM cleaning + translation with a context window, and stream TTS audio via the `synthesizing` event — fixing broken phrasing and burst-then-silence audio.

**Architecture:** `STTSession` dispatches full utterances on `recognized` events (or a 4s time cap). `LLMTranslator` cleans + translates in a single GPT-4o mini call with a rolling 5-utterance context window. `TTSSynthesizer` streams audio via the `synthesizing` event callback. `SessionHandler` orchestrates the async pipeline.

**Tech Stack:** Python 3.13, FastAPI, `azure-cognitiveservices-speech`, `openai>=1.30`, `pytest`, `unittest.mock`

**Spec:** `docs/superpowers/specs/2026-04-09-streaming-pipeline-redesign-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/config.py` | Modify | Remove translator/chunk fields, add silence timeout + time cap + context window |
| `backend/stt.py` | Rewrite | Recognized-event dispatch with 4s time cap |
| `backend/llm_translator.py` | Create | Combined clean + translate with context window |
| `backend/tts.py` | Modify | Streaming via `synthesizing` event |
| `backend/session.py` | Modify | New pipeline orchestration |
| `backend/main.py` | Modify | Pass new config fields |
| `backend/llm_cleaner.py` | Delete | Replaced by llm_translator.py |
| `backend/text_translator.py` | Delete | Replaced by llm_translator.py |
| `operator/app.js` | Modify | Display raw_de / clean_de / en_text |
| `tests/backend/test_config.py` | Rewrite | Test new/removed fields |
| `tests/backend/test_stt.py` | Rewrite | Test recognized-event + time cap |
| `tests/backend/test_llm_translator.py` | Create | Test combined clean+translate, context window, fallback |
| `tests/backend/test_tts.py` | Rewrite | Test synthesizing event streaming |
| `tests/backend/test_session.py` | Rewrite | Test new pipeline with LLMTranslator |
| `tests/backend/test_main.py` | Modify | Update env dicts |
| `tests/backend/test_llm_cleaner.py` | Delete | Replaced by test_llm_translator.py |
| `tests/backend/test_text_translator.py` | Delete | Replaced by test_llm_translator.py |
| `requirements.txt` | Modify | Remove httpx |
| `.env.example` | Modify | Update env vars |
| `docs/azure-setup.md` | Modify | Remove Translator section |

---

## Task 1: Config — remove old fields, add new fields

**Files:**
- Modify: `backend/config.py`
- Rewrite: `tests/backend/test_config.py`
- Modify: `tests/backend/test_main.py`

- [ ] **Step 1: Write failing tests for new config fields**

Replace `tests/backend/test_config.py` entirely:

```python
import os
import pytest
from unittest.mock import patch


def test_config_loads_from_env():
    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc123;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "BACKEND_HOST": "0.0.0.0",
        "BACKEND_PORT": "8000",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        settings = _load()
        assert settings.azure_speech_key == "test-key"
        assert settings.azure_speech_region == "westeurope"
        assert settings.backend_port == 8000


def test_config_raises_on_missing_speech_key():
    env = {
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_SPEECH_KEY"):
            _load()


def test_config_defaults():
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
        assert s.stt_silence_timeout_ms == 1000
        assert s.stt_time_cap_s == 4.0
        assert s.llm_context_window == 5


def test_config_overrides_from_env():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "STT_SILENCE_TIMEOUT_MS": "1500",
        "STT_TIME_CAP_S": "5.0",
        "LLM_CONTEXT_WINDOW": "8",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.stt_silence_timeout_ms == 1500
        assert s.stt_time_cap_s == 5.0
        assert s.llm_context_window == 8


def test_config_raises_on_missing_openai_endpoint():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            _load()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_config.py -v
```

Expected: FAIL — `Settings` still has `azure_translator_key` etc., missing new fields.

- [ ] **Step 3: Update `backend/config.py`**

Replace the entire file:

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
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    backend_host: str
    backend_port: int
    stt_silence_timeout_ms: int
    stt_time_cap_s: float
    llm_context_window: int


def _load() -> Settings:
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    pubsub_cs = os.environ.get("AZURE_WEBPUBSUB_CONNECTION_STRING")
    openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")

    if not key:
        raise ValueError("AZURE_SPEECH_KEY is required")
    if not region:
        raise ValueError("AZURE_SPEECH_REGION is required")
    if not pubsub_cs:
        raise ValueError("AZURE_WEBPUBSUB_CONNECTION_STRING is required")
    if not openai_endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT is required")
    if not openai_api_key:
        raise ValueError("AZURE_OPENAI_API_KEY is required")
    if not openai_deployment:
        raise ValueError("AZURE_OPENAI_DEPLOYMENT is required")

    return Settings(
        azure_speech_key=key,
        azure_speech_region=region,
        azure_webpubsub_connection_string=pubsub_cs,
        azure_openai_endpoint=openai_endpoint,
        azure_openai_api_key=openai_api_key,
        azure_openai_deployment=openai_deployment,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
        stt_silence_timeout_ms=int(os.environ.get("STT_SILENCE_TIMEOUT_MS", "1000")),
        stt_time_cap_s=float(os.environ.get("STT_TIME_CAP_S", "4.0")),
        llm_context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", "5")),
    )


settings = _load()
```

- [ ] **Step 4: Update all `env` dicts in `tests/backend/test_main.py`**

There are 8 `env` dicts in `test_main.py`. In each one, **remove** these keys:

```python
"AZURE_TRANSLATOR_KEY": "tr-key",
"AZURE_TRANSLATOR_REGION": "westeurope",
```

The module-level `env` dict (line 5) and each function-level `env` dict all need the translator keys removed. No new keys needed — the new fields all have defaults.

- [ ] **Step 5: Run config and main tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_config.py tests/backend/test_main.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd ~/gibberly && git add backend/config.py tests/backend/test_config.py tests/backend/test_main.py
git commit -m "feat: config — replace translator/chunk fields with silence timeout, time cap, context window"
```

---

## Task 2: STTSession — recognized-event dispatch with time cap

**Files:**
- Rewrite: `backend/stt.py`
- Rewrite: `tests/backend/test_stt.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/backend/test_stt.py` entirely:

```python
import threading
import time
from unittest.mock import MagicMock, patch


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_starts_continuous_recognition(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer = MagicMock()
    mock_recognizer_class.return_value = mock_recognizer

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.start()

    mock_recognizer.start_continuous_recognition.assert_called_once()


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_write_pushes_bytes(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_recognizer_class.return_value = MagicMock()

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=lambda t: None)
    session.write(b"\x01\x02\x03")

    mock_stream.write.assert_called_once_with(b"\x01\x02\x03")


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_dispatches_full_text(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    evt.result.text = "Das ist gut und schön"
    session._on_recognized(evt)

    assert dispatched == ["Das ist gut und schön"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_non_speech_skipped(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.NoMatch
    evt.result.text = ""
    session._on_recognized(evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_empty_text_skipped(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    evt = MagicMock()
    evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    evt.result.text = ""
    session._on_recognized(evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_time_cap_dispatches_interim_text(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,  # short cap for testing
    )

    # Simulate recognizing event (interim text arrives)
    evt = MagicMock()
    evt.result.text = "Das ist ein langer Satz"
    session._on_recognizing(evt)

    # Wait for the time cap to fire
    time.sleep(0.3)

    assert dispatched == ["Das ist ein langer Satz"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_cancels_time_cap(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.5,  # long enough that recognized fires first
    )

    # Interim text arrives, starts cap timer
    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)

    # Recognized fires before cap — dispatches final text, cancels cap
    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Das ist gut und schön"
    session._on_recognized(final_evt)

    # Wait to ensure cap doesn't fire a duplicate
    time.sleep(0.7)

    assert dispatched == ["Das ist gut und schön"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_time_cap_clears_interim_after_dispatch(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(
        speech_key="k", speech_region="r",
        on_text=dispatched.append,
        time_cap_s=0.1,
    )

    # First interim + cap dispatch
    evt = MagicMock()
    evt.result.text = "Erster Satz"
    session._on_recognizing(evt)
    time.sleep(0.3)

    assert dispatched == ["Erster Satz"]

    # No new interim — cap should not re-dispatch
    time.sleep(0.3)
    assert dispatched == ["Erster Satz"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_silence_timeout_configured(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_config_instance = MagicMock()
    mock_config_class.return_value = mock_config_instance
    mock_recognizer_class.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession(
        speech_key="k", speech_region="r",
        on_text=lambda t: None,
        silence_timeout_ms=1500,
    )

    import azure.cognitiveservices.speech as speechsdk
    mock_config_instance.set_property.assert_any_call(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "1500"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_stt.py -v
```

Expected: FAIL — `STTSession` constructor doesn't accept `time_cap_s` or `silence_timeout_ms`.

- [ ] **Step 3: Rewrite `backend/stt.py`**

Replace the entire file:

```python
import threading
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk


class STTSession:
    """Azure Speech Recognizer (de-DE) with recognized-event dispatch.

    Dispatches full utterances on `recognized` events. A configurable time cap
    forces dispatch of interim text if no recognized event fires within the cap.
    """

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_text: Callable[[str], None],
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 4.0,
    ):
        self._on_text = on_text
        self._time_cap_s = time_cap_s
        self._lock = threading.Lock()
        self._interim_text = ""
        self._cap_timer: Optional[threading.Timer] = None

        self._push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_recognition_language = "de-DE"
        config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(silence_timeout_ms),
        )

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )
        self._recognizer.recognizing.connect(self._on_recognizing)
        self._recognizer.recognized.connect(self._on_recognized)

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._cap_timer is None:
                self._cap_timer = threading.Timer(self._time_cap_s, self._on_cap_timeout)
                self._cap_timer.daemon = True
                self._cap_timer.start()

    def _on_cap_timeout(self) -> None:
        with self._lock:
            text = self._interim_text
            self._interim_text = ""
            self._cap_timer = None
        if text.strip():
            self._on_text(text)

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
            self._interim_text = ""
        text = evt.result.text
        if text.strip():
            self._on_text(text)

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        with self._lock:
            if self._cap_timer is not None:
                self._cap_timer.cancel()
                self._cap_timer = None
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_stt.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/stt.py tests/backend/test_stt.py
git commit -m "feat: STTSession — recognized-event dispatch with configurable time cap and silence timeout"
```

---

## Task 3: LLMTranslator — combined clean + translate with context window

**Files:**
- Create: `backend/llm_translator.py`
- Create: `tests/backend/test_llm_translator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_llm_translator.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_response(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_clean_de_and_en_text(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_de": "Das ist gut", "en_text": "That is good"}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("Ähm das ist gut")

    assert result == {"clean_de": "Das ist gut", "en_text": "That is good"}


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_empty_input_returns_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("   ")

    assert result == {"clean_de": "", "en_text": ""}
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_builds_context_window(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_de": "Satz eins", "en_text": "Sentence one"}'),
        _make_mock_response('{"clean_de": "Satz zwei", "en_text": "Sentence two"}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", context_window=5)

    await translator.translate("Satz eins")
    await translator.translate("Ähm Satz zwei")

    # Second call should include first utterance as context
    second_call = mock_client.chat.completions.create.call_args_list[1]
    messages = second_call.kwargs["messages"]
    user_msg = messages[-1]["content"]
    assert "Satz eins" in user_msg
    assert "Sentence one" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_context_window_limited(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", context_window=2)

    for i in range(3):
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                json.dumps({"clean_de": f"Satz {i}", "en_text": f"Sentence {i}"})
            )
        )
        await translator.translate(f"Satz {i}")

    # After 3 translations with window=2, only last 2 should be in context
    assert len(translator._context) == 2
    assert translator._context[0] == ("Satz 1", "Sentence 1")
    assert translator._context[1] == ("Satz 2", "Sentence 2")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_raises_on_api_error(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")

    with pytest.raises(Exception, match="timeout"):
        await translator.translate("Das ist gut")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_error_does_not_update_context(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")

    try:
        await translator.translate("Das ist gut")
    except Exception:
        pass

    assert len(translator._context) == 0


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_all_filler_returns_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_de": "", "en_text": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("Ähm äh")

    assert result == {"clean_de": "", "en_text": ""}
    # Empty result should not be added to context
    assert len(translator._context) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_llm_translator.py -v
```

Expected: FAIL — `backend.llm_translator` doesn't exist.

- [ ] **Step 3: Create `backend/llm_translator.py`**

```python
import json
from collections import deque
from typing import Tuple

from openai import AsyncAzureOpenAI

_SYSTEM_PROMPT = """\
You process live German sermon transcript for real-time translation.

Clean the new chunk: remove spoken fillers (ähm, äh, hm, also/ja/ne/sozusagen/\
irgendwie/halt when used as fillers), false starts, and immediately repeated words.
Then translate to natural, fluent English. Preserve theological vocabulary.

Return JSON only: {"clean_de": "...", "en_text": "..."}
If the entire input is filler or empty, return: {"clean_de": "", "en_text": ""}\
"""


class LLMTranslator:
    """Cleans and translates German text in a single GPT-4o mini call.

    Maintains a rolling context window of recent utterances for coherent translation.
    Raises on API failure so the caller can fall back to raw text.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        context_window: int = 5,
    ):
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2024-08-01-preview",
        )
        self._deployment = deployment
        self._context: deque[Tuple[str, str]] = deque(maxlen=context_window)

    def _build_user_message(self, raw_de: str) -> str:
        parts = []
        if self._context:
            parts.append("Recent context (for reference only — do NOT re-translate):")
            for i, (de, en) in enumerate(self._context, 1):
                parts.append(f'[{i}] "{de}" → "{en}"')
            parts.append("")
        parts.append("New chunk to process:")
        parts.append(f'"{raw_de}"')
        return "\n".join(parts)

    async def translate(self, raw_de: str) -> dict:
        if not raw_de.strip():
            return {"clean_de": "", "en_text": ""}

        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_message(raw_de)},
            ],
            temperature=0,
            max_tokens=max(128, len(raw_de.split()) * 6),
            response_format={"type": "json_object"},
            timeout=3.0,
        )

        result = json.loads(response.choices[0].message.content.strip())
        clean_de = result.get("clean_de", "")
        en_text = result.get("en_text", "")

        if clean_de:
            self._context.append((clean_de, en_text))

        return {"clean_de": clean_de, "en_text": en_text}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_llm_translator.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/llm_translator.py tests/backend/test_llm_translator.py
git commit -m "feat: LLMTranslator — combined clean+translate with rolling context window"
```

---

## Task 4: TTSSynthesizer — streaming via `synthesizing` event

**Files:**
- Modify: `backend/tts.py`
- Rewrite: `tests/backend/test_tts.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/backend/test_tts.py` entirely:

```python
from unittest.mock import MagicMock, patch, call
import azure.cognitiveservices.speech as speechsdk


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_connects_synthesizing_event(mock_config, mock_synth_class):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello", lambda c: None)

    mock_synth.synthesizing.connect.assert_called_once()
    mock_synth.synthesizing.disconnect_all.assert_called_once()


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_streams_chunks_via_event(mock_config, mock_synth_class):
    chunks_received = []
    chunk_a = b"\x01\x02\x03"
    chunk_b = b"\x04\x05\x06"

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result

    # Capture the callback registered via synthesizing.connect
    registered_callback = None

    def capture_connect(cb):
        nonlocal registered_callback
        registered_callback = cb

    mock_synth.synthesizing.connect.side_effect = capture_connect

    # When speak_text_async().get() is called, simulate synthesizing events
    def simulate_synthesis():
        evt_a = MagicMock()
        evt_a.result.audio_data = chunk_a
        evt_b = MagicMock()
        evt_b.result.audio_data = chunk_b
        registered_callback(evt_a)
        registered_callback(evt_b)
        return mock_result

    mock_synth.speak_text_async.return_value.get.side_effect = simulate_synthesis

    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello world", chunks_received.append)

    assert chunks_received == [chunk_a, chunk_b]


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_skips_empty_audio_data(mock_config, mock_synth_class):
    chunks_received = []

    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result

    registered_callback = None

    def capture_connect(cb):
        nonlocal registered_callback
        registered_callback = cb

    mock_synth.synthesizing.connect.side_effect = capture_connect

    def simulate_synthesis():
        evt = MagicMock()
        evt.result.audio_data = b""  # empty
        registered_callback(evt)
        return mock_result

    mock_synth.speak_text_async.return_value.get.side_effect = simulate_synthesis
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")
    synth.synthesize("Hello", chunks_received.append)

    assert chunks_received == []


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_raises_on_failure(mock_config, mock_synth_class):
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.Canceled
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth.synthesizing.connect.side_effect = lambda cb: None
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    import pytest
    with pytest.raises(RuntimeError, match="TTS failed"):
        synth.synthesize("Hello", lambda c: None)


@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_andrew_neural_voice(mock_config, mock_synth_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth.synthesizing.connect.side_effect = lambda cb: None
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    assert mock_config_instance.speech_synthesis_voice_name == "en-US-AndrewNeural"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_tts.py -v
```

Expected: FAIL — current `synthesize()` doesn't connect to `synthesizing` event.

- [ ] **Step 3: Update `backend/tts.py`**

Replace the entire file:

```python
from typing import Callable
import azure.cognitiveservices.speech as speechsdk

_VOICE = "en-US-AndrewNeural"


class TTSSynthesizer:
    """Synthesizes English text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Streams audio chunks via the synthesizing event as they're generated.
    """

    def __init__(self, speech_key: str, speech_region: str):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_synthesis_voice_name = _VOICE
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        )
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

    def synthesize(self, text: str, on_audio_chunk: Callable[[bytes], None]) -> None:
        def on_synthesizing(evt):
            if evt.result.audio_data:
                on_audio_chunk(evt.result.audio_data)

        self._synthesizer.synthesizing.connect(on_synthesizing)
        try:
            result = self._synthesizer.speak_text_async(text).get()
            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                raise RuntimeError(f"TTS failed: {result.reason}")
        finally:
            self._synthesizer.synthesizing.disconnect_all()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_tts.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/tts.py tests/backend/test_tts.py
git commit -m "feat: TTSSynthesizer — stream audio via synthesizing event instead of post-hoc chunking"
```

---

## Task 5: SessionHandler — new pipeline orchestration

**Files:**
- Modify: `backend/session.py`
- Rewrite: `tests/backend/test_session.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/backend/test_session.py` entirely:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_has_unique_id(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler

    def make():
        return SessionHandler(
            speech_key="sk", speech_region="r", pubsub_cs="cs",
            openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
            loop=loop,
        )

    s1, s2 = make(), make()
    assert s1.session_id != s2.session_id
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_listener_token_comes_from_pubsub(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub.get_listener_token.return_value = "wss://tok"
    mock_pub_class.return_value = mock_pub
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
    )
    assert handler.listener_token == "wss://tok"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_write_audio_forwards_to_stt_session(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
    )
    handler.write(b"\xde\xad\xbe\xef")
    mock_stt.write.assert_called_once_with(b"\xde\xad\xbe\xef")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_sends_phrase_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_de": "Der Herr ist gut.", "en_text": "The Lord is good."})

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
        on_status=capture_status,
    )

    loop.run_until_complete(handler._process_chunk("Ähm, der Herr ist gut."))

    phrase_msgs = [m for m in statuses if m.get("type") == "phrase"]
    assert len(phrase_msgs) == 1
    assert phrase_msgs[0]["raw_de"] == "Ähm, der Herr ist gut."
    assert phrase_msgs[0]["clean_de"] == "Der Herr ist gut."
    assert phrase_msgs[0]["en_text"] == "The Lord is good."
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_tts_for_empty_result(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_de": "", "en_text": ""})

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
    )
    loop.run_until_complete(handler._process_chunk("Ähm"))

    mock_tts.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_falls_back_on_llm_error(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(side_effect=Exception("timeout"))

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
        on_status=capture_status,
    )
    loop.run_until_complete(handler._process_chunk("Der Herr ist gut."))

    fallback_msgs = [m for m in statuses if m.get("type") == "llm_fallback"]
    assert len(fallback_msgs) == 1
    assert fallback_msgs[0]["chunk"] == "Der Herr ist gut."

    # Fallback still sends raw text to TTS
    mock_tts_class.return_value.synthesize.assert_called_once()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_publishes_audio_directly(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_de": "Gut", "en_text": "Good"})

    # Simulate TTS calling on_chunk with audio data
    def fake_synthesize(text, on_chunk):
        on_chunk(b"\x01\x02")
        on_chunk(b"\x03\x04")

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize
    mock_tts_class.return_value = mock_tts

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        loop=loop,
    )
    loop.run_until_complete(handler._process_chunk("Gut"))

    # Audio published directly from TTS callback
    assert mock_pub.publish_audio.call_count == 2
    mock_pub.publish_audio.assert_any_call(handler.session_id, b"\x01\x02")
    mock_pub.publish_audio.assert_any_call(handler.session_id, b"\x03\x04")
    loop.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_session.py -v
```

Expected: FAIL — `SessionHandler` still imports `LLMCleaner`, `TextTranslator`, expects old params.

- [ ] **Step 3: Update `backend/session.py`**

Replace the entire file:

```python
import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from backend.stt import STTSession
from backend.llm_translator import LLMTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates STT → LLM clean+translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 4.0,
        context_window: int = 5,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        on_status: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.session_id = str(uuid.uuid4())
        if loop is None:
            raise TypeError(
                "SessionHandler requires an explicit event loop. "
                "Pass the running loop via loop=asyncio.get_running_loop()."
            )
        self._loop = loop
        self._on_status = on_status
        self.listener_count = 0
        self._tts_lock = asyncio.Lock()

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._llm_translator = LLMTranslator(
            openai_endpoint, openai_api_key, openai_deployment,
            context_window=context_window,
        )
        self._tts = TTSSynthesizer(speech_key, speech_region)
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            silence_timeout_ms=silence_timeout_ms,
            time_cap_s=time_cap_s,
        )

    def _on_text(self, raw_de: str) -> None:
        """Called from STTSession recognized/cap thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_de), self._loop
        )

    async def _process_chunk(self, raw_de: str) -> None:
        try:
            result = await self._llm_translator.translate(raw_de)
            clean_de = result["clean_de"]
            en_text = result["en_text"]
        except Exception:
            clean_de = raw_de
            en_text = raw_de
            await self._send_status({"type": "llm_fallback", "chunk": raw_de})

        if not en_text:
            return

        await self._send_status({
            "type": "phrase",
            "raw_de": raw_de,
            "clean_de": clean_de,
            "en_text": en_text,
        })

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_phrase(self.session_id, en_text),
        )

        async with self._tts_lock:
            try:
                def on_chunk(audio_bytes: bytes) -> None:
                    self._publisher.publish_audio(self.session_id, audio_bytes)

                await loop.run_in_executor(
                    None,
                    lambda: self._tts.synthesize(en_text, on_chunk),
                )
            except Exception as exc:
                await self._send_status({"type": "tts_error", "error": str(exc)})

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except Exception:
                pass

    def listener_join(self) -> int:
        self.listener_count += 1
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def listener_leave(self) -> int:
        self.listener_count = max(0, self.listener_count - 1)
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": self.listener_count}),
            self._loop,
        )
        return self.listener_count

    def start(self) -> None:
        self._stt.start()

    def write(self, audio_bytes: bytes) -> None:
        self._stt.write(audio_bytes)

    def stop(self) -> None:
        self._stt.stop()
        self._publisher.send_close(self.session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_session.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/session.py tests/backend/test_session.py
git commit -m "feat: SessionHandler — new pipeline with LLMTranslator and direct audio publishing"
```

---

## Task 6: main.py — pass new config fields

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update the `SessionHandler` constructor call in `backend/main.py`**

Replace lines 73-85 (the `handler = SessionHandler(...)` block) with:

```python
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
```

- [ ] **Step 2: Run all tests to verify nothing broke**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_main.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
cd ~/gibberly && git add backend/main.py
git commit -m "feat: main.py — pass new config fields to SessionHandler"
```

---

## Task 7: Delete old modules and tests

**Files:**
- Delete: `backend/llm_cleaner.py`
- Delete: `backend/text_translator.py`
- Delete: `tests/backend/test_llm_cleaner.py`
- Delete: `tests/backend/test_text_translator.py`

- [ ] **Step 1: Delete the files**

```bash
cd ~/gibberly && rm backend/llm_cleaner.py backend/text_translator.py tests/backend/test_llm_cleaner.py tests/backend/test_text_translator.py
```

- [ ] **Step 2: Run full test suite**

```bash
cd ~/gibberly && python -m pytest tests/ -v
```

Expected: all pass (no imports from deleted modules remain).

- [ ] **Step 3: Commit**

```bash
cd ~/gibberly && git add -u backend/llm_cleaner.py backend/text_translator.py tests/backend/test_llm_cleaner.py tests/backend/test_text_translator.py
git commit -m "chore: delete old llm_cleaner, text_translator, and their tests"
```

---

## Task 8: Operator console — display raw_de / clean_de / en_text

**Files:**
- Modify: `operator/app.js`

- [ ] **Step 1: Update `handleStatusMessage` in `operator/app.js`**

In `operator/app.js`, replace lines 145-148 (the `phrase` handler inside `handleStatusMessage`):

```javascript
    if (msg.type === 'phrase') {
      lastPhraseEl.textContent = `"${msg.text}"`;
      if (msg.raw_de) console.log(`[gibberly] raw:   ${msg.raw_de}`);
      if (msg.clean_de) console.log(`[gibberly] clean: ${msg.clean_de}`);
```

with:

```javascript
    if (msg.type === 'phrase') {
      const en = msg.en_text || msg.text || '';
      const parts = [];
      if (msg.raw_de) parts.push(`raw: ${msg.raw_de}`);
      if (msg.clean_de) parts.push(`clean: ${msg.clean_de}`);
      parts.push(`en: ${en}`);
      lastPhraseEl.innerHTML = parts.map(p => `<div>${p}</div>`).join('');
      if (msg.raw_de) console.log(`[gibberly] raw:   ${msg.raw_de}`);
      if (msg.clean_de) console.log(`[gibberly] clean: ${msg.clean_de}`);
      if (en) console.log(`[gibberly] en:    ${en}`);
```

Also remove the `translator_error` handler (lines 151-152) since there's no longer a separate translator:

```javascript
    } else if (msg.type === 'translator_error') {
      console.error(`[gibberly] Translator failed — chunk: ${msg.chunk}`);
```

Replace it with nothing (just remove those two lines).

- [ ] **Step 2: Commit**

```bash
cd ~/gibberly && git add operator/app.js
git commit -m "feat: operator console — display raw_de, clean_de, en_text in phrase view"
```

---

## Task 9: Update requirements.txt, .env.example, azure-setup.md

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `docs/azure-setup.md`

- [ ] **Step 1: Remove `httpx` from `requirements.txt`**

In `requirements.txt`, remove the line:

```
httpx==0.27.0
```

Note: `httpx` is still listed under `# Testing` but it's used by the test suite for ASGI transport. Check if `tests/backend/test_main.py` imports it — yes it does (`from httpx import AsyncClient`). So **keep `httpx` in the Testing section** and only remove it if it appears elsewhere. Looking at the current file, `httpx==0.27.0` is under `# Testing` already, so **no change needed to requirements.txt**.

- [ ] **Step 2: Update `.env.example`**

Replace the entire file:

```
AZURE_SPEECH_KEY=your_speech_key_here
AZURE_SPEECH_REGION=westeurope
AZURE_WEBPUBSUB_CONNECTION_STRING=Endpoint=https://...

# Azure OpenAI (GPT-4o mini — cleaning + translation)
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=your_openai_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# STT tuning (optional — defaults shown)
# STT_SILENCE_TIMEOUT_MS=1000
# STT_TIME_CAP_S=4.0
# LLM_CONTEXT_WINDOW=5

BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

# Operator console — used by operator/serve.py to generate config.js
# Local dev:  ws://localhost:8000
# Azure:      wss://gibberly-backend.azurewebsites.net
GIBBERLY_BACKEND=ws://localhost:8000
OPERATOR_PORT=9000
```

- [ ] **Step 3: Update `docs/azure-setup.md`**

Remove Section 4 ("Create an Azure Translator Resource") entirely — lines 66-78.

In Section 6, update the `az webapp config appsettings set` command (lines 138-152) to remove the translator env vars. Replace with:

```bash
az webapp config appsettings set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --settings \
    AZURE_SPEECH_KEY="<KEY 1 from Speech resource>" \
    AZURE_SPEECH_REGION="westeurope" \
    AZURE_WEBPUBSUB_CONNECTION_STRING="<connection string from Web PubSub>" \
    AZURE_OPENAI_ENDPOINT="<endpoint from Azure OpenAI resource>" \
    AZURE_OPENAI_API_KEY="<KEY 1 from Azure OpenAI resource>" \
    AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini" \
    BACKEND_HOST="0.0.0.0" \
    BACKEND_PORT="8000"
```

Update the intro text (line 3) from "You need three things: **Speech** resource (STT + translation + TTS), **Web PubSub** resource…" to "You need three things: **Speech** resource (STT + TTS), **Web PubSub** resource (relay audio to listeners), and **Azure OpenAI** (cleaning + translation)."

In the Cost table, remove the Translator row if present, and add Azure OpenAI:

```
| Azure OpenAI (GPT-4o mini) | Pay-per-use | ~$0.50 per sermon hour |
```

- [ ] **Step 4: Run full test suite**

```bash
cd ~/gibberly && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add .env.example docs/azure-setup.md
git commit -m "docs: update env example and azure setup — remove Translator, add tuning vars"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd ~/gibberly && python -m pytest tests/ -v
```

Expected: all pass, no warnings about missing modules.

- [ ] **Step 2: Verify no stale imports**

```bash
cd ~/gibberly && grep -r "llm_cleaner\|text_translator\|TextTranslator\|LLMCleaner\|translator_key\|translator_region\|chunk_interval\|stt_chunk_interval" backend/ tests/ --include="*.py"
```

Expected: no matches.

- [ ] **Step 3: Commit any remaining cleanup**

If grep found stale references, fix them and commit. Otherwise, no action needed.
