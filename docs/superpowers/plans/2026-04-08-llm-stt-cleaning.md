# LLM STT Cleaning Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the integrated Azure `TranslationRecognizer` with a four-stage pipeline: STT (de-DE) → LLM filler cleaning (Azure OpenAI GPT-4o mini) → text translation (Azure Translator) → TTS (Azure Speech SDK), giving clean English audio to listeners and full text visibility on the operator console.

**Architecture:** `STTSession` dispatches raw German text chunks every ~1.5 s from `recognizing` interim results. `LLMCleaner` strips fillers via GPT-4o mini. `TextTranslator` calls Azure Translator REST API. `TTSSynthesizer` streams audio chunks from `SpeechSynthesizer`. `SessionHandler` orchestrates the async chain.

**Tech Stack:** Python 3.13, FastAPI, `azure-cognitiveservices-speech`, `openai>=1.30` (Azure OpenAI), `httpx` (Translator REST), `pytest`, `unittest.mock`

**Spec:** `docs/superpowers/specs/2026-04-08-llm-stt-cleaning-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/config.py` | Modify | Add new env var fields |
| `backend/stt.py` | Create | `STTSession` — de-DE recognizer with timer chunking |
| `backend/llm_cleaner.py` | Create | `LLMCleaner` — GPT-4o mini filler removal |
| `backend/text_translator.py` | Create | `TextTranslator` — Azure Translator REST de→en |
| `backend/tts.py` | Create | `TTSSynthesizer` — streaming Azure TTS |
| `backend/session.py` | Modify | Orchestrate new pipeline, replace TranslationSession |
| `backend/main.py` | Modify | Pass new config fields to SessionHandler |
| `backend/translation.py` | Delete | Replaced by stt.py |
| `operator/app.js` | Modify | Display raw_de / clean_de on phrase messages |
| `tests/backend/test_config.py` | Modify | Test new fields |
| `tests/backend/test_stt.py` | Create | Tests for STTSession |
| `tests/backend/test_llm_cleaner.py` | Create | Tests for LLMCleaner |
| `tests/backend/test_text_translator.py` | Create | Tests for TextTranslator |
| `tests/backend/test_tts.py` | Create | Tests for TTSSynthesizer |
| `tests/backend/test_session.py` | Replace | Tests for updated SessionHandler |
| `tests/backend/test_translation.py` | Delete | Covered by test_stt.py |
| `tests/backend/test_main.py` | Modify | Add new env vars to test env dicts |
| `requirements.txt` | Modify | Add `openai>=1.30` |
| `.env.example` | Modify | Add new env var examples |
| `docs/azure-setup.md` | Modify | Add OpenAI + Translator provisioning |

---

## Task 1: Config — new env vars

**Files:**
- Modify: `backend/config.py`
- Modify: `tests/backend/test_config.py`
- Modify: `tests/backend/test_main.py` (add new vars to all `env` dicts)

- [ ] **Step 1: Write failing tests for new config fields**

Add to `tests/backend/test_config.py`:

```python
def test_config_loads_new_azure_fields():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.azure_openai_endpoint == "https://my-openai.openai.azure.com/"
        assert s.azure_openai_api_key == "oai-key"
        assert s.azure_openai_deployment == "gpt-4o-mini"
        assert s.azure_translator_key == "tr-key"
        assert s.azure_translator_region == "westeurope"
        assert s.stt_chunk_interval_s == 1.5  # default


def test_config_chunk_interval_from_env():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
        "STT_CHUNK_INTERVAL_S": "2.0",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.stt_chunk_interval_s == 2.0


def test_config_raises_on_missing_openai_endpoint():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            _load()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_config.py -v -k "new_azure or chunk_interval or missing_openai"
```

Expected: FAIL — `Settings` has no `azure_openai_endpoint` field.

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
    azure_translator_key: str
    azure_translator_region: str
    backend_host: str
    backend_port: int
    stt_chunk_interval_s: float


def _load() -> Settings:
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    pubsub_cs = os.environ.get("AZURE_WEBPUBSUB_CONNECTION_STRING")
    openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    translator_key = os.environ.get("AZURE_TRANSLATOR_KEY")
    translator_region = os.environ.get("AZURE_TRANSLATOR_REGION")

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
    if not translator_key:
        raise ValueError("AZURE_TRANSLATOR_KEY is required")
    if not translator_region:
        raise ValueError("AZURE_TRANSLATOR_REGION is required")

    return Settings(
        azure_speech_key=key,
        azure_speech_region=region,
        azure_webpubsub_connection_string=pubsub_cs,
        azure_openai_endpoint=openai_endpoint,
        azure_openai_api_key=openai_api_key,
        azure_openai_deployment=openai_deployment,
        azure_translator_key=translator_key,
        azure_translator_region=translator_region,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
        stt_chunk_interval_s=float(os.environ.get("STT_CHUNK_INTERVAL_S", "1.5")),
    )


settings = _load()
```

- [ ] **Step 4: Add new env vars to all `env` dicts in `tests/backend/test_main.py`**

Every `env` dict in `test_main.py` needs these additional keys. There are 8 occurrences. Add to each one:

```python
"AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
"AZURE_OPENAI_API_KEY": "oai-key",
"AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
"AZURE_TRANSLATOR_KEY": "tr-key",
"AZURE_TRANSLATOR_REGION": "westeurope",
```

The module-level `env` dict at the top of `test_main.py` (lines 4-8) and each `env` dict inside individual test functions all need these added.

- [ ] **Step 5: Run config and main tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_config.py tests/backend/test_main.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd ~/gibberly && git add backend/config.py tests/backend/test_config.py tests/backend/test_main.py
git commit -m "feat: config — add Azure OpenAI, Translator, and STT chunk interval fields"
```

---

## Task 2: STTSession

**Files:**
- Create: `backend/stt.py`
- Create: `tests/backend/test_stt.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_stt.py`:

```python
import threading
from unittest.mock import MagicMock, patch, call


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
def test_stt_dispatch_sends_new_words_only(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # Simulate recognizing event with 3 words
    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)

    # First dispatch sends all 3 words
    session._dispatch()
    assert dispatched == ["Das ist gut"]

    # More words arrive in next interim result
    evt2 = MagicMock()
    evt2.result.text = "Das ist gut und schön"
    session._on_recognizing(evt2)

    session._dispatch()
    assert dispatched == ["Das ist gut", "und schön"]


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_recognized_flushes_remaining_words(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    import azure.cognitiveservices.speech as speechsdk
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # 2 words already dispatched (cursor at 2)
    evt = MagicMock()
    evt.result.text = "Das ist gut"
    session._on_recognizing(evt)
    session._dispatch()  # sends "Das ist gut", cursor=3

    # recognized fires with 5 words total — only last 2 are new
    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.RecognizedSpeech
    final_evt.result.text = "Das ist gut und schön"
    session._on_recognized(final_evt)

    assert dispatched == ["Das ist gut", "und schön"]
    # cursor reset to 0
    assert session._last_word_count == 0


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

    final_evt = MagicMock()
    final_evt.result.reason = speechsdk.ResultReason.NoMatch
    final_evt.result.text = ""
    session._on_recognized(final_evt)

    assert dispatched == []


@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
@patch("backend.stt.speechsdk.SpeechConfig")
def test_stt_dispatch_skips_when_no_new_words(
    mock_config_class, mock_stream_class, mock_audio_config, mock_recognizer_class
):
    mock_recognizer_class.return_value = MagicMock()
    dispatched = []

    from backend.stt import STTSession
    session = STTSession(speech_key="k", speech_region="r", on_text=dispatched.append)

    # dispatch fires but no interim text yet
    session._dispatch()
    assert dispatched == []
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_stt.py -v
```

Expected: FAIL — `backend.stt` does not exist.

- [ ] **Step 3: Create `backend/stt.py`**

```python
import threading
from typing import Callable, Optional
import azure.cognitiveservices.speech as speechsdk


class STTSession:
    """Azure Speech Recognizer (de-DE) with timer-based interim chunking.

    Calls on_text(chunk) with new German words every chunk_interval seconds
    from interim recognizing events, then flushes remaining words on the final
    recognized event.
    """

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        on_text: Callable[[str], None],
        chunk_interval: float = 1.5,
    ):
        self._on_text = on_text
        self._chunk_interval = chunk_interval
        self._lock = threading.Lock()
        self._interim_text = ""
        self._last_word_count = 0
        self._timer: Optional[threading.Timer] = None

        self._push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_recognition_language = "de-DE"
        config.set_property("Speech_SegmentationSilenceTimeoutMs", "500")

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )
        self._recognizer.recognizing.connect(self._on_recognizing)
        self._recognizer.recognized.connect(self._on_recognized)

    def _on_recognizing(self, evt) -> None:
        with self._lock:
            self._interim_text = evt.result.text
            if self._timer is None:
                self._timer = threading.Timer(self._chunk_interval, self._dispatch)
                self._timer.daemon = True
                self._timer.start()

    def _dispatch(self) -> None:
        with self._lock:
            words = self._interim_text.split()
            new_words = words[self._last_word_count:]
            self._last_word_count = len(words)
            self._timer = None
        if new_words:
            self._on_text(" ".join(new_words))

    def _on_recognized(self, evt) -> None:
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            final_words = evt.result.text.split()
            new_words = final_words[self._last_word_count:]
            self._last_word_count = 0
            self._interim_text = ""
        if new_words:
            self._on_text(" ".join(new_words))

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def write(self, audio_bytes: bytes) -> None:
        self._push_stream.write(audio_bytes)

    def stop(self) -> None:
        self._recognizer.stop_continuous_recognition()
        self._push_stream.close()
```

- [ ] **Step 4: Run tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_stt.py -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/stt.py tests/backend/test_stt.py
git commit -m "feat: STTSession — de-DE recognizer with 1.5s timer-based interim chunking"
```

---

## Task 3: LLMCleaner

**Files:**
- Create: `backend/llm_cleaner.py`
- Create: `tests/backend/test_llm_cleaner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_llm_cleaner.py`:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_cleaned_text(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Der Herr ist gut."
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("Ähm, der Herr ist gut."))
    assert result == "Der Herr ist gut."


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_empty_string_for_empty_input(mock_client_class):
    mock_client_class.return_value = MagicMock()

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean(""))
    assert result == ""
    # API must NOT be called for empty input
    mock_client_class.return_value.chat.completions.create.assert_not_called()


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_empty_string_for_whitespace_input(mock_client_class):
    mock_client_class.return_value = MagicMock()

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("   "))
    assert result == ""


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_raises_on_api_error(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    try:
        asyncio.run(cleaner.clean("Test text"))
        assert False, "Expected exception"
    except Exception as e:
        assert "API error" in str(e)


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_strips_whitespace_from_response(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "  Der Herr ist gut.  \n"
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("Ähm, der Herr ist gut."))
    assert result == "Der Herr ist gut."
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_llm_cleaner.py -v
```

Expected: FAIL — `backend.llm_cleaner` does not exist.

- [ ] **Step 3: Install openai package**

```bash
cd ~/gibberly && source .venv/bin/activate && pip install "openai>=1.30"
```

- [ ] **Step 4: Create `backend/llm_cleaner.py`**

```python
from openai import AsyncAzureOpenAI

_SYSTEM_PROMPT = """\
You are processing a live German sermon transcript for real-time translation.
Remove spoken language fillers (ähm, äh, hm, also/ja/ne/sozusagen/irgendwie/halt \
when used as fillers) and clean up false starts or immediately repeated words.
Preserve the meaning, sentence structure, and theological vocabulary exactly.
Return only the cleaned German text — no explanation, no translation.
If the entire input is filler or empty, return an empty string.\
"""


class LLMCleaner:
    """Removes spoken fillers from a German text chunk via Azure OpenAI GPT-4o mini.

    Raises on API failure so the caller can fall back to the raw text.
    """

    def __init__(self, endpoint: str, api_key: str, deployment: str):
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2024-08-01-preview",
        )
        self._deployment = deployment

    async def clean(self, text: str) -> str:
        if not text.strip():
            return ""
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=max(64, len(text.split()) * 3),
            timeout=2.0,
        )
        return response.choices[0].message.content.strip()
```

- [ ] **Step 5: Run tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_llm_cleaner.py -v
```

Expected: all 5 pass.

- [ ] **Step 6: Commit**

```bash
cd ~/gibberly && git add backend/llm_cleaner.py tests/backend/test_llm_cleaner.py
git commit -m "feat: LLMCleaner — Azure OpenAI GPT-4o mini filler removal for German sermon STT"
```

---

## Task 4: TextTranslator

**Files:**
- Create: `backend/text_translator.py`
- Create: `tests/backend/test_text_translator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_text_translator.py`:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


def _make_translator():
    from backend.text_translator import TextTranslator
    return TextTranslator("tr-key", "westeurope")


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_english_text(mock_client_class):
    mock_response = MagicMock()
    mock_response.json.return_value = [{"translations": [{"text": "God is good."}]}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    result = asyncio.run(translator.translate("Gott ist gut."))
    assert result == "God is good."


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_for_empty_input(mock_client_class):
    translator = _make_translator()
    result = asyncio.run(translator.translate(""))
    assert result is None
    mock_client_class.assert_not_called()


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_for_whitespace_input(mock_client_class):
    translator = _make_translator()
    result = asyncio.run(translator.translate("   "))
    assert result is None
    mock_client_class.assert_not_called()


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_on_http_error(mock_client_class):
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    result = asyncio.run(translator.translate("Gott ist gut."))
    assert result is None


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_sends_correct_headers(mock_client_class):
    mock_response = MagicMock()
    mock_response.json.return_value = [{"translations": [{"text": "God is good."}]}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    asyncio.run(translator.translate("Gott ist gut."))

    call_kwargs = mock_client.post.call_args
    headers = call_kwargs.kwargs["headers"]
    assert headers["Ocp-Apim-Subscription-Key"] == "tr-key"
    assert headers["Ocp-Apim-Subscription-Region"] == "westeurope"
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_text_translator.py -v
```

Expected: FAIL — `backend.text_translator` does not exist.

- [ ] **Step 3: Create `backend/text_translator.py`**

```python
from typing import Optional
import httpx

_TRANSLATOR_ENDPOINT = "https://api.cognitive.microsofttranslator.com"


class TextTranslator:
    """Translates German text to English via Azure Cognitive Services Translator REST API.

    Returns None for empty input or on API failure — caller skips TTS in those cases.
    """

    def __init__(
        self,
        api_key: str,
        region: str,
        endpoint: str = _TRANSLATOR_ENDPOINT,
    ):
        self._api_key = api_key
        self._region = region
        self._endpoint = endpoint

    async def translate(self, text: str) -> Optional[str]:
        if not text.strip():
            return None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._endpoint}/translate",
                    params={"api-version": "3.0", "from": "de", "to": "en"},
                    headers={
                        "Ocp-Apim-Subscription-Key": self._api_key,
                        "Ocp-Apim-Subscription-Region": self._region,
                        "Content-Type": "application/json",
                    },
                    json=[{"text": text}],
                    timeout=5.0,
                )
                response.raise_for_status()
                data = response.json()
                return data[0]["translations"][0]["text"]
        except Exception:
            return None
```

- [ ] **Step 4: Run tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_text_translator.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/text_translator.py tests/backend/test_text_translator.py
git commit -m "feat: TextTranslator — Azure Cognitive Services Translator de→en REST client"
```

---

## Task 5: TTSSynthesizer

**Files:**
- Create: `backend/tts.py`
- Create: `tests/backend/test_tts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_tts.py`:

```python
from unittest.mock import MagicMock, patch


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_streams_audio_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth

    mock_result = MagicMock()
    mock_future = MagicMock()
    mock_future.get.return_value = mock_result
    mock_synth.start_speaking_text_async.return_value = mock_future

    # read_data fills buffer with 4 bytes first call, returns 0 second call
    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    call_count = 0

    def fake_read(buf):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            buf[:4] = bytearray([0xFF, 0xFE, 0x00, 0x01])
            return 4
        return 0

    mock_stream.read_data.side_effect = fake_read

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("God is good.", chunks.append)

    assert len(chunks) == 1
    assert chunks[0] == bytes([0xFF, 0xFE, 0x00, 0x01])


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_emits_multiple_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth
    mock_future = MagicMock()
    mock_future.get.return_value = MagicMock()
    mock_synth.start_speaking_text_async.return_value = mock_future

    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    call_count = 0

    def fake_read(buf):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            buf[:2] = bytearray([call_count, call_count])
            return 2
        return 0

    mock_stream.read_data.side_effect = fake_read

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert len(chunks) == 3
    assert chunks[0] == bytes([1, 1])
    assert chunks[1] == bytes([2, 2])
    assert chunks[2] == bytes([3, 3])


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_empty_stream_emits_no_chunks(mock_config, mock_synth_class, mock_stream_class):
    mock_synth = MagicMock()
    mock_synth_class.return_value = mock_synth
    mock_future = MagicMock()
    mock_future.get.return_value = MagicMock()
    mock_synth.start_speaking_text_async.return_value = mock_future

    mock_stream = MagicMock()
    mock_stream_class.return_value = mock_stream
    mock_stream.read_data.return_value = 0  # immediately empty

    from backend.tts import TTSSynthesizer
    synth = TTSSynthesizer("key", "westeurope")

    chunks = []
    synth.synthesize("Hello", chunks.append)

    assert chunks == []


@patch("backend.tts.speechsdk.AudioDataStream")
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_andrew_neural_voice(mock_config, mock_synth_class, mock_stream_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth_class.return_value = MagicMock()
    mock_synth_class.return_value.start_speaking_text_async.return_value.get.return_value = MagicMock()
    mock_stream_class.return_value.read_data.return_value = 0

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope")

    mock_config_instance.speech_synthesis_voice_name = "en-US-AndrewNeural"
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_tts.py -v
```

Expected: FAIL — `backend.tts` does not exist.

- [ ] **Step 3: Create `backend/tts.py`**

```python
from typing import Callable
import azure.cognitiveservices.speech as speechsdk

_VOICE = "en-US-AndrewNeural"
_CHUNK_SIZE = 4096


class TTSSynthesizer:
    """Synthesizes English text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Calls on_audio_chunk(bytes) with each chunk as synthesis streams.
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
        result_future = self._synthesizer.start_speaking_text_async(text)
        result = result_future.get()
        audio_stream = speechsdk.AudioDataStream(result)
        buffer = bytearray(_CHUNK_SIZE)
        while True:
            filled = audio_stream.read_data(buffer)
            if filled == 0:
                break
            on_audio_chunk(bytes(buffer[:filled]))
```

- [ ] **Step 4: Run tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_tts.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
cd ~/gibberly && git add backend/tts.py tests/backend/test_tts.py
git commit -m "feat: TTSSynthesizer — streaming Azure TTS via start_speaking_text_async"
```

---

## Task 6: SessionHandler + main.py + operator console

**Files:**
- Modify: `backend/session.py` (full replacement)
- Modify: `backend/main.py`
- Modify: `operator/app.js`
- Replace: `tests/backend/test_session.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/backend/test_session.py` entirely:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def _make_handler(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class,
                  on_status=None):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "wss://pubsub.example.com/token123"

    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk",
        speech_region="westeurope",
        pubsub_cs="cs",
        openai_endpoint="https://ep.openai.azure.com/",
        openai_api_key="oai-key",
        openai_deployment="gpt-4o-mini",
        translator_key="tr-key",
        translator_region="westeurope",
        loop=loop,
        on_status=on_status,
    )
    return handler, loop, mock_pub, mock_stt, mock_llm, mock_tr, mock_tts


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_has_unique_id(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler

    def make():
        return SessionHandler(
            speech_key="sk", speech_region="r", pubsub_cs="cs",
            openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
            translator_key="tk", translator_region="r",
            loop=loop,
        )

    s1, s2 = make(), make()
    assert s1.session_id != s2.session_id
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_listener_token_comes_from_pubsub(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub.get_listener_token.return_value = "wss://tok"
    mock_pub_class.return_value = mock_pub
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    assert handler.listener_token == "wss://tok"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id)
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_write_audio_forwards_to_stt_session(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt = MagicMock()
    mock_stt_class.return_value = mock_stt
    mock_llm_class.return_value = MagicMock()
    mock_tr_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    handler.write(b"\xde\xad\xbe\xef")
    mock_stt.write.assert_called_once_with(b"\xde\xad\xbe\xef")
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_sends_phrase_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(return_value="Der Herr ist gut.")

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr
    mock_tr.translate = AsyncMock(return_value="The Lord is good.")

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
        on_status=capture_status,
    )

    loop.run_until_complete(handler._process_chunk("Ähm, der Herr ist gut."))

    phrase_msgs = [m for m in statuses if m.get("type") == "phrase"]
    assert len(phrase_msgs) == 1
    assert phrase_msgs[0]["raw_de"] == "Ähm, der Herr ist gut."
    assert phrase_msgs[0]["clean_de"] == "Der Herr ist gut."
    assert phrase_msgs[0]["text"] == "The Lord is good."
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_tts_for_empty_clean(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(return_value="")  # all-filler chunk

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr

    loop = asyncio.new_event_loop()
    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
    )
    loop.run_until_complete(handler._process_chunk("Ähm"))

    mock_tr.translate.assert_not_called()
    mock_tts.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.TextTranslator")
@patch("backend.session.LLMCleaner")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_falls_back_on_llm_error(mock_pub_class, mock_stt_class, mock_llm_class, mock_tr_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()
    mock_tts_class.return_value.synthesize = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.clean = AsyncMock(side_effect=Exception("timeout"))

    mock_tr = MagicMock()
    mock_tr_class.return_value = mock_tr
    mock_tr.translate = AsyncMock(return_value="The Lord is good.")

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    from backend.session import SessionHandler
    handler = SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        translator_key="tk", translator_region="r",
        loop=loop,
        on_status=capture_status,
    )
    loop.run_until_complete(handler._process_chunk("Der Herr ist gut."))

    # fallback status emitted
    fallback_msgs = [m for m in statuses if m.get("type") == "llm_fallback"]
    assert len(fallback_msgs) == 1
    assert fallback_msgs[0]["chunk"] == "Der Herr ist gut."

    # translator still called with raw text (fallback)
    mock_tr.translate.assert_called_once_with("Der Herr ist gut.")
    loop.close()
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_session.py -v
```

Expected: several FAIL — `SessionHandler` has wrong constructor signature.

- [ ] **Step 3: Replace `backend/session.py`**

```python
import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from backend.stt import STTSession
from backend.llm_cleaner import LLMCleaner
from backend.text_translator import TextTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher


class SessionHandler:
    """Orchestrates STT → LLM clean → translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        translator_key: str,
        translator_region: str,
        chunk_interval: float = 1.5,
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

        self._publisher = PubSubPublisher(pubsub_cs)
        self.listener_token = self._publisher.get_listener_token(self.session_id)

        self._cleaner = LLMCleaner(openai_endpoint, openai_api_key, openai_deployment)
        self._translator = TextTranslator(translator_key, translator_region)
        self._tts = TTSSynthesizer(speech_key, speech_region)
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            chunk_interval=chunk_interval,
        )

    def _on_text(self, raw_de: str) -> None:
        """Called from STTSession timer/recognized thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_de), self._loop
        )

    async def _process_chunk(self, raw_de: str) -> None:
        try:
            clean_de = await self._cleaner.clean(raw_de)
        except Exception:
            clean_de = raw_de
            await self._send_status({"type": "llm_fallback", "chunk": raw_de})

        if not clean_de:
            return

        en_text = await self._translator.translate(clean_de)
        if not en_text:
            return

        await self._send_status({
            "type": "phrase",
            "raw_de": raw_de,
            "clean_de": clean_de,
            "text": en_text,
        })

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_phrase(self.session_id, en_text),
        )
        await loop.run_in_executor(
            None,
            lambda: self._tts.synthesize(
                en_text,
                lambda chunk: asyncio.run_coroutine_threadsafe(
                    self._publish_chunk(chunk), loop
                ),
            ),
        )

    async def _publish_chunk(self, audio_bytes: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._publisher.publish_audio(self.session_id, audio_bytes),
        )

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

- [ ] **Step 4: Update `backend/main.py` — pass new config to SessionHandler**

In the `/ws/stream` endpoint, replace the `SessionHandler(...)` call (lines 73–79) with:

```python
    handler = SessionHandler(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        pubsub_cs=settings.azure_webpubsub_connection_string,
        openai_endpoint=settings.azure_openai_endpoint,
        openai_api_key=settings.azure_openai_api_key,
        openai_deployment=settings.azure_openai_deployment,
        translator_key=settings.azure_translator_key,
        translator_region=settings.azure_translator_region,
        chunk_interval=settings.stt_chunk_interval_s,
        loop=loop,
        on_status=send_status,
    )
```

- [ ] **Step 5: Update `operator/app.js` — show raw_de and clean_de in phrase handler**

In `app.js`, find the `if (msg.type === 'phrase')` block (around line 144) and replace it:

```javascript
    if (msg.type === 'phrase') {
      lastPhraseEl.textContent = `"${msg.text}"`;
      if (msg.raw_de) console.log(`[gibberly] raw:   ${msg.raw_de}`);
      if (msg.clean_de) console.log(`[gibberly] clean: ${msg.clean_de}`);
    }
```

- [ ] **Step 6: Run session and main tests**

```bash
cd ~/gibberly && python -m pytest tests/backend/test_session.py tests/backend/test_main.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd ~/gibberly && git add backend/session.py backend/main.py operator/app.js tests/backend/test_session.py
git commit -m "feat: SessionHandler — orchestrate STT→LLM→translate→TTS pipeline"
```

---

## Task 7: Cleanup

**Files:**
- Delete: `backend/translation.py`
- Delete: `tests/backend/test_translation.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete old files**

```bash
cd ~/gibberly && rm backend/translation.py tests/backend/test_translation.py
```

- [ ] **Step 2: Add `openai` to `requirements.txt`**

Add after the `azure-messaging-webpubsubservice` line:

```
openai>=1.30
```

- [ ] **Step 3: Run full test suite**

```bash
cd ~/gibberly && python -m pytest tests/ -v
```

Expected: all tests pass, no references to `backend.translation`.

- [ ] **Step 4: Commit**

```bash
cd ~/gibberly && git add requirements.txt && git rm backend/translation.py tests/backend/test_translation.py
git commit -m "chore: remove TranslationSession, add openai to requirements"
```

---

## Task 8: Docs — .env.example and azure-setup.md

**Files:**
- Modify: `.env.example`
- Modify: `docs/azure-setup.md`

- [ ] **Step 1: Update `.env.example`**

Add after the `AZURE_WEBPUBSUB_CONNECTION_STRING` line:

```bash
# Azure OpenAI (GPT-4o mini — filler cleaning)
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=your_openai_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# Azure Cognitive Services Translator (de→en)
AZURE_TRANSLATOR_KEY=your_translator_key_here
AZURE_TRANSLATOR_REGION=westeurope

# STT chunk interval in seconds (default 1.5)
STT_CHUNK_INTERVAL_S=1.5
```

- [ ] **Step 2: Add Azure OpenAI provisioning section to `docs/azure-setup.md`**

Add a new section (after the existing Web PubSub section, before the App Service section):

```markdown
## 3. Create an Azure OpenAI Resource

1. **Create a resource** → search **Azure OpenAI** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Region**: `West Europe` (must match Speech resource region for lowest latency)
   - **Name**: `gibberly-openai`
   - **Pricing tier**: `S0`
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Keys and Endpoint**.
5. Copy **KEY 1** → `AZURE_OPENAI_API_KEY` and **Endpoint** → `AZURE_OPENAI_ENDPOINT`.

**Deploy the model:**

6. Go to **Azure OpenAI Studio** (link in the resource overview) → **Deployments** → **+ Create**.
7. Select model: `gpt-4o-mini` → Deployment name: `gpt-4o-mini` → **Deploy**.
8. Set `AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini` in `.env`.

---

## 4. Create an Azure Translator Resource

1. **Create a resource** → search **Translator** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Region**: `West Europe`
   - **Name**: `gibberly-translator`
   - **Pricing tier**: `Free F0` (2M chars/month) or `S1` for production
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Keys and Endpoint**.
5. Copy **KEY 1** → `AZURE_TRANSLATOR_KEY`.
   Region is `westeurope` → `AZURE_TRANSLATOR_REGION=westeurope`.

> **Note:** The Translator endpoint is always `https://api.cognitive.microsofttranslator.com` regardless of resource region — no need to copy it.
```

> **Note:** Renumber the existing section "3. Configure a Hub" → "5. Configure a Hub" and "4. Deploy the Backend" → "6. Deploy the Backend" after inserting the new sections above.

- [ ] **Step 3: Commit**

```bash
cd ~/gibberly && git add .env.example docs/azure-setup.md
git commit -m "docs: add Azure OpenAI and Translator provisioning steps, update .env.example"
```

---

## Self-Review Notes

- All spec requirements are covered: STTSession timer chunking ✓, LLMCleaner filler prompt ✓, TextTranslator ✓, TTSSynthesizer streaming ✓, SessionHandler orchestration ✓, operator console phrase enrichment ✓, fallback on LLM error ✓, empty-chunk skip ✓, config new fields ✓, azure-setup.md ✓
- Type consistency: `on_text: Callable[[str], None]` used in STTSession constructor and `_on_text` in SessionHandler ✓; `on_audio_chunk: Callable[[bytes], None]` in TTSSynthesizer.synthesize ✓
- `translate()` returns `Optional[str]` throughout ✓; `clean()` returns `str` and raises on error ✓
