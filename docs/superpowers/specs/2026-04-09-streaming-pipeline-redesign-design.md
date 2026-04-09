# Streaming Pipeline Redesign — Design Spec

**Date:** 2026-04-09
**Goal:** Fix broken phrasing and burst-then-silence audio by replacing word-level timer chunking with recognized-event buffering, combining LLM cleaning + translation with a context window, and streaming TTS audio via the `synthesizing` event.

**Latency budget:** ~5 seconds behind the speaker.

---

## Problems Being Solved

1. **Bad phrasing:** The 1.5s timer dispatches arbitrary word-count deltas (e.g. "und schön") which produce nonsensical English when translated in isolation. German word order differs fundamentally from English.

2. **Audio bursts + gaps:** `TTSSynthesizer` calls `speak_text_async().get()`, waits for complete synthesis, then dumps all 4KB chunks at once. Combined with the `_tts_lock`, this produces: silence → burst → silence → burst.

---

## Architecture Overview

```
Azure STT (de-DE)
  ├─ recognizing events → accumulate interim text, start 4s time cap
  └─ recognized event (or time cap) → dispatch full utterance
        │
        ▼
LLMTranslator (GPT-4o mini, single call)
  ├─ Input: raw_de + last 5 utterances as context
  └─ Output: {clean_de, en_text}
        │
        ▼
Operator console ← status: {raw_de, clean_de, en_text}
        │
        ▼
TTSSynthesizer (Azure Speech SDK)
  ├─ synthesizing event → stream audio chunks to PubSub as generated
  └─ Serialized by _tts_lock (one utterance at a time)
        │
        ▼
Web PubSub → Listener browser (unchanged)
```

---

## Section 1: STT Changes

**Remove:** Timer-based word-count chunking (`_last_word_count`, `_chunk_interval`, recurring `threading.Timer`, `stt_chunk_interval_s` config field).

**Keep:** `recognized` events as the primary dispatch trigger. These fire at natural clause/sentence boundaries, controlled by `Speech_SegmentationSilenceTimeoutMs`. Increased from 500 to 1000ms default to ride through brief mid-sentence pauses (the speaker is quick). Made configurable via `STT_SILENCE_TIMEOUT_MS` env var.

**Add:** A 4-second time cap safety valve. If no `recognized` event fires within 4 seconds of the first `recognizing` event in a sequence, force-dispatch whatever interim text has accumulated. This handles speakers who don't pause. The cap timer resets after each dispatch (whether by `recognized` or by cap).

**Implementation:**
- `_interim_text: str` — updated on each `recognizing` event
- `_cap_timer: Optional[threading.Timer]` — single-shot 4s timer, started on first `recognizing` after a dispatch, cancelled on `recognized`
- `_on_recognized(evt)` — dispatch `evt.result.text` if `RecognizedSpeech`, cancel cap timer, clear state
- `_on_cap_timeout()` — dispatch `_interim_text`, clear state
- Callback: `on_text(raw_de: str)` — unchanged signature

**Config:**
- `stt_time_cap_s: float` (default `4.0`, env var `STT_TIME_CAP_S`)
- `stt_silence_timeout_ms: int` (default `1000`, env var `STT_SILENCE_TIMEOUT_MS`)

---

## Section 2: LLM Combined Cleaning + Translation with Context Window

**Remove:** `backend/llm_cleaner.py` and `backend/text_translator.py`. Remove `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION` from config. Remove `httpx` dependency.

**Create:** `backend/llm_translator.py` — `LLMTranslator` class.

**Context window:** A `collections.deque(maxlen=N)` of recent `(clean_de, en_text)` tuples. Default `N=5`, configurable via `LLM_CONTEXT_WINDOW` env var.

**Single async method:**
```python
async def translate(self, raw_de: str) -> dict:
    """Returns {"clean_de": str, "en_text": str}"""
```

**Prompt structure:**
```
System: You process live German sermon transcript for real-time translation.
Clean the new chunk: remove fillers (ähm, äh, hm, also/ja/ne/sozusagen/irgendwie/halt
when used as fillers), false starts, and immediately repeated words.
Then translate to natural English. Preserve theological vocabulary.
Return JSON only: {"clean_de": "...", "en_text": "..."}
If input is pure filler or empty, return {"clean_de": "", "en_text": ""}

Recent context (for reference only — do NOT re-translate):
[1] "Die Gnade Gottes ist überall" → "The grace of God is everywhere"
[2] "Und wenn wir das verstehen" → "And when we understand that"

New chunk to process:
"Ähm das bedeutet also für uns äh ganz konkret"
```

**After successful call:** Append `(clean_de, en_text)` to the deque.

**Response parsing:** `response_format={"type": "json_object"}` to enforce JSON output. Parse with `json.loads()`.

**Fallback on failure:** Return `{"clean_de": raw_de, "en_text": raw_de}` and let the caller surface a status message.

**Config additions:**
- `llm_context_window: int` (default `5`, env var `LLM_CONTEXT_WINDOW`)

---

## Section 3: TTS Streaming via `synthesizing` Event

**Remove:** `_CHUNK_SIZE = 4096` constant and the post-hoc slicing loop in `synthesize()`.

**Change:** Use the `synthesizing` event callback on `SpeechSynthesizer` to stream audio chunks as they're generated during synthesis.

```python
def synthesize(self, text: str, on_audio_chunk: Callable[[bytes], None]) -> None:
    def on_synthesizing(evt):
        if evt.result.audio_data:
            on_audio_chunk(evt.result.audio_data)

    self._synthesizer.synthesizing.connect(on_synthesizing)
    result = self._synthesizer.speak_text_async(text).get()
    self._synthesizer.synthesizing.disconnect_all()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError(f"TTS failed: {result.reason}")
```

Chunks arrive at natural synthesis pacing — no artificial timing needed.

**Keep:** `_tts_lock` in `SessionHandler` to prevent concurrent utterances from interleaving audio.

---

## Section 4: SessionHandler Orchestration

**Pipeline per `recognized` event:**

```
on_text(raw_de)
  → _process_chunk(raw_de)
    → llm_translator.translate(raw_de)  →  {clean_de, en_text}
    → send status {type: "phrase", raw_de, clean_de, en_text} to operator
    → publish phrase text to PubSub (for listener subtitle display)
    → acquire _tts_lock
    → run TTS in executor with streaming callback → publish_audio directly
    → release _tts_lock
```

**Simplification:** Since TTS runs in an executor thread and `PubSubPublisher.publish_audio` is synchronous, the `synthesizing` callback calls `publish_audio` directly — no `run_coroutine_threadsafe` bounce needed for audio chunks.

**Constructor changes:**
- Remove: `translator_key`, `translator_region`, `chunk_interval` params
- Add: `context_window` param (int, default 5)
- Replace `self._cleaner` + `self._translator` with `self._llm_translator`

**Remove:** `_publish_chunk` async method (no longer needed).

---

## Section 5: Config and Dependencies

**Config removals:**
- `azure_translator_key`, `azure_translator_region`
- `stt_chunk_interval_s`
- Corresponding env var validation

**Config additions:**
- `stt_time_cap_s: float` (default `4.0`, env `STT_TIME_CAP_S`)
- `stt_silence_timeout_ms: int` (default `1000`, env `STT_SILENCE_TIMEOUT_MS`)
- `llm_context_window: int` (default `5`, env `LLM_CONTEXT_WINDOW`)

**Dependency changes (`requirements.txt`):**
- Remove: `httpx`
- Keep: `openai>=1.30`

**`.env.example`:** Remove translator vars, add `STT_TIME_CAP_S`, `STT_SILENCE_TIMEOUT_MS`, and `LLM_CONTEXT_WINDOW` as commented defaults.

---

## Section 6: Operator Console

Phrase status messages change shape from `{type, text}` to `{type, raw_de, clean_de, en_text}`.

The operator console displays all three fields stacked so the user can diagnose whether issues originate in STT, cleaning, or translation:

```
raw_de:   "Ähm das bedeutet also für uns äh ganz konkret"
clean_de: "Das bedeutet für uns ganz konkret"
en_text:  "That means for us very concretely"
```

Minor change to existing phrase display rendering in the operator app.

---

## Section 7: Testing

**New/rewritten test files:**
- `tests/backend/test_stt.py` — recognized-event dispatch, 4s time cap, interim accumulation
- `tests/backend/test_llm_translator.py` — structured JSON return, context window deque, fallback on error
- `tests/backend/test_tts.py` — `synthesizing` event connected, on_audio_chunk receives streaming data
- `tests/backend/test_session.py` — full pipeline with LLMTranslator, verify status includes raw_de/clean_de/en_text
- `tests/backend/test_config.py` — new/removed fields
- `tests/backend/test_main.py` — updated env dicts

**Deleted:**
- `tests/backend/test_llm_cleaner.py`
- `tests/backend/test_text_translator.py`

---

## Files Changed Summary

| File | Action |
|------|--------|
| `backend/stt.py` | Rewrite — recognized-event + time cap |
| `backend/llm_translator.py` | Create — combined clean + translate |
| `backend/tts.py` | Modify — synthesizing event streaming |
| `backend/session.py` | Modify — new pipeline orchestration |
| `backend/config.py` | Modify — add/remove fields |
| `backend/main.py` | Modify — pass new config fields |
| `backend/llm_cleaner.py` | Delete |
| `backend/text_translator.py` | Delete |
| `operator/app.js` | Modify — display raw_de/clean_de/en_text |
| `tests/backend/test_stt.py` | Rewrite |
| `tests/backend/test_llm_translator.py` | Create |
| `tests/backend/test_tts.py` | Rewrite |
| `tests/backend/test_session.py` | Rewrite |
| `tests/backend/test_config.py` | Modify |
| `tests/backend/test_main.py` | Modify |
| `tests/backend/test_llm_cleaner.py` | Delete |
| `tests/backend/test_text_translator.py` | Delete |
| `requirements.txt` | Modify — remove httpx |
| `.env.example` | Modify |
| `docs/azure-setup.md` | Modify — remove Translator section |

---

## Latency Estimate

| Stage | Time |
|-------|------|
| STT silence detection | ~1000ms |
| LLM clean + translate | ~400ms |
| TTS first audio byte | ~200ms |
| **Total to first audio** | **~1.6s per utterance** |

Well within the 5-second budget. The 4s time cap is the worst case for continuous speech without pauses.

---

## Listener — No Changes

The listener ([listener/app.js](listener/app.js)) already schedules PCM chunks sequentially via `nextPlayTime = startAt + audioBuffer.duration`. Naturally-paced streaming chunks from TTS will produce smooth playback without modification.
