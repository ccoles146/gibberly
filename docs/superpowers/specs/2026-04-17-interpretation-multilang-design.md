# Design: Interpretation Pipeline + Multi-language Listener
**Date:** 2026-04-17
**Branch:** `feature/interpretation-multilang`

---

## 1. Overview

Two independent changes to the Gibberly live sermon translation service:

1. **Interpretation pipeline** — improve TTS phrase quality by switching the LLM from literal fragment translation to natural-phrase interpretation, and extending the STT time cap.
2. **Multi-language listener** — allow listeners to choose their target language, default to text-only (audio opt-in), and suppress TTS synthesis for languages with no active audio listeners.

Additionally: **operator source language selector** (German / English) on the operator panel.

---

## 2. Change 1 — Interpretation Pipeline

### 2.1 Problem

The STT `time_cap_s` (default 4s) forces dispatch of mid-sentence German fragments. The LLM system prompt previously instructed literal translation of fragments only, producing choppy, unnatural English TTS output (e.g. "and I can't even" synthesised as a complete phrase).

### 2.2 Solution

**`backend/llm_translator.py` — prompt rewrite**

The system prompt is rewritten with these principles:

- **Interpret, don't literally translate.** Produce natural, complete English phrases even when the German input is a mid-sentence fragment. This text has been machine transcribed and may include incorrect transcriptions, try to correct them if the meaning seems out of context or simply do not translate, this is particularly important where for example 'impossible' was transcribed as 'possible', try to catch those.
- **Use context actively.** The rolling context window (last 5 pairs) is framing for completing fragments, not just vocabulary reference.
- **Pending thread.** The LLM returns an optional `pending` string — a brief note on any unresolved grammatical arc (e.g. "speaker is mid-enumeration"). This is stored in `LLMTranslator._pending` and prepended to the next user message as: `Open thread: <pending>`. This helps the next call pick up the thought without re-reading context pairs.
- **Output format** remains `{"clean_src": "...", "en_text": "...", "pending": "..."}` where `pending` may be empty. All existing target language keys are also present (see Change 2).
- **Empty/filler input** still returns all-empty fields.

`LLMTranslator.translate()` stores `result.get("pending", "")` in `self._pending` after each call and prepends it to the next user message. Return dict to callers is unchanged: `{"clean_de": ..., "en_text": ..., <lang_keys>}`.

**`backend/stt.py`** — no code change required. The time cap is already tunable via config.

**`backend/config.py`** — `STT_TIME_CAP_S` default changed from `4.0` to `8.0`.

**`.env.example`** — comment updated to reflect the new default and range (2–10s).

### 2.3 What does not change

`SessionHandler`, `TTSSynthesizer`, `PubSubPublisher`, and the console are unaffected by this change.

---

## 3. Change 2 — Multi-language Listener

### 3.1 Language list

**New file: `backend/languages.py`**

```python
SUPPORTED_LANGUAGES = [
    {"code": "en", "name": "English",    "voice": "en-US-AndrewNeural",      "llm_key": "en_text"},
    {"code": "de", "name": "German",     "voice": "de-DE-KatjaNeural",       "llm_key": "de_text"},
    {"code": "es", "name": "Spanish",    "voice": "es-ES-ElviraNeural",      "llm_key": "es_text"},
    {"code": "fr", "name": "French",     "voice": "fr-FR-DeniseNeural",      "llm_key": "fr_text"},
    {"code": "hr", "name": "Croatian",     "voice": "hr-HR-GabrijelaNeural",   "llm_key": "hr_text"},
    {"code": "pt", "name": "Portuguese", "voice": "pt-BR-FranciscaNeural",   "llm_key": "pt_text"},
    {"code": "pl", "name": "Polish",     "voice": "pl-PL-ZofiaNeural",       "llm_key": "pl_text"},
    {"code": "ro", "name": "Romanian",   "voice": "ro-RO-AlinaNeural",       "llm_key": "ro_text"},
    {"code": "uk", "name": "Ukrainian",  "voice": "uk-UA-PolinaNeural",      "llm_key": "uk_text"},
]
```

The source language is excluded from the listener target list at runtime (e.g. if input is German, `de` is not offered to listeners; if input is English, `en` is not offered).

### 3.2 New backend endpoint: `GET /languages`

Returns `[{"code": "en", "name": "English"}, ...]` — voice names are not exposed.

The listener needs to know the session's source language to filter it from the selector. A new `GET /session/{id}/info` endpoint returns `{"source_lang": "de-DE"}`. The listener fetches both `/languages` and `/session/{id}/info` on load (in parallel), then filters the source language from the selector before rendering. This keeps the `/negotiate` endpoint clean.

### 3.3 LLM changes

`LLMTranslator` system prompt expands to list all active target language codes (determined at construction time). Output JSON includes one key per language (`en_text`, `es_text`, etc.) plus `clean_src` (cleaned source text, language-agnostic field name) and `pending`.

`LLMTranslator.__init__` accepts `target_languages: list[str]` (list of `llm_key` values). The system prompt is built dynamically from this list.

Context window stores `(clean_src, en_text)` as the canonical pair (English as reference language). If English is not a target language, it stores the first target language's text instead.

`translate()` return dict: `{"clean_src": ..., "en_text": ..., "es_text": ..., ..., "pending": ...}`. For backwards compatibility, `clean_de` is aliased to `clean_src` in the return dict when source language is German.

### 3.4 TTSSynthesizer

Add `voice` parameter to constructor (currently hardcoded to `en-US-AndrewNeural`).

```python
class TTSSynthesizer:
    def __init__(self, speech_key: str, speech_region: str, voice: str = "en-US-AndrewNeural"):
```

### 3.5 PubSub groups

Groups: `session-{id}-{lang}` (e.g. `session-abc123-en`, `session-abc123-es`).

`PubSubPublisher` methods updated:
- `get_listener_token(session_id, lang)` — grants membership to `session-{id}-{lang}`
- `publish_audio(session_id, lang, audio_bytes)`
- `publish_phrase(session_id, lang, clean_src, text)` — phrase JSON only includes the target language text, no other languages
- `send_close(session_id)` — broadcasts to all groups (iterates `SUPPORTED_LANGUAGES`)

`SessionHandler` stores a dict of listener tokens at startup, one per language.

### 3.6 SessionHandler changes

**Constructor additions:**
- `source_lang: str` — STT recognition language (e.g. `"de-DE"`)
- `target_languages: list[dict]` — subset of `SUPPORTED_LANGUAGES` (after excluding source)

**State additions:**
- `_tts: dict[str, TTSSynthesizer]` — one per language code
- `listener_count: dict[str, int]` — per language (replaces scalar)
- `audio_active_count: dict[str, int]` — per language, default 0

**`_process_chunk` changes:**

```
for each language in target_languages:
    text = result[lang["llm_key"]]
    if not text:
        continue
    publish_phrase(session_id, lang["code"], clean_src, text)
    if audio_active_count[lang["code"]] > 0:
        synthesize TTS with lang["voice"] and publish_audio(session_id, lang["code"], ...)
```

All TTS calls for a single chunk run sequentially inside the existing `_tts_lock` to preserve ordering. They are run in executor as before.

**Listener join/leave methods** updated to accept `lang: str`:
- `listener_join(lang)` / `listener_leave(lang)` — updates `listener_count[lang]`
- `audio_join(lang)` / `audio_leave(lang)` — updates `audio_active_count[lang]`

The `on_status` callback emits `{"type": "listeners", "count": <total>}` where `total` is the sum across all languages — keeping the operator console display unchanged. Per-language breakdown is out of scope for this change.

### 3.7 Backend HTTP endpoints

| Method | Path | Change |
|--------|------|--------|
| GET | `/languages` | New — returns `[{code, name}]` |
| GET | `/session/{id}/info` | New — returns `{source_lang}` |
| GET | `/negotiate?session={id}&lang={code}` | `lang` param added |
| POST | `/session/{id}/join?lang={code}` | `lang` param added |
| POST | `/session/{id}/leave?lang={code}` | `lang` param added |
| POST | `/session/{id}/audio/join?lang={code}` | New |
| POST | `/session/{id}/audio/leave?lang={code}` | New |

### 3.8 WebSocket stream endpoint

`/ws/stream?source_lang=de-DE` (default `de-DE`). Backend reads `source_lang` from query params, validates against `["de-DE", "en-US"]`, passes to `SessionHandler`. Also included in `session_created` WS message.

### 3.9 Listener UI (`listener/index.html` + `listener/app.js`)

**On page load (before connect):**
1. Fetch `GET /languages` — populate language selector `<select>` (default: first language, typically English).
2. If session ID is in URL params, also fetch `GET /session/{id}/info` to get `source_lang` and filter it from the selector.

**Language selector:** a `<select>` shown before connecting. Disabled after connect (language is locked for the session). The chosen `lang` code is passed to `/negotiate?session={id}&lang={lang}` and to join/leave calls.

**Connect flow change:** the Listen button becomes **Connect**. On connect, join WebSocket as before (language-scoped group). No `AudioContext` created yet.

**Unmute audio button:** shown after connecting, default off. Tapping:
- Creates `AudioContext`
- Resumes it (handles iOS autoplay)
- POSTs `/session/{id}/audio/join?lang={lang}`
- Changes button label to "Mute audio"

Muting again:
- Suspends `AudioContext`
- POSTs `/session/{id}/audio/leave?lang={lang}`

Phrase display and transcript section work as before, using `msg.data.text` from phrase events (language-specific text already selected server-side).

### 3.10 Operator panel changes (`operator/app.js` + `operator/index.html`)

Add a source language `<select>` with two options:
- `de-DE` — German (default)
- `en-US` — English

This selector is shown before session start, disabled once streaming begins. The chosen value is appended to the WebSocket URL: `/ws/stream?source_lang=de-DE`.

---

## 4. Data flow summary (post-change)

```
Mic/file → STT (de-DE or en-US, cap 8s)
         → LLMTranslator.translate(raw)
             → GPT-4o mini: clean_src + en_text + es_text + ... + pending
         → for each language:
               publish_phrase(session, lang, text)   ← always
               if audio_active_count[lang] > 0:
                   TTSSynthesizer(voice=lang.voice).synthesize(text)
                   publish_audio(session, lang, bytes)
```

```
Listener page loads:
  → GET /languages           (build selector)
  → GET /session/{id}/info   (filter source lang from selector)
  → user picks language, taps Connect
  → GET /negotiate?session=X&lang=en  (get WS token)
  → WS connect → joinGroup session-X-en
  → POST /session/X/join?lang=en
  → phrase events arrive → display text
  → user taps "Unmute audio"
  → POST /session/X/audio/join?lang=en
  → audio events arrive → play
```

---

## 5. Files changed

| File | Type |
|------|------|
| `backend/languages.py` | New |
| `backend/llm_translator.py` | Modified |
| `backend/tts.py` | Modified |
| `backend/pubsub.py` | Modified |
| `backend/session.py` | Modified |
| `backend/main.py` | Modified |
| `backend/config.py` | Modified |
| `listener/index.html` | Modified |
| `listener/app.js` | Modified |
| `operator/app.js` | Modified |
| `operator/index.html` | Modified |
| `.env.example` | Modified |

---

## 6. Out of scope

- Per-language transcript download (listener downloads only the language it selected — existing behaviour is sufficient)
- Operator visibility into per-language listener counts (future)
- Dynamic language list (adding languages without code change)
- More than 2 source languages
