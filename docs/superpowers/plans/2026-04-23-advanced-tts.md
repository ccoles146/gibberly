# Advanced TTS (gpt-4o-mini-tts + Tone Matching + Operator Voice Select) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade TTS to `gpt-4o-mini-tts` when an East US Azure OpenAI endpoint is available, with LLM-driven tone tagging for energy-matched synthesis and a voice picker in the operator console; fall back to the existing Azure Speech synthesiser when no East US endpoint is configured.

**Architecture:** The config layer detects TTS mode from env vars (`AZURE_OPENAI_REGION` and the optional `AZURE_OPENAI_EASTUS_*` pair). The LLM translator gains a `tone` output field at near-zero token cost. A new `OpenAITTSSynthesizer` uses the Azure OpenAI **v1 API** (no dated `api-version` required) with a configurable model name and natural-language voice instructions derived from tone. A `/tts-config` endpoint exposes mode and available voices to the operator panel, which gains a voice picker that passes the selected voice into the session WebSocket URL.

> **Note on SSML:** `gpt-4o-mini-tts` does not accept SSML. Energy shaping is achieved via OpenAI's `instructions` parameter (free-text natural language) — this is the functional equivalent of SSML prosody control for this model.

> **Note on API version:** The Azure OpenAI v1 API (`api_version="v1"`) is the current GA path. It routes to `https://<resource>.openai.azure.com/openai/v1/` and requires no dated version string going forward.

**Tech Stack:** Python 3.13, `openai` package (already installed — provides `AzureOpenAI` sync and `AsyncAzureOpenAI`), FastAPI/asyncio (existing), pytest + pytest-asyncio (existing), vanilla JS (operator panel).

**Status:** COMPLETE

---

## File Map

| File | Change |
|------|--------|
| `.env.example` | Add `AZURE_OPENAI_REGION`, `AZURE_OPENAI_EASTUS_ENDPOINT`, `AZURE_OPENAI_EASTUS_API_KEY`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` |
| `backend/config.py` | Add five new optional fields; add `tts_mode`, `effective_tts_endpoint`, `effective_tts_api_key` read-only properties |
| `backend/llm_translator.py` | Add `tone` to system prompt output schema; parse and return it; default `"calm"` |
| `backend/tts.py` | Add `_TONE_INSTRUCTIONS` dict and `OpenAITTSSynthesizer` (v1 API, configurable model); add `tone` keyword arg to `TTSSynthesizer.synthesize` (ignored, for interface parity) |
| `backend/main.py` | Add `GET /tts-config` endpoint; read `tts_voice` query param from `/ws/stream`; pass TTS config to `SessionHandler` |
| `backend/session.py` | Import `OpenAITTSSynthesizer`; select TTS class at construction; extract `tone` from translate result; pass to `synthesize()` |
| `operator/index.html` | Add voice select `ctrl-group` to controls panel (hidden until JS reveals it) |
| `operator/app.js` | Fetch `/tts-config` on load; show/hide voice select; persist voice to localStorage; include `tts_voice` in WebSocket URL |
| `tests/backend/test_tts.py` | Add three tests for `OpenAITTSSynthesizer` |
| `tests/backend/test_llm_translator.py` | Add two tests: tone present in result, unknown tone defaults to `"calm"` |

---

## Task 1 — Config: new env vars and settings properties

**Files:**
- Modify: `.env.example`
- Modify: `backend/config.py`

- [ ] **Step 1: Add new vars to `.env.example`**

```
# Azure OpenAI region for the primary endpoint (e.g. eastus, germanywestcentral).
# If this equals "eastus", gpt-4o-mini-tts TTS is used automatically via the primary endpoint.
AZURE_OPENAI_REGION=germanywestcentral

# Optional: secondary East US Azure OpenAI resource for advanced TTS.
# Only needed when AZURE_OPENAI_REGION is not "eastus".
# AZURE_OPENAI_EASTUS_ENDPOINT=https://<eastus-resource>.openai.azure.com/
# AZURE_OPENAI_EASTUS_API_KEY=your_eastus_key_here

# Model and voice for advanced TTS (ignored when falling back to Azure Speech TTS).
# OPENAI_TTS_MODEL=gpt-4o-mini-tts
# OPENAI_TTS_VOICE=coral
```

- [ ] **Step 2: Update `backend/config.py`**

Replace the full file with:

```python
import os
from dataclasses import dataclass
from typing import Optional
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
    session_timeout_s: int
    # Advanced TTS fields (all optional — fallback is Azure Speech)
    azure_openai_region: str = ""
    azure_openai_eastus_endpoint: str = ""
    azure_openai_eastus_api_key: str = ""
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "coral"

    @property
    def tts_mode(self) -> str:
        """One of: 'openai_primary', 'openai_secondary', 'azure'."""
        if self.azure_openai_region.lower() == "eastus":
            return "openai_primary"
        if self.azure_openai_eastus_endpoint and self.azure_openai_eastus_api_key:
            return "openai_secondary"
        return "azure"

    @property
    def effective_tts_endpoint(self) -> Optional[str]:
        if self.tts_mode == "openai_primary":
            return self.azure_openai_endpoint
        if self.tts_mode == "openai_secondary":
            return self.azure_openai_eastus_endpoint
        return None

    @property
    def effective_tts_api_key(self) -> Optional[str]:
        if self.tts_mode == "openai_primary":
            return self.azure_openai_api_key
        if self.tts_mode == "openai_secondary":
            return self.azure_openai_eastus_api_key
        return None


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
        stt_time_cap_s=float(os.environ.get("STT_TIME_CAP_S", "8.0")),
        llm_context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", "5")),
        session_timeout_s=int(os.environ.get("SESSION_TIMEOUT_S", "3600")),
        azure_openai_region=os.environ.get("AZURE_OPENAI_REGION", ""),
        azure_openai_eastus_endpoint=os.environ.get("AZURE_OPENAI_EASTUS_ENDPOINT", ""),
        azure_openai_eastus_api_key=os.environ.get("AZURE_OPENAI_EASTUS_API_KEY", ""),
        openai_tts_model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_tts_voice=os.environ.get("OPENAI_TTS_VOICE", "coral"),
    )


settings = _load()
```

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
cd ~/gibberly && source .venv/bin/activate
pytest tests/ -x -q
```

Expected: all 20 tests pass.

- [ ] **Step 4: Commit**

```bash
git add .env.example backend/config.py
git commit -m "feat: add advanced TTS config fields with tts_mode selection logic"
```

---

## Task 2 — LLM: add `tone` field to translator output

**Files:**
- Modify: `backend/llm_translator.py`
- Modify: `tests/backend/test_llm_translator.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/backend/test_llm_translator.py`:

```python
@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_tone_field(mock_client_class):
    """translate() includes a 'tone' key in the result dict."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Gott liebt euch", "en_text": "God loves you", "pending": "", "tone": "warm"}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Gott liebt euch")

    assert result["tone"] == "warm"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_unknown_tone_defaults_to_calm(mock_client_class):
    """An unrecognised tone value from the LLM is coerced to 'calm'."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Test", "en_text": "Test", "pending": "", "tone": "LOUDLY"}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Test")

    assert result["tone"] == "calm"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/backend/test_llm_translator.py::test_translate_returns_tone_field \
       tests/backend/test_llm_translator.py::test_translate_unknown_tone_defaults_to_calm -v
```

Expected: FAIL — `KeyError: 'tone'`.

- [ ] **Step 3: Update `backend/llm_translator.py`**

Add the valid-tone set after the imports:

```python
_VALID_TONES = {"calm", "warm", "urgent", "emphatic", "joyful", "solemn", "questioning"}
```

Replace `_build_system_prompt` with:

```python
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
- tone: one of [calm, warm, urgent, emphatic, joyful, solemn, questioning]
  — the dominant emotional register of the speaker in this chunk
{lang_keys}

## Example
Context: [1] "Und erst nach zweieinhalb Tagen" → "And only after two and a half days"
New chunk: "als plötzlich der Friede da ist"
CORRECT output: {{"clean_src": "als plötzlich der Friede da ist", "en_text": "when suddenly the peace arrived", "pending": "", "tone": "solemn"}}
WRONG output: any output that re-includes the context lines\
"""
```

Replace the `translate` method with:

```python
    async def translate(self, raw: str) -> dict:
        if not raw.strip():
            result = {"clean_src": "", "tone": "calm"}
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
            max_tokens=max(512, len(raw.split()) * 12 * len(self._target_languages)),
            response_format={"type": "json_object"},
            timeout=5.0,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content (possible content filter or token limit)")
        parsed = json.loads(content.strip())
        clean_src = parsed.get("clean_src", "")
        self._pending = parsed.get("pending", "")

        raw_tone = parsed.get("tone", "calm")
        tone = raw_tone if raw_tone in _VALID_TONES else "calm"

        result = {"clean_src": clean_src, "tone": tone}
        for lang in self._target_languages:
            result[lang["llm_key"]] = parsed.get(lang["llm_key"], "")

        if clean_src:
            self._context.append((clean_src, result.get(self._ref_key, "")))

        return result
```

- [ ] **Step 4: Run the two new tests**

```bash
pytest tests/backend/test_llm_translator.py::test_translate_returns_tone_field \
       tests/backend/test_llm_translator.py::test_translate_unknown_tone_defaults_to_calm -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite to check no regressions**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/llm_translator.py tests/backend/test_llm_translator.py
git commit -m "feat: add tone field to LLM translator output for TTS voice shaping"
```

---

## Task 3 — TTS: add `OpenAITTSSynthesizer` (v1 API, configurable model)

**Files:**
- Modify: `backend/tts.py`
- Modify: `tests/backend/test_tts.py`

- [ ] **Step 1: Write three failing tests**

Append to `tests/backend/test_tts.py`:

```python
# ── OpenAITTSSynthesizer ────────────────────────────────────────────────────

@patch("backend.tts.AzureOpenAI")
def test_openai_tts_synthesize_returns_audio(mock_client_class):
    """Audio bytes from the API response are passed to the callback."""
    audio_bytes = b"\xff\xfb" + b"\x00" * 200
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = audio_bytes

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key")
    received = []
    synth.synthesize("God loves you", received.append)

    assert received == [audio_bytes]


@patch("backend.tts.AzureOpenAI")
def test_openai_tts_passes_tone_as_instructions(mock_client_class):
    """The tone argument is mapped to a non-empty instructions string."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = b"\x00"

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key")
    synth.synthesize("Hallelujah", lambda _: None, tone="joyful")

    call_kwargs = mock_client.audio.speech.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini-tts"
    assert len(call_kwargs["instructions"]) > 10


@patch("backend.tts.AzureOpenAI")
def test_openai_tts_uses_configurable_model(mock_client_class):
    """The model name is taken from the constructor argument, not hardcoded."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.audio.speech.create.return_value.content = b"\x00"

    from backend.tts import OpenAITTSSynthesizer
    synth = OpenAITTSSynthesizer("https://ep.openai.azure.com/", "key", model="gpt-4o-tts")
    synth.synthesize("Test", lambda _: None)

    call_kwargs = mock_client.audio.speech.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-tts"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/backend/test_tts.py::test_openai_tts_synthesize_returns_audio \
       tests/backend/test_tts.py::test_openai_tts_passes_tone_as_instructions \
       tests/backend/test_tts.py::test_openai_tts_uses_configurable_model -v
```

Expected: FAIL — `ImportError: cannot import name 'OpenAITTSSynthesizer'`.

- [ ] **Step 3: Replace `backend/tts.py`**

```python
from typing import Callable
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI

# Tone → natural-language voice instruction for gpt-4o-mini-tts.
# Uses OpenAI's `instructions` parameter — SSML is not supported by this model.
_TONE_INSTRUCTIONS: dict[str, str] = {
    "calm":        "Speak gently and evenly with quiet warmth. Unhurried, steady pace.",
    "warm":        "Speak with pastoral warmth and genuine care. Natural, conversational tone.",
    "urgent":      "Speak with urgency and conviction. Slightly faster pace, words carry weight.",
    "emphatic":    "Speak with deliberate emphasis on key words. Authoritative but not harsh.",
    "joyful":      "Speak brightly, with life and celebration in the voice.",
    "solemn":      "Speak slowly and gravely. Quiet reverence, weighted pauses.",
    "questioning": "Slightly open, inviting tone. Raise inflection at key moments of reflection.",
}


class TTSSynthesizer:
    """Synthesizes text to audio using Azure Speech SDK.

    synthesize() is synchronous — run it in a thread executor.
    Returns one complete MP3 blob via on_audio_chunk once synthesis finishes.
    The tone argument is accepted for interface parity but ignored.
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

    def synthesize(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None],
        tone: str = "calm",
    ) -> None:
        result = self._synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"TTS failed: {result.reason}")
        if result.audio_data:
            on_audio_chunk(result.audio_data)


class OpenAITTSSynthesizer:
    """Synthesizes text using a configurable OpenAI TTS model via Azure OpenAI.

    Uses the v1 API (api_version='v1') — no dated version string required.
    synthesize() is synchronous — run it in a thread executor.
    Voice instructions are derived from the tone argument.
    Note: SSML is not supported; this model uses natural-language instructions.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        voice: str = "coral",
        model: str = "gpt-4o-mini-tts",
    ):
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="v1",
        )
        self._voice = voice
        self._model = model

    def synthesize(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None],
        tone: str = "calm",
    ) -> None:
        instructions = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["calm"])
        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            instructions=instructions,
        )
        audio_bytes = response.content
        if audio_bytes:
            on_audio_chunk(audio_bytes)
```

- [ ] **Step 4: Run all TTS tests**

```bash
pytest tests/backend/test_tts.py -v
```

Expected: all 8 tests pass (5 existing + 3 new).

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/tts.py tests/backend/test_tts.py
git commit -m "feat: add OpenAITTSSynthesizer with v1 API, configurable model, and tone voice instructions"
```

---

## Task 4 — Session: wire TTS selection and tone

**Files:**
- Modify: `backend/session.py`

- [ ] **Step 1: Update `backend/session.py`**

Change the import block at the top:

```python
from backend.tts import TTSSynthesizer, OpenAITTSSynthesizer
```

Add three optional constructor parameters after `context_window`:

```python
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
        openai_tts_endpoint: Optional[str] = None,
        openai_tts_api_key: Optional[str] = None,
        openai_tts_model: str = "gpt-4o-mini-tts",
        openai_tts_voice: str = "coral",
    ):
```

Replace the `self._tts` construction block (the four lines starting `self._tts: dict[str, TTSSynthesizer]`):

```python
        if openai_tts_endpoint and openai_tts_api_key:
            self._tts: dict[str, TTSSynthesizer | OpenAITTSSynthesizer] = {
                lang["code"]: OpenAITTSSynthesizer(
                    openai_tts_endpoint,
                    openai_tts_api_key,
                    voice=openai_tts_voice,
                    model=openai_tts_model,
                )
                for lang in target_languages
            }
        else:
            self._tts = {
                lang["code"]: TTSSynthesizer(speech_key, speech_region, voice=lang["voice"])
                for lang in target_languages
            }
```

In `_process_chunk`, extract `tone` and forward it. Replace the full method:

```python
    async def _process_chunk(self, raw_src: str) -> None:
        if self.paused:
            return
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

        tone = result.get("tone", "calm")
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
                            lambda t=text, s=tts, oc=on_chunk, tn=tone: s.synthesize(t, oc, tone=tn),
                        )
                    except Exception as exc:
                        await self._send_status({"type": "tts_error", "error": str(exc)})
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass. (Session tests mock TTSSynthesizer; the new params default to `None` so existing tests exercise the Azure path unchanged.)

- [ ] **Step 3: Commit**

```bash
git add backend/session.py
git commit -m "feat: wire OpenAI TTS selection, configurable model, and tone forwarding into session"
```

---

## Task 5 — Backend: `/tts-config` endpoint and voice param on `/ws/stream`

**Files:**
- Modify: `backend/main.py`

The `main.py` file exposes the FastAPI app and the `/ws/stream` WebSocket handler. Make the following two changes:

- [ ] **Step 1: Add the `/tts-config` endpoint**

Add this route alongside the other GET routes (e.g. after `/languages`):

```python
OPENAI_TTS_VOICES = [
    {"id": "coral",   "label": "Coral — warm, natural"},
    {"id": "onyx",    "label": "Onyx — deep, authoritative"},
    {"id": "ash",     "label": "Ash — conversational, clear"},
    {"id": "shimmer", "label": "Shimmer — soft, gentle"},
    {"id": "nova",    "label": "Nova — bright, energetic"},
    {"id": "alloy",   "label": "Alloy — neutral, balanced"},
]

@app.get("/tts-config")
async def get_tts_config():
    return {
        "mode":   settings.tts_mode,          # "azure" | "openai_primary" | "openai_secondary"
        "model":  settings.openai_tts_model,
        "voice":  settings.openai_tts_voice,
        "voices": OPENAI_TTS_VOICES,
    }
```

- [ ] **Step 2: Read `tts_voice` query param in the `/ws/stream` handler**

In the existing WebSocket handler function signature, add the optional `tts_voice` param:

```python
@app.websocket("/ws/stream")
async def ws_stream(
    websocket: WebSocket,
    source_lang: str = "de-DE",
    tts_voice: str = "",          # ← add this
):
```

When constructing `SessionHandler`, pass the effective voice (operator override takes priority over env default):

```python
    session = SessionHandler(
        # ... all existing args unchanged ...
        openai_tts_endpoint=settings.effective_tts_endpoint,
        openai_tts_api_key=settings.effective_tts_api_key,
        openai_tts_model=settings.openai_tts_model,
        openai_tts_voice=tts_voice or settings.openai_tts_voice,   # ← operator override
        loop=asyncio.get_running_loop(),
        on_status=...,
    )
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add /tts-config endpoint and tts_voice session param"
```

---

## Task 6 — Operator: voice selector UI

**Files:**
- Modify: `operator/index.html`
- Modify: `operator/app.js`

- [ ] **Step 1: Add voice select to `operator/index.html`**

In the controls panel (`<aside class="controls-panel">`), insert a new `ctrl-group` after the channel group and before the audio level meter:

```html
      <div class="ctrl-group" id="voice-group" style="display:none">
        <span class="ctrl-label">TTS Voice</span>
        <select id="voice-select">
          <!-- populated by JS from /tts-config -->
        </select>
      </div>
```

- [ ] **Step 2: Update `operator/app.js`**

After the existing DOM ref block, add:

```javascript
  const voiceGroup   = document.getElementById('voice-group');
  const voiceSelect  = document.getElementById('voice-select');
  const STORAGE_VOICE = 'gibberly_tts_voice';
```

Add a new function to load TTS config and populate the voice dropdown. Place it alongside `populateDevices`:

```javascript
  async function loadTtsConfig() {
    let config;
    try {
      const res = await fetch(backendHttp + '/tts-config');
      if (!res.ok) return;
      config = await res.json();
    } catch (_) { return; }

    if (config.mode === 'azure') return; // Azure TTS — no voice picker needed

    // Populate voice options
    voiceSelect.innerHTML = '';
    (config.voices || []).forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.label;
      voiceSelect.appendChild(opt);
    });

    // Restore saved or default voice
    const saved = localStorage.getItem(STORAGE_VOICE);
    const defaultVoice = saved || config.voice || 'coral';
    if ([...voiceSelect.options].some(o => o.value === defaultVoice)) {
      voiceSelect.value = defaultVoice;
    }

    voiceGroup.style.display = '';
  }

  voiceSelect.addEventListener('change', () => {
    localStorage.setItem(STORAGE_VOICE, voiceSelect.value);
  });

  loadTtsConfig();
```

In `setState`, disable/enable the voice select alongside the source lang select:

```javascript
    if (sourceLangSelect) sourceLangSelect.disabled = (s === 'live' || s === 'connecting');
    voiceSelect.disabled = (s === 'live' || s === 'connecting');   // ← add this line
```

In `openWebSocket`, include the voice in the WebSocket URL. Find:

```javascript
    const ws = new WebSocket(`${backendWs}/ws/stream?source_lang=${sourceLang}`);
```

Replace with:

```javascript
    const voice = voiceSelect.value || localStorage.getItem(STORAGE_VOICE) || '';
    const voiceParam = voice ? `&tts_voice=${encodeURIComponent(voice)}` : '';
    const ws = new WebSocket(`${backendWs}/ws/stream?source_lang=${sourceLang}${voiceParam}`);
```

- [ ] **Step 3: Smoke-test the operator panel manually**

Start the backend (or use a mock) and open the operator panel in a browser. With `tts_mode === 'azure'` the voice selector should be hidden. Temporarily set `AZURE_OPENAI_REGION=eastus` in `.env`, restart the backend, reload the panel — the voice selector should appear and list the six voices. Changing voice and refreshing should restore the selection.

- [ ] **Step 4: Commit**

```bash
git add operator/index.html operator/app.js
git commit -m "feat: add TTS voice selector to operator panel, driven by /tts-config"
```

---

## Verification

- [ ] **Config smoke — Azure fallback**

```bash
python -c "
from backend.config import settings
assert settings.tts_mode == 'azure'
assert settings.effective_tts_endpoint is None
print('OK: Azure fallback')
"
```

- [ ] **Config smoke — East US secondary**

```bash
AZURE_OPENAI_EASTUS_ENDPOINT=https://test.openai.azure.com/ \
AZURE_OPENAI_EASTUS_API_KEY=testkey \
python -c "
from backend.config import settings
assert settings.tts_mode == 'openai_secondary'
assert settings.effective_tts_endpoint == 'https://test.openai.azure.com/'
print('OK: East US secondary')
"
```

- [ ] **Config smoke — East US primary**

```bash
AZURE_OPENAI_REGION=eastus python -c "
from backend.config import settings
assert settings.tts_mode == 'openai_primary'
print('OK: East US primary, endpoint:', settings.effective_tts_endpoint)
"
```

- [ ] **Full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass.

---

## Operational notes

**v1 API routing:** `api_version="v1"` in `AzureOpenAI` routes requests to `https://<resource>.openai.azure.com/openai/v1/`. If the East US resource returns `404` for this path, the resource may have been provisioned before the v1 API was rolled out — check the Azure AI Foundry portal for that resource and confirm the v1 endpoint is listed. As a fallback, replace `"v1"` with `"2025-03-01-preview"` in `OpenAITTSSynthesizer._init_`.

**Model name:** Defaults to `gpt-4o-mini-tts`. To use the full quality model, set `OPENAI_TTS_MODEL=gpt-4o-tts` in `.env`. The operator panel always shows whichever model the backend is configured to use.

**Voice per session vs. voice in env:** `OPENAI_TTS_VOICE` in `.env` sets the server default. When the operator picks a voice in the panel, it overrides for that session via the `tts_voice` WebSocket query param. Disconnecting and reconnecting picks up any new operator selection.

**Latency:** Calls from `germanywestcentral` to an East US Azure OpenAI endpoint add ~90–120 ms vs ~10–20 ms for the local Azure Speech endpoint. With the full pipeline already at ~2 s, this is imperceptible to listeners.
