# Design: LLM STT Cleaning Pipeline

**Date:** 2026-04-08  
**Status:** Approved

## Problem

The current pipeline uses Azure `TranslationRecognizer` which does STT + Translation + TTS in a single opaque call. German sermon speech is extemporaneous and contains fillers (ähm, äh, also, ja, sozusagen, etc.) that get faithfully translated into awkward English, degrading the listener experience.

## Approach

Replace the integrated `TranslationRecognizer` with a four-stage explicit pipeline:

```
Audio bytes
    │
    ▼
[STTSession]          Azure Speech Recognizer (de-DE only)
    │ German text chunks (timer-based, ~1.5s)
    ▼
[LLMCleaner]          Azure OpenAI GPT-4o mini
    │ Cleaned German text (or empty string → stop)
    ▼
[TextTranslator]      Azure Cognitive Services Translator (de→en)
    │ English text
    ▼
[TTSSynthesizer]      Azure Speech SDK SpeechSynthesizer (en-US-AndrewNeural)
    │ Audio chunks (streamed via start_speaking_text_async)
    ▼
  Listeners (Web PubSub — unchanged)
```

This gives two text interception points (German and English) for future post-processing.

## Components

### STTSession (`backend/stt.py`)

Replaces `TranslationSession`. Wraps `azure.cognitiveservices.speech.SpeechRecognizer` configured for `de-DE`.

**Chunking behaviour:**
- Subscribes to both `recognizing` (interim) and `recognized` (final phrase) events.
- Maintains a word cursor (`_last_word_count`) on the current interim text.
- A repeating timer fires every `chunk_interval` seconds (default 1.5s). On each tick, it extracts words beyond the cursor, dispatches them as a raw German chunk via `on_text(chunk: str)`, and advances the cursor.
- On `recognized` (phrase complete): cancels the pending tick, dispatches any remaining words from the final text, resets cursor to 0.
- Thread safety: a `threading.Lock` guards cursor and interim text access (Azure SDK callbacks run on background threads).

**Known tradeoff:** Azure can revise earlier words in interim results. Words already dispatched to TTS cannot be recalled. This is acceptable for live sermon use.

**Config:** `Speech_SegmentationSilenceTimeoutMs` set to `500` to also encourage faster phrase breaks on natural pauses.

### LLMCleaner (`backend/llm_cleaner.py`)

Calls Azure OpenAI GPT-4o mini. Runs in a thread executor to avoid blocking the asyncio event loop.

**System prompt:**
```
You are processing a live German sermon transcript for real-time translation.
Remove spoken language fillers (ähm, äh, hm, also/ja/ne/sozusagen/irgendwie/halt
when used as fillers) and clean up false starts or immediately repeated words.
Preserve the meaning, sentence structure, and theological vocabulary exactly.
Return only the cleaned German text — no explanation, no translation.
If the entire input is filler or empty, return an empty string.
```

**Parameters:** temperature=0, max_tokens=`max(64, len(chunk.split()) * 3)` — generous headroom for a German chunk that shrinks after cleaning.

**Fallback:** If the Azure OpenAI call fails or times out (2s), pass the raw German text through unchanged and emit `{"type": "llm_fallback", "chunk": "..."}` to the operator console. Never silently drop a phrase.

### TextTranslator (`backend/text_translator.py`)

Calls Azure Cognitive Services Translator REST API (`/translate?from=de&to=en`). Runs in a thread executor.

If `LLMCleaner` returns an empty string, `TextTranslator` is not called — the pipeline stops for that chunk and no audio is emitted.

### TTSSynthesizer (`backend/tts.py`)

Wraps `azure.cognitiveservices.speech.SpeechSynthesizer` with `en-US-AndrewNeural`.

Uses `start_speaking_text_async()` to begin synthesis and reads chunks from the returned `AudioDataStream`, calling `on_audio_chunk(bytes)` as they arrive. This preserves the streaming behaviour of the current `synthesizing` event callback.

### SessionHandler (`backend/session.py`)

Orchestrates the pipeline. Key changes:
- Imports `STTSession` instead of `TranslationSession`.
- Creates `LLMCleaner`, `TextTranslator`, and `TTSSynthesizer` instances.
- `_on_text(raw_de: str)` is the new callback from `STTSession`. It runs the async chain: clean → translate → synthesize → publish.
- `_on_phrase` is updated to send enriched status: `{"type": "phrase", "raw_de": "...", "clean_de": "...", "text": "..."}` so the operator console shows all three text stages for quality monitoring.
- `translation.py` is deleted.

## Error Handling Summary

| Stage         | Failure mode              | Behaviour                                      |
|---------------|---------------------------|------------------------------------------------|
| STTSession    | Azure Speech unavailable  | WebSocket error propagates, session ends       |
| LLMCleaner    | Timeout / API error       | Pass raw German through, emit `llm_fallback`   |
| TextTranslator| API error                 | Log error, skip chunk (no audio for that chunk)|
| TTSSynthesizer| Synthesis error           | Log error, skip chunk                          |
| Empty chunk   | All-filler input          | Pipeline stops after LLM stage, no TTS         |

## Configuration

### New environment variables

```
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

AZURE_TRANSLATOR_KEY=...
AZURE_TRANSLATOR_REGION=...
# AZURE_TRANSLATOR_ENDPOINT is optional; defaults to https://api.cognitive.microsofttranslator.com

STT_CHUNK_INTERVAL_S=1.5   # seconds between interim dispatches
```

`config.py` gains these fields. All new fields are required except `STT_CHUNK_INTERVAL_S` (defaults to `1.5`).

### New Azure resources

| Resource                              | Tier          | Purpose                        |
|---------------------------------------|---------------|--------------------------------|
| Azure OpenAI                          | S0            | GPT-4o mini deployment         |
| Azure Cognitive Services Translator   | S1 (or Free)  | de→en text translation         |

`docs/azure-setup.md` to be updated with provisioning steps for both.

### New Python dependencies

- `openai>=1.0` (Azure OpenAI SDK)
- `requests` (Translator REST call — likely already present)

## File Changes

| File                              | Change                                    |
|-----------------------------------|-------------------------------------------|
| `backend/stt.py`                  | New — `STTSession`                        |
| `backend/llm_cleaner.py`          | New — `LLMCleaner`                        |
| `backend/text_translator.py`      | New — `TextTranslator`                    |
| `backend/tts.py`                  | New — `TTSSynthesizer`                    |
| `backend/translation.py`          | Deleted                                   |
| `backend/session.py`              | Updated orchestration                     |
| `backend/config.py`               | New env var fields                        |
| `backend/__init__.py`             | No change                                 |
| `backend/main.py`                 | No change                                 |
| `backend/pubsub.py`               | No change                                 |
| `docs/azure-setup.md`             | New provisioning steps                    |
| `requirements.txt` / `pyproject`  | Add `openai`, confirm `requests`          |

## Latency Analysis

Additional latency per chunk vs current integrated pipeline:

| Stage         | Estimated latency |
|---------------|-------------------|
| LLM cleaning  | 150–300 ms        |
| Text translate| 50–150 ms         |
| TTS (streamed)| similar to current|
| **Total added**| **200–450 ms**   |

For 1.5s chunks this is a ~15–30% overhead, acceptable for live sermon translation.
