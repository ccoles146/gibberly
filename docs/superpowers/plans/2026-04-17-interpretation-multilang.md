# Interpretation Pipeline + Multi-language Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace literal fragment translation with interpreted natural phrasing, add per-language TTS/listener support with audio opt-in, and add source language selection to the operator console.

**Architecture:** A new `backend/languages.py` defines the language list. `LLMTranslator` expands to return all target language translations in one call plus a `pending` arc note. `SessionHandler` holds one `TTSSynthesizer` per language and only synthesises audio for languages with active audio listeners. The listener page is text-first with an explicit unmute button.

**Tech Stack:** Python/FastAPI backend, Azure Speech SDK, Azure OpenAI (GPT-4o mini), Azure Web PubSub, plain HTML/JS frontend.

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/languages.py` | Create | Canonical language list + helper |
| `backend/stt.py` | Modify | Add `language` constructor param |
| `backend/tts.py` | Modify | Add `voice` constructor param |
| `backend/pubsub.py` | Modify | Lang-scoped groups (`session-{id}-{lang}`) |
| `backend/llm_translator.py` | Modify | Interpretation prompt + multi-lang output + `pending` |
| `backend/session.py` | Modify | Per-language TTS, listener/audio counts |
| `backend/main.py` | Modify | New endpoints, `source_lang` WS query param |
| `backend/config.py` | Modify | `STT_TIME_CAP_S` default 4.0 → 8.0 |
| `listener/index.html` | Modify | Language selector + unmute button |
| `listener/app.js` | Modify | Fetch languages, lang-scoped connect, audio opt-in |
| `operator/index.html` | Modify | Source language selector |
| `operator/app.js` | Modify | Append `source_lang` to WS URL |
| `.env.example` | Modify | Updated comment for `STT_TIME_CAP_S` |
| `tests/backend/test_languages.py` | Create | Tests for language list |
| `tests/backend/test_stt.py` | Modify | Test `language` param |
| `tests/backend/test_tts.py` | Modify | Test `voice` param |
| `tests/backend/test_pubsub.py` | Modify | Update group name assertions |
| `tests/backend/test_llm_translator.py` | Modify | Multi-lang output, `pending`, context |
| `tests/backend/test_session.py` | Modify | Multi-lang session behaviour |
| `tests/backend/test_main.py` | Modify | New endpoints + updated existing |

---

## Task 1: Create feature branch + `backend/languages.py`

**Files:**
- Create: `backend/languages.py`
- Create: `tests/backend/test_languages.py`

- [ ] **Step 1: Create the branch**

```bash
cd /home/chris/gibberly
git checkout -b feature/interpretation-multilang
```

Expected: `Switched to a new branch 'feature/interpretation-multilang'`

- [ ] **Step 2: Write the failing test**

Create `tests/backend/test_languages.py`:

```python
def test_all_languages_have_required_keys():
    from backend.languages import SUPPORTED_LANGUAGES
    for lang in SUPPORTED_LANGUAGES:
        assert "code" in lang
        assert "name" in lang
        assert "voice" in lang
        assert "llm_key" in lang
        assert lang["llm_key"] == f"{lang['code']}_text"


def test_language_count():
    from backend.languages import SUPPORTED_LANGUAGES
    assert len(SUPPORTED_LANGUAGES) == 9


def test_get_target_languages_excludes_source():
    from backend.languages import get_target_languages
    targets = get_target_languages("de")
    codes = [l["code"] for l in targets]
    assert "de" not in codes
    assert "en" in codes


def test_get_target_languages_excludes_english_source():
    from backend.languages import get_target_languages
    targets = get_target_languages("en")
    codes = [l["code"] for l in targets]
    assert "en" not in codes
    assert "de" in codes


def test_get_target_languages_preserves_order():
    from backend.languages import SUPPORTED_LANGUAGES, get_target_languages
    targets = get_target_languages("xx")  # unknown source — all kept
    assert targets == SUPPORTED_LANGUAGES
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd /home/chris/gibberly && source .venv/bin/activate
python -m pytest tests/backend/test_languages.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.languages'`

- [ ] **Step 4: Create `backend/languages.py`**

```python
SUPPORTED_LANGUAGES = [
    {"code": "en", "name": "English",    "voice": "en-US-AndrewNeural",    "llm_key": "en_text"},
    {"code": "de", "name": "German",     "voice": "de-DE-KatjaNeural",     "llm_key": "de_text"},
    {"code": "es", "name": "Spanish",    "voice": "es-ES-ElviraNeural",    "llm_key": "es_text"},
    {"code": "fr", "name": "French",     "voice": "fr-FR-DeniseNeural",    "llm_key": "fr_text"},
    {"code": "hr", "name": "Croatian",   "voice": "hr-HR-GabrijelaNeural", "llm_key": "hr_text"},
    {"code": "pt", "name": "Portuguese", "voice": "pt-BR-FranciscaNeural", "llm_key": "pt_text"},
    {"code": "pl", "name": "Polish",     "voice": "pl-PL-ZofiaNeural",     "llm_key": "pl_text"},
    {"code": "ro", "name": "Romanian",   "voice": "ro-RO-AlinaNeural",     "llm_key": "ro_text"},
    {"code": "uk", "name": "Ukrainian",  "voice": "uk-UA-PolinaNeural",    "llm_key": "uk_text"},
]


def get_target_languages(source_lang_code: str) -> list[dict]:
    """Return SUPPORTED_LANGUAGES excluding the entry matching source_lang_code."""
    return [lang for lang in SUPPORTED_LANGUAGES if lang["code"] != source_lang_code]
```

- [ ] **Step 5: Run tests to confirm passing**

```bash
python -m pytest tests/backend/test_languages.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/languages.py tests/backend/test_languages.py
git commit -m "feat: add language list with get_target_languages helper"
```

---

## Task 2: Update `backend/stt.py` + `backend/tts.py` — add language/voice params

**Files:**
- Modify: `backend/stt.py`
- Modify: `backend/tts.py`
- Modify: `tests/backend/test_stt.py`
- Modify: `tests/backend/test_tts.py`

- [ ] **Step 1: Write failing test for STT language param**

Add to `tests/backend/test_stt.py` (append after existing tests):

```python
@patch("backend.stt.speechsdk.SpeechConfig")
@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
def test_stt_uses_given_language(mock_stream, mock_audio_cfg, mock_recognizer, mock_config):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_recognizer.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession("key", "region", on_text=lambda t: None, language="en-US")

    assert mock_config_instance.speech_recognition_language == "en-US"


@patch("backend.stt.speechsdk.SpeechConfig")
@patch("backend.stt.speechsdk.SpeechRecognizer")
@patch("backend.stt.speechsdk.audio.AudioConfig")
@patch("backend.stt.speechsdk.audio.PushAudioInputStream")
def test_stt_defaults_to_german(mock_stream, mock_audio_cfg, mock_recognizer, mock_config):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_recognizer.return_value = MagicMock()

    from backend.stt import STTSession
    STTSession("key", "region", on_text=lambda t: None)

    assert mock_config_instance.speech_recognition_language == "de-DE"
```

- [ ] **Step 2: Write failing test for TTS voice param**

Add to `tests/backend/test_tts.py` (append after existing tests):

```python
@patch("backend.tts.speechsdk.SpeechSynthesizer")
@patch("backend.tts.speechsdk.SpeechConfig")
def test_synthesize_uses_custom_voice(mock_config, mock_synth_class):
    mock_config_instance = MagicMock()
    mock_config.return_value = mock_config_instance
    mock_synth = MagicMock()
    mock_result = MagicMock()
    mock_result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
    mock_result.audio_data = b"\x00"
    mock_synth.speak_text_async.return_value.get.return_value = mock_result
    mock_synth_class.return_value = mock_synth

    from backend.tts import TTSSynthesizer
    TTSSynthesizer("key", "westeurope", voice="es-ES-ElviraNeural")

    assert mock_config_instance.speech_synthesis_voice_name == "es-ES-ElviraNeural"
```

- [ ] **Step 3: Run to confirm failures**

```bash
python -m pytest tests/backend/test_stt.py tests/backend/test_tts.py -v 2>&1 | tail -15
```

Expected: `test_stt_uses_given_language FAILED`, `test_stt_defaults_to_german FAILED`, `test_synthesize_uses_custom_voice FAILED`

- [ ] **Step 4: Update `backend/stt.py`**

Change the `__init__` signature and language assignment (lines 33–56 of current file):

```python
def __init__(
    self,
    speech_key: str,
    speech_region: str,
    on_text: Callable[[str], None],
    silence_timeout_ms: int = 1000,
    time_cap_s: float = 4.0,
    language: str = "de-DE",
):
    self._on_text = on_text
    self._time_cap_s = time_cap_s
    self._lock = threading.Lock()
    self._interim_text = ""
    self._total_dispatched = ""
    self._cap_timer: Optional[threading.Timer] = None

    self._push_stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

    config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    config.speech_recognition_language = language
    config.set_property(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
        str(silence_timeout_ms),
    )

    self._recognizer = speechsdk.SpeechRecognizer(
        speech_config=config, audio_config=audio_config
    )
    self._recognizer.recognizing.connect(self._on_recognizing)
    self._recognizer.recognized.connect(self._on_recognized)
```

- [ ] **Step 5: Update `backend/tts.py`**

Replace the class definition (full file):

```python
from typing import Callable
import azure.cognitiveservices.speech as speechsdk


class TTSSynthesizer:
    """Synthesizes text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Returns one complete MP3 blob via on_audio_chunk once synthesis finishes.
    """

    def __init__(self, speech_key: str, speech_region: str, voice: str = "en-US-AndrewNeural"):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        config.speech_synthesis_voice_name = voice
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

    def synthesize(self, text: str, on_audio_chunk: Callable[[bytes], None]) -> None:
        result = self._synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"TTS failed: {result.reason}")
        if result.audio_data:
            on_audio_chunk(result.audio_data)
```

- [ ] **Step 6: Run all tests to confirm passing**

```bash
python -m pytest tests/backend/test_stt.py tests/backend/test_tts.py -v
```

Expected: all pass (including pre-existing tests — default voice test still works because default is unchanged)

- [ ] **Step 7: Commit**

```bash
git add backend/stt.py backend/tts.py tests/backend/test_stt.py tests/backend/test_tts.py
git commit -m "feat: add language param to STTSession, voice param to TTSSynthesizer"
```

---

## Task 3: Update `backend/pubsub.py` — lang-scoped groups

**Files:**
- Modify: `backend/pubsub.py`
- Modify: `tests/backend/test_pubsub.py`

- [ ] **Step 1: Update tests first**

Replace the full contents of `tests/backend/test_pubsub.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_audio_sends_binary_to_lang_group(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")

    audio = b"\x00\x01\x02\x03"
    publisher.publish_audio("abc123", "en", audio)

    mock_client.send_to_group.assert_called_once_with(
        "session-abc123-en", audio, content_type="application/octet-stream"
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_get_listener_token_scoped_to_lang_group(mock_client_class):
    mock_client = MagicMock()
    mock_client.get_client_access_token.return_value = {
        "url": "wss://test.webpubsub.azure.com/client/hubs/sermon?access_token=token123"
    }
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    url = publisher.get_listener_token("session42", "fr")

    assert url.startswith("wss://")
    mock_client.get_client_access_token.assert_called_once_with(
        groups=["session-session42-fr"],
        roles=["webpubsub.joinLeaveGroup.session-session42-fr"],
    )


@patch("backend.pubsub.WebPubSubServiceClient")
def test_publish_phrase_sends_text_for_lang(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.publish_phrase("sess1", "es", "El texto limpio", "The clean text")

    call_args = mock_client.send_to_group.call_args
    assert call_args[0][0] == "session-sess1-es"
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "phrase"
    assert payload["text"] == "The clean text"
    assert payload["clean_src"] == "El texto limpio"


@patch("backend.pubsub.WebPubSubServiceClient")
def test_send_close_broadcasts_to_all_lang_groups(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.from_connection_string.return_value = mock_client

    from backend.pubsub import PubSubPublisher
    from backend.languages import SUPPORTED_LANGUAGES
    publisher = PubSubPublisher("Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;")
    publisher.send_close("sess1")

    assert mock_client.send_to_group.call_count == len(SUPPORTED_LANGUAGES)
    called_groups = {c[0][0] for c in mock_client.send_to_group.call_args_list}
    for lang in SUPPORTED_LANGUAGES:
        assert f"session-sess1-{lang['code']}" in called_groups
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/backend/test_pubsub.py -v 2>&1 | tail -15
```

Expected: all 4 tests fail (old tests now gone, new ones fail against old implementation)

- [ ] **Step 3: Replace `backend/pubsub.py`**

```python
import json
from backend.languages import SUPPORTED_LANGUAGES
from azure.messaging.webpubsubservice import WebPubSubServiceClient


class PubSubPublisher:
    def __init__(self, connection_string: str, hub: str = "sermon"):
        normalized_cs = connection_string.replace("AccessKey=", "accesskey=")
        self._client = WebPubSubServiceClient.from_connection_string(
            normalized_cs, hub=hub
        )

    def publish_audio(self, session_id: str, lang: str, audio_bytes: bytes) -> None:
        group = f"session-{session_id}-{lang}"
        self._client.send_to_group(group, audio_bytes, content_type="application/octet-stream")

    def get_listener_token(self, session_id: str, lang: str) -> str:
        group = f"session-{session_id}-{lang}"
        result = self._client.get_client_access_token(
            groups=[group],
            roles=[f"webpubsub.joinLeaveGroup.{group}"],
        )
        return result["url"]

    def publish_phrase(self, session_id: str, lang: str, clean_src: str, text: str) -> None:
        group = f"session-{session_id}-{lang}"
        self._client.send_to_group(
            group,
            json.dumps({"type": "phrase", "clean_src": clean_src, "text": text}),
            content_type="application/json",
        )

    def send_close(self, session_id: str) -> None:
        for lang in SUPPORTED_LANGUAGES:
            group = f"session-{session_id}-{lang['code']}"
            try:
                self._client.send_to_group(group, '{"type":"close"}', content_type="application/json")
            except Exception:
                pass
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_pubsub.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/pubsub.py tests/backend/test_pubsub.py
git commit -m "feat: pubsub — lang-scoped groups (session-{id}-{lang})"
```

---

## Task 4: Rewrite `backend/llm_translator.py` — interpretation + multi-language + pending

**Files:**
- Modify: `backend/llm_translator.py`
- Modify: `tests/backend/test_llm_translator.py`

- [ ] **Step 1: Replace the test file**

Replace the full contents of `tests/backend/test_llm_translator.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

ENGLISH_ONLY = [{"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"}]
TWO_LANGS = [
    {"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"},
    {"code": "es", "name": "Spanish", "voice": "es-ES-ElviraNeural", "llm_key": "es_text"},
]


def _make_mock_response(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_clean_src_and_lang_keys(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Das ist gut", "en_text": "That is good", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Ähm das ist gut")

    assert result["clean_src"] == "Das ist gut"
    assert result["en_text"] == "That is good"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_empty_input_returns_empty_without_api_call(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("   ")

    assert result["clean_src"] == ""
    assert result["en_text"] == ""
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_all_target_language_keys(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Guten Tag", "en_text": "Good day", "es_text": "Buen día", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=TWO_LANGS)
    result = await translator.translate("Guten Tag")

    assert result["en_text"] == "Good day"
    assert result["es_text"] == "Buen día"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_stores_pending_and_sends_in_next_call(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_src": "Und Jesus", "en_text": "And Jesus", "pending": "subject introduced, verb expected"}'),
        _make_mock_response('{"clean_src": "sagte uns", "en_text": "told us", "pending": ""}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

    await translator.translate("Und Jesus")
    assert translator._pending == "subject introduced, verb expected"

    await translator.translate("sagte uns")
    second_call = mock_client.chat.completions.create.call_args_list[1]
    user_msg = second_call.kwargs["messages"][-1]["content"]
    assert "subject introduced, verb expected" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_clears_pending_when_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Fertig", "en_text": "Done", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    translator._pending = "some prior arc"
    await translator.translate("Fertig")

    assert translator._pending == ""


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_builds_context_window(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_src": "Satz eins", "en_text": "Sentence one", "pending": ""}'),
        _make_mock_response('{"clean_src": "Satz zwei", "en_text": "Sentence two", "pending": ""}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY, context_window=5)

    await translator.translate("Satz eins")
    await translator.translate("Satz zwei")

    second_call = mock_client.chat.completions.create.call_args_list[1]
    user_msg = second_call.kwargs["messages"][-1]["content"]
    assert "Satz eins" in user_msg
    assert "Sentence one" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_context_window_limited(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY, context_window=2)

    for i in range(3):
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                json.dumps({"clean_src": f"Satz {i}", "en_text": f"Sentence {i}", "pending": ""})
            )
        )
        await translator.translate(f"Satz {i}")

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
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

    with pytest.raises(Exception, match="timeout"):
        await translator.translate("Das ist gut")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_error_does_not_update_context(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

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
        return_value=_make_mock_response('{"clean_src": "", "en_text": "", "pending": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Ähm äh")

    assert result["clean_src"] == ""
    assert result["en_text"] == ""
    assert len(translator._context) == 0


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_system_prompt_lists_all_target_languages(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_src": "x", "en_text": "x", "es_text": "x", "pending": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=TWO_LANGS)
    await translator.translate("test")

    call_args = mock_client.chat.completions.create.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "en_text" in system_msg
    assert "es_text" in system_msg
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/backend/test_llm_translator.py -v 2>&1 | tail -20
```

Expected: multiple failures due to missing `target_languages` param and wrong return keys

- [ ] **Step 3: Replace `backend/llm_translator.py`**

```python
import json
from collections import deque
from typing import Tuple

from openai import AsyncAzureOpenAI


def _build_system_prompt(target_languages: list[dict]) -> str:
    lang_keys = "\n".join(
        f'- {lang["llm_key"]}: natural {lang["name"]} interpretation'
        for lang in target_languages
    )
    return f"""\
You process live sermon transcript for real-time interpretation.

## Your task
You receive a NEW CHUNK of transcript (possibly mid-sentence or a sentence fragment).
Interpret it into natural, complete phrases in each target language.
Even if the chunk is a sentence fragment, produce complete natural phrases by inferring
the speaker's meaning from context. Do not translate literally — interpret.

The text has been machine-transcribed and may contain transcription errors.
Try to correct them if the meaning seems out of context (e.g. "impossible" transcribed
as "possible" — catch those). If correction is uncertain, translate as given.

The context lines are shown so you can maintain consistent vocabulary and understand
sentence flow — they have already been broadcast. DO NOT include context in your output.
Target vocabulary for young adults and non-native speakers. Be concise but natural.

## Cleaning rules
Remove spoken fillers (ähm, äh, hm, also/ja/ne/sozusagen/irgendwie/halt when used as
fillers), false starts, and immediately repeated words. If the entire input is filler,
return empty strings for all fields.

## Output format
Return JSON only with exactly these keys:
- clean_src: cleaned source text (fillers and false starts removed)
- pending: brief note on any unresolved grammatical arc (e.g. "mid-enumeration,
  continuation expected"); empty string if the thought is complete
{lang_keys}

## Example
Context: [1] "Und erst nach zweieinhalb Tagen" → "And only after two and a half days"
New chunk: "als plötzlich der Friede da ist"
CORRECT output: {{"clean_src": "als plötzlich der Friede da ist", "en_text": "when suddenly the peace arrived", "pending": ""}}
WRONG output: any output that re-includes the context lines\
"""


class LLMTranslator:
    """Interprets and translates sermon text in a single GPT call.

    Maintains a rolling context window of recent utterances.
    Carries forward a 'pending' arc note when a chunk ends mid-thought.
    Raises on API failure so the caller can fall back.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        target_languages: list[dict],
        context_window: int = 5,
    ):
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2024-08-01-preview",
        )
        self._deployment = deployment
        self._target_languages = target_languages
        self._system_prompt = _build_system_prompt(target_languages)
        self._context: deque[Tuple[str, str]] = deque(maxlen=context_window)
        self._pending: str = ""

        # Reference language key for context storage (prefer English)
        ref_keys = [l["llm_key"] for l in target_languages if l["code"] == "en"]
        self._ref_key = ref_keys[0] if ref_keys else target_languages[0]["llm_key"]

    def _build_user_message(self, raw: str) -> str:
        parts = []
        if self._pending:
            parts.append(f"Open thread: {self._pending}")
            parts.append("")
        if self._context:
            parts.append("Recent context (reference only — do NOT re-translate):")
            for i, (src, ref) in enumerate(self._context, 1):
                parts.append(f'[{i}] "{src}" → "{ref}"')
            parts.append("")
        parts.append("New chunk to interpret:")
        parts.append(f'"{raw}"')
        return "\n".join(parts)

    async def translate(self, raw: str) -> dict:
        if not raw.strip():
            result = {"clean_src": ""}
            for lang in self._target_languages:
                result[lang["llm_key"]] = ""
            return result

        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": self._build_user_message(raw)},
            ],
            temperature=0,
            max_tokens=max(128, len(raw.split()) * 8),
            response_format={"type": "json_object"},
            timeout=5.0,
        )

        parsed = json.loads(response.choices[0].message.content.strip())
        clean_src = parsed.get("clean_src", "")
        self._pending = parsed.get("pending", "")

        result = {"clean_src": clean_src}
        for lang in self._target_languages:
            result[lang["llm_key"]] = parsed.get(lang["llm_key"], "")

        if clean_src:
            self._context.append((clean_src, result.get(self._ref_key, "")))

        return result
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_llm_translator.py -v
```

Expected: all 11 tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/llm_translator.py tests/backend/test_llm_translator.py
git commit -m "feat: LLMTranslator — interpretation prompt, multi-language output, pending arc"
```

---

## Task 5: Update `backend/config.py` + `.env.example`

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Update the default in `backend/config.py`**

Change line 53:

```python
stt_time_cap_s=float(os.environ.get("STT_TIME_CAP_S", "8.0")),
```

- [ ] **Step 2: Update `.env.example`**

Change the comment block (lines 10–13):

```
# STT tuning (optional — defaults shown)
# STT_SILENCE_TIMEOUT_MS=1000
# STT_TIME_CAP_S=8.0    # seconds before forcing dispatch of mid-sentence fragment (2–10)
# LLM_CONTEXT_WINDOW=5
```

- [ ] **Step 3: Run config test to confirm nothing broke**

```bash
python -m pytest tests/backend/test_config.py -v
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add backend/config.py .env.example
git commit -m "config: raise STT_TIME_CAP_S default to 8.0 for better phrase quality"
```

---

## Task 6: Update `backend/session.py` — multi-language orchestration

**Files:**
- Modify: `backend/session.py`
- Modify: `tests/backend/test_session.py`

- [ ] **Step 1: Replace test file**

Replace the full contents of `tests/backend/test_session.py`:

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

ENGLISH_ONLY = [{"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"}]


def _make_handler(loop, on_status=None, target_languages=None):
    """Helper to build a SessionHandler with all dependencies mocked."""
    from backend.session import SessionHandler
    return SessionHandler(
        speech_key="sk", speech_region="r", pubsub_cs="cs",
        openai_endpoint="https://ep", openai_api_key="k", openai_deployment="m",
        target_languages=target_languages or ENGLISH_ONLY,
        loop=loop,
        on_status=on_status,
    )


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
    s1, s2 = _make_handler(loop), _make_handler(loop)
    assert s1.session_id != s2.session_id
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_session_listener_tokens_keyed_by_lang(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub.get_listener_token.return_value = "wss://tok"
    mock_pub_class.return_value = mock_pub
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    assert handler.listener_tokens["en"] == "wss://tok"
    mock_pub.get_listener_token.assert_called_once_with(handler.session_id, "en")
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
    handler = _make_handler(loop)
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

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Der Herr ist gut.", "en_text": "The Lord is good."})

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler._process_chunk("Ähm, der Herr ist gut."))

    phrase_msgs = [m for m in statuses if m.get("type") == "phrase"]
    assert len(phrase_msgs) == 1
    assert phrase_msgs[0]["raw_src"] == "Ähm, der Herr ist gut."
    assert phrase_msgs[0]["clean_src"] == "Der Herr ist gut."
    assert phrase_msgs[0]["en_text"] == "The Lord is good."
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_all_tts_when_clean_src_empty(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "", "en_text": ""})

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    loop.run_until_complete(handler._process_chunk("Ähm"))

    mock_tts.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_skips_tts_when_no_audio_listeners(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    """TTS must not fire when audio_active_count for that language is 0."""
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_tts = MagicMock()
    mock_tts_class.return_value = mock_tts

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    # audio_active_count["en"] is 0 by default
    loop.run_until_complete(handler._process_chunk("Gut"))

    mock_tts.synthesize.assert_not_called()
    # phrase should still be published even without audio
    mock_pub.publish_phrase.assert_called_once()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_process_chunk_synthesizes_when_audio_listener_present(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub = MagicMock()
    mock_pub_class.return_value = mock_pub
    mock_pub.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(return_value={"clean_src": "Gut", "en_text": "Good"})

    def fake_synthesize(text, on_chunk):
        on_chunk(b"\x01\x02")

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize
    mock_tts_class.return_value = mock_tts

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)
    handler.audio_join("en")  # one audio listener
    loop.run_until_complete(handler._process_chunk("Gut"))

    mock_tts.synthesize.assert_called_once_with("Good", mock_tts.synthesize.call_args[0][1])
    mock_pub.publish_audio.assert_called_once_with(handler.session_id, "en", b"\x01\x02")
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

    mock_llm = MagicMock()
    mock_llm_class.return_value = mock_llm
    mock_llm.translate = AsyncMock(side_effect=Exception("timeout"))

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    loop.run_until_complete(handler._process_chunk("Der Herr ist gut."))

    fallback_msgs = [m for m in statuses if m.get("type") == "llm_fallback"]
    assert len(fallback_msgs) == 1
    assert fallback_msgs[0]["chunk"] == "Der Herr ist gut."
    mock_tts_class.return_value.synthesize.assert_not_called()
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_listener_join_leave_updates_total_count_in_status(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    statuses = []
    loop = asyncio.new_event_loop()

    async def capture_status(msg):
        statuses.append(msg)

    handler = _make_handler(loop, on_status=capture_status)
    handler.listener_join("en")
    handler.listener_join("es")
    handler.listener_leave("en")
    loop.run_until_complete(asyncio.sleep(0))  # let threadsafe coroutines run

    listener_msgs = [m for m in statuses if m.get("type") == "listeners"]
    counts = [m["count"] for m in listener_msgs]
    assert counts == [1, 2, 1]
    loop.close()


@patch("backend.session.TTSSynthesizer")
@patch("backend.session.LLMTranslator")
@patch("backend.session.STTSession")
@patch("backend.session.PubSubPublisher")
def test_audio_join_leave_updates_audio_active_count(mock_pub_class, mock_stt_class, mock_llm_class, mock_tts_class):
    mock_pub_class.return_value = MagicMock()
    mock_pub_class.return_value.get_listener_token.return_value = "tok"
    mock_stt_class.return_value = MagicMock()
    mock_llm_class.return_value = MagicMock()
    mock_tts_class.return_value = MagicMock()

    loop = asyncio.new_event_loop()
    handler = _make_handler(loop)

    handler.audio_join("en")
    assert handler.audio_active_count["en"] == 1
    handler.audio_join("en")
    assert handler.audio_active_count["en"] == 2
    handler.audio_leave("en")
    assert handler.audio_active_count["en"] == 1
    handler.audio_leave("en")
    handler.audio_leave("en")  # extra leave — should not go negative
    assert handler.audio_active_count["en"] == 0
    loop.close()
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/backend/test_session.py -v 2>&1 | tail -20
```

Expected: multiple failures

- [ ] **Step 3: Replace `backend/session.py`**

```python
import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Optional

log = logging.getLogger("gibberly")

from backend.stt import STTSession
from backend.llm_translator import LLMTranslator
from backend.tts import TTSSynthesizer
from backend.pubsub import PubSubPublisher
from backend.languages import SUPPORTED_LANGUAGES, get_target_languages


class SessionHandler:
    """Orchestrates STT → LLM interpret+translate → TTS → Web PubSub for one session."""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        pubsub_cs: str,
        openai_endpoint: str,
        openai_api_key: str,
        openai_deployment: str,
        target_languages: list[dict],
        source_lang: str = "de-DE",
        silence_timeout_ms: int = 1000,
        time_cap_s: float = 8.0,
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
        self.source_lang = source_lang
        self._target_languages = target_languages
        self._tts_lock = asyncio.Lock()

        self.listener_count: dict[str, int] = {}
        self.audio_active_count: dict[str, int] = {}

        self._publisher = PubSubPublisher(pubsub_cs)

        # One listener token per language
        self.listener_tokens: dict[str, str] = {
            lang["code"]: self._publisher.get_listener_token(self.session_id, lang["code"])
            for lang in target_languages
        }

        # One TTS synthesizer per language
        self._tts: dict[str, TTSSynthesizer] = {
            lang["code"]: TTSSynthesizer(speech_key, speech_region, voice=lang["voice"])
            for lang in target_languages
        }

        self._llm_translator = LLMTranslator(
            openai_endpoint, openai_api_key, openai_deployment,
            target_languages=target_languages,
            context_window=context_window,
        )
        self._stt = STTSession(
            speech_key=speech_key,
            speech_region=speech_region,
            on_text=self._on_text,
            silence_timeout_ms=silence_timeout_ms,
            time_cap_s=time_cap_s,
            language=source_lang,
        )

    def _on_text(self, raw_src: str) -> None:
        """Called from STTSession thread — bridge to asyncio."""
        asyncio.run_coroutine_threadsafe(
            self._process_chunk(raw_src), self._loop
        )

    async def _process_chunk(self, raw_src: str) -> None:
        try:
            result = await self._llm_translator.translate(raw_src)
            clean_src = result["clean_src"]
        except Exception:
            await self._send_status({"type": "llm_fallback", "chunk": raw_src})
            return

        if not clean_src:
            return

        await self._send_status({
            "type": "phrase",
            "raw_src": raw_src,
            "clean_src": clean_src,
            "en_text": result.get("en_text", ""),
        })

        loop = asyncio.get_running_loop()

        async with self._tts_lock:
            for lang in self._target_languages:
                text = result.get(lang["llm_key"], "")
                if not text:
                    continue

                await loop.run_in_executor(
                    None,
                    lambda lc=lang["code"], cs=clean_src, t=text: (
                        self._publisher.publish_phrase(self.session_id, lc, cs, t)
                    ),
                )

                if self.audio_active_count.get(lang["code"], 0) > 0:
                    tts = self._tts[lang["code"]]
                    try:
                        def on_chunk(audio_bytes: bytes, lc=lang["code"]) -> None:
                            self._publisher.publish_audio(self.session_id, lc, audio_bytes)

                        await loop.run_in_executor(
                            None,
                            lambda t=text, s=tts, oc=on_chunk: s.synthesize(t, oc),
                        )
                    except Exception as exc:
                        await self._send_status({"type": "tts_error", "error": str(exc)})

    async def _send_status(self, msg: dict) -> None:
        if self._on_status:
            try:
                await self._on_status(msg)
            except Exception:
                pass

    def listener_join(self, lang: str) -> int:
        self.listener_count[lang] = self.listener_count.get(lang, 0) + 1
        total = sum(self.listener_count.values())
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def listener_leave(self, lang: str) -> int:
        self.listener_count[lang] = max(0, self.listener_count.get(lang, 0) - 1)
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        total = sum(self.listener_count.values())
        asyncio.run_coroutine_threadsafe(
            self._send_status({"type": "listeners", "count": total}),
            self._loop,
        )
        return self.listener_count[lang]

    def audio_join(self, lang: str) -> int:
        self.audio_active_count[lang] = self.audio_active_count.get(lang, 0) + 1
        return self.audio_active_count[lang]

    def audio_leave(self, lang: str) -> int:
        self.audio_active_count[lang] = max(0, self.audio_active_count.get(lang, 0) - 1)
        return self.audio_active_count[lang]

    def start(self) -> None:
        self._stt.start()

    def write(self, audio_bytes: bytes) -> None:
        self._stt.write(audio_bytes)

    def stop(self) -> None:
        self._stt.stop()
        try:
            self._publisher.send_close(self.session_id)
        except Exception as exc:
            log.warning("send_close failed (ignored): %s", exc)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_session.py -v
```

Expected: all 11 tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/session.py tests/backend/test_session.py
git commit -m "feat: SessionHandler — per-language TTS, audio-active gating, listener tokens dict"
```

---

## Task 7: Update `backend/main.py` — new endpoints + source_lang

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/backend/test_main.py`

- [ ] **Step 1: Add new tests to the end of `tests/backend/test_main.py`**

Append these tests (keep all existing tests — they need updating too in Step 4):

```python
@patch("backend.main.SessionHandler")
def test_languages_endpoint_returns_list(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/languages")
                assert r.status_code == 200
                langs = r.json()
                assert isinstance(langs, list)
                assert len(langs) == 9
                assert all("code" in l and "name" in l for l in langs)
                # voice must not be exposed
                assert all("voice" not in l for l in langs)

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_session_info_returns_source_lang(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.source_lang = "de-DE"
        app.state.sessions = {"sess1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/session/sess1/info")
                assert r.status_code == 200
                assert r.json() == {"source_lang": "de-DE"}

                r2 = await client.get("/session/nonexistent/info")
                assert r2.status_code == 404

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_negotiate_with_lang_param(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.listener_tokens = {"en": "wss://tok-en", "fr": "wss://tok-fr"}
        app.state.sessions = {"s1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/negotiate?session=s1&lang=fr")
                assert r.status_code == 200
                assert r.json()["url"] == "wss://tok-fr"

                r2 = await client.get("/negotiate?session=s1&lang=xx")
                assert r2.status_code == 404

        asyncio.run(_test())


@patch("backend.main.SessionHandler")
def test_audio_join_and_leave(mock_session_class):
    import os, importlib, asyncio
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    env = {
        "AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key", "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env):
        import backend.config as cfg; importlib.reload(cfg)
        import backend.main as main_mod; importlib.reload(main_mod)
        from backend.main import app

        mock_handler = MagicMock()
        mock_handler.audio_join.return_value = 1
        mock_handler.audio_leave.return_value = 0
        app.state.sessions = {"s1": mock_handler}

        async def _test():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/session/s1/audio/join?lang=en")
                assert r.status_code == 200
                assert r.json() == {"count": 1}
                mock_handler.audio_join.assert_called_once_with("en")

                r2 = await client.post("/session/s1/audio/leave?lang=en")
                assert r2.status_code == 200
                assert r2.json() == {"count": 0}
                mock_handler.audio_leave.assert_called_once_with("en")

                r3 = await client.post("/session/nonexistent/audio/join?lang=en")
                assert r3.status_code == 404

        asyncio.run(_test())
```

- [ ] **Step 2: Update existing tests in `tests/backend/test_main.py` that break**

The `test_negotiate_returns_pubsub_url` test sets `mock_session.listener_token`. Update the mock:

```python
# In test_negotiate_returns_pubsub_url, change:
mock_session.listener_token = "wss://pubsub.example.com/token"
# To:
mock_session.listener_tokens = {"en": "wss://pubsub.example.com/token"}
# And change the request from:
r = await client.get("/negotiate?session=test-uuid")
# To:
r = await client.get("/negotiate?session=test-uuid&lang=en")
```

The `test_listener_join_increments_count` and `test_listener_leave_decrements_count` tests call `/session/{id}/join` — these now require a `lang` query param. Update:

```python
# In test_listener_join_increments_count, change:
r = await client.post("/session/session-abc/join")
# To:
r = await client.post("/session/session-abc/join?lang=en")

# In test_listener_leave_decrements_count, change:
r = await client.post("/session/session-abc/leave")
# To:
r = await client.post("/session/session-abc/leave?lang=en")
# Also update mock:
mock_handler.listener_leave.return_value = 0
# to ensure listener_leave is called with lang arg:
mock_handler.listener_join.return_value = 1
```

- [ ] **Step 3: Run to confirm failures**

```bash
python -m pytest tests/backend/test_main.py -v 2>&1 | tail -20
```

Expected: new tests fail, some existing tests also fail

- [ ] **Step 4: Replace `backend/main.py`**

```python
import asyncio
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


if LISTENER_DIR.exists():
    app.mount("/listen", StaticFiles(directory=str(LISTENER_DIR), html=True), name="listener")
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/backend/test_main.py -v
```

Expected: all pass

- [ ] **Step 6: Run full suite to check nothing regressed**

```bash
python -m pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/main.py tests/backend/test_main.py
git commit -m "feat: main — /languages, /session/info, lang-scoped negotiate/join/leave, audio endpoints, source_lang WS param"
```

---

## Task 8: Update listener frontend

**Files:**
- Modify: `listener/index.html`
- Modify: `listener/app.js`

No automated tests for frontend — verify manually after Task 10 if the backend is running, or by inspection.

- [ ] **Step 1: Replace `listener/index.html`**

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
    #last-phrase { font-size: 1rem; color: #aaa; text-align: center; }
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

  <p id="last-phrase"></p>

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

- [ ] **Step 2: Replace `listener/app.js`**

```javascript
(function () {
  const connectBtn      = document.getElementById('connect-btn');
  const audioBtn        = document.getElementById('audio-btn');
  const statusEl        = document.getElementById('status');
  const phraseEl        = document.getElementById('last-phrase');
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

  // ── Language selector setup ────────────────────────────────────────────────
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

      // Default to English if available, otherwise first option
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
    audioBtn.style.display = state ? '' : 'none';
    if (!state) {
      audioBtn.textContent = '\uD83D\uDD0A Unmute audio';
      audioBtn.className = '';
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
      // Unmute
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      nextPlayTime = 0;
      fetch(`/session/${session}/audio/join?lang=${chosenLang}`, { method: 'POST' }).catch(() => {});
      audioActive = true;
      audioBtn.textContent = '\uD83D\uDD07 Mute audio';
      audioBtn.className = 'active';
      if (isIOS && muteWarningEl) muteWarningEl.style.display = 'block';
    } else {
      // Mute
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
    phraseEl.textContent = '';
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

      if (msg.type === 'message' && msg.dataType === 'json') {
        if (msg.data?.type === 'close') {
          disconnect('Session ended.');
        } else if (msg.data?.type === 'phrase') {
          const text = msg.data.text || '';
          phraseEl.textContent = text;
          if (text) addPhrase(text);
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
git commit -m "feat: listener — language selector, text-first default, audio unmute opt-in"
```

---

## Task 9: Update operator frontend

**Files:**
- Modify: `operator/index.html`
- Modify: `operator/app.js`

- [ ] **Step 1: Add source language selector to `operator/index.html`**

In the `#controls` div, add a new `<select>` before the device select. Replace the controls div:

```html
  <div id="controls">
    <select id="source-lang-select">
      <option value="de-DE">German sermon</option>
      <option value="en-US">English sermon</option>
    </select>
    <select id="device-select"><option value="">Loading devices…</option></select>
    <select id="channel-select" style="display:none">
      <option value="left">Left</option>
      <option value="right">Right</option>
      <option value="mix">Mix</option>
    </select>
    <input type="file" id="file-input" accept=".wav">
    <button id="action-btn">▶ Start</button>
  </div>
```

Also add a CSS rule for the source lang select to size it appropriately. Add inside the `<style>` block:

```css
    #source-lang-select { flex: none; max-width: 160px; }
```

- [ ] **Step 2: Update `operator/app.js` to use source lang and disable on start**

Add a DOM ref at the top of the IIFE alongside the other refs:

```javascript
  const sourceLangSelect = document.getElementById('source-lang-select');
```

In `openWebSocket`, change the WebSocket URL from:

```javascript
    const ws = new WebSocket(backendWs + '/ws/stream');
```

To:

```javascript
    const sourceLang = sourceLangSelect ? sourceLangSelect.value : 'de-DE';
    const ws = new WebSocket(`${backendWs}/ws/stream?source_lang=${sourceLang}`);
```

Disable the selector when live and re-enable on stop. In `setState`:

```javascript
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
  }
```

Also update the `handleStatusMessage` phrase handler to use the new key names (`raw_src`, `clean_src`):

```javascript
    if (msg.type === 'phrase') {
      const en = msg.en_text || msg.text || '';
      const parts = [];
      if (msg.raw_src || msg.raw_de) parts.push(`raw: ${msg.raw_src || msg.raw_de}`);
      if (msg.clean_src || msg.clean_de) parts.push(`clean: ${msg.clean_src || msg.clean_de}`);
      parts.push(`en: ${en}`);
      lastPhraseEl.innerHTML = parts.map(p => `<div>${p}</div>`).join('');
      if (msg.raw_src || msg.raw_de) console.log(`[gibberly] raw:   ${msg.raw_src || msg.raw_de}`);
      if (msg.clean_src || msg.clean_de) console.log(`[gibberly] clean: ${msg.clean_src || msg.clean_de}`);
      if (en) console.log(`[gibberly] en:    ${en}`);
    }
```

- [ ] **Step 3: Commit**

```bash
git add operator/index.html operator/app.js
git commit -m "feat: operator — source language selector (German/English)"
```

---

## Task 10: Full test suite + final check

- [ ] **Step 1: Run the complete test suite**

```bash
cd /home/chris/gibberly && source .venv/bin/activate
python -m pytest --tb=short -v
```

Expected: all tests pass. Count should be higher than the original 53 (new tests added in Tasks 1, 2, 3, 4, 6, 7).

- [ ] **Step 2: Verify no regressions in existing test files that weren't explicitly updated**

```bash
python -m pytest tests/backend/test_config.py tests/backend/test_stt.py tests/console/ -v
```

Expected: all pass

- [ ] **Step 3: Commit and push branch**

```bash
git log --oneline feature/interpretation-multilang ^master
```

Review commits look correct, then:

```bash
git push -u origin feature/interpretation-multilang
```

---

## Summary of tests added/changed

| File | Before | After |
|------|--------|-------|
| `test_languages.py` | new | 5 tests |
| `test_stt.py` | existing | +2 tests |
| `test_tts.py` | existing | +1 test |
| `test_pubsub.py` | 3 tests replaced | 4 tests |
| `test_llm_translator.py` | 7 tests replaced | 11 tests |
| `test_session.py` | 7 tests replaced | 11 tests |
| `test_main.py` | existing | +4 tests, 3 updated |
