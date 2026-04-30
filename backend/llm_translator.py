import asyncio
import json
import logging
import time
from collections import deque

import openai
from openai import AsyncAzureOpenAI
from openai import OpenAI

log = logging.getLogger("gibberly.llm")

_VALID_TONES = {"calm", "warm", "urgent", "emphatic", "joyful", "solemn", "questioning"}


class ContentFilterError(Exception):
    """Azure OpenAI content policy blocked this chunk.

    The context window has already been cleared by the time this is raised,
    so the next call will not carry the triggering content forward.
    """
    pass


def _build_system_prompt(target_languages: list[dict]) -> str:
    lang_keys = "\n".join(
        f'- {lang["llm_key"]}: natural {lang["name"]} interpretation'
        for lang in target_languages
    )
    return f"""\
You process live evangelical sermon transcript, informal, extemporaneous speech for real-time interpretation.

## Your task
You receive a NEW CHUNK of transcript (possibly mid-sentence or a sentence fragment).
Interpret it into natural, complete phrases in each target language.
Even if the chunk is a sentence fragment, produce complete natural phrases by inferring
the speaker's meaning from context. Do not translate literally — interpret based on your knowledge
of the Bible and Christian theology including vocabulary for the particular target language. 
If it seems incorrect given the context then you probably misheard.

The text has been machine-transcribed and may contain transcription errors.
Try to correct them if the meaning seems out of context (e.g. "impossible" transcribed
as "possible" — catch those). If correction is uncertain, lean towards a more theologically meaningful
interpretation given the recent context.

The context lines are shown so you can maintain consistent vocabulary and understand
sentence flow — they have already been broadcast. DO NOT include context in your output.
Target vocabulary for young adults and non-native speakers. Be concise but natural.

## Cleaning rules
Remove spoken fillers (ähm, äh, hm, also/ja/ne/sozusagen/irgendwie/halt when used as
fillers), false starts, immediately repeated words and short phrases. If the entire input is filler,
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
        # self._client = AsyncAzureOpenAI(
        #     azure_endpoint=endpoint,
        #     api_key=api_key,
        #     api_version="2025-04-01-preview",
        #     max_retries=0,
        # )
        self._client = OpenAI(
            base_url=endpoint,
            api_key=api_key,
        )
        self._deployment = deployment
        self._target_languages = target_languages
        self._system_prompt = _build_system_prompt(target_languages)
        self._context: deque[tuple[str, str]] = deque(maxlen=context_window)
        self._pending: str = ""
        self._call_count = 0

        # Reference language key for context storage (prefer English)
        ref_keys = [lang["llm_key"] for lang in target_languages if lang["code"] == "en"]
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
            log.debug("LLM skipping empty/whitespace chunk")
            result = {"clean_src": "", "tone": "calm"}
            for lang in self._target_languages:
                result[lang["llm_key"]] = ""
            return result

        self._call_count += 1
        call_num = self._call_count
        word_count = len(raw.split())
        ctx_size = len(self._context)
        log.info(
            "LLM call #%d — %d words, ctx=%d/%d%s",
            call_num, word_count, ctx_size, self._context.maxlen,
            f", pending={self._pending!r}" if self._pending else "",
        )

        # Retry only APIConnectionError (fast TCP-level drops, ~20ms).
        # APITimeoutError is never retried — 5s already spent; let session fall back.
        _MAX_CONN_RETRIES = 2
        _CONN_RETRY_DELAY_S = 0.5

        t0 = time.monotonic()
        response = None
        for _attempt in range(_MAX_CONN_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._deployment,
                    messages=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": self._build_user_message(raw)},
                    ],
                    temperature=1,
                    max_completion_tokens=max(512, len(raw.split()) * 12 * len(self._target_languages)),
                    response_format={"type": "json_object"},
                    timeout=10.0,
                )
                break  # success
            except openai.BadRequestError as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                # Detect Azure content filter blocks — distinct from API errors
                body = exc.body or {}
                err = body.get("error", {}) if isinstance(body, dict) else {}
                if err.get("code") == "content_filter":
                    inner = err.get("innererror", {}).get("content_filter_result", {})
                    triggered = [
                        f"{cat}({v.get('severity','?')})"
                        for cat, v in inner.items()
                        if isinstance(v, dict) and v.get("filtered")
                    ]
                    ctx_before = len(self._context)
                    self._context.clear()
                    self._pending = ""
                    log.warning(
                        "LLM call #%d content filter blocked after %.0fms — "
                        "categories=%s. Cleared context (%d entries) and pending to prevent "
                        "persistent filtering on subsequent chunks.",
                        call_num, elapsed_ms, triggered, ctx_before,
                    )
                    raise ContentFilterError(f"content_filter: {triggered}") from exc
                log.error("LLM call #%d bad request after %.0fms: %s", call_num, elapsed_ms, exc)
                raise
            except openai.APIConnectionError as exc:
                attempt_ms = (time.monotonic() - t0) * 1000
                if _attempt < _MAX_CONN_RETRIES:
                    log.warning(
                        "LLM call #%d connection error after %.0fms (attempt %d/%d) — "
                        "retrying in %.0fms: %s",
                        call_num, attempt_ms, _attempt + 1, _MAX_CONN_RETRIES + 1,
                        _CONN_RETRY_DELAY_S * 1000, exc,
                    )
                    await asyncio.sleep(_CONN_RETRY_DELAY_S)
                else:
                    elapsed_ms = (time.monotonic() - t0) * 1000
                    log.error("LLM call #%d failed after %.0fms: %s", call_num, elapsed_ms, exc)
                    raise
            except Exception as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                log.error("LLM call #%d failed after %.0fms: %s", call_num, elapsed_ms, exc)
                raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        usage = response.usage
        if usage:
            details = getattr(usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) or 0
            log.info(
                "LLM call #%d — %.0fms | prompt=%d (cached=%d) completion=%d total=%d tokens",
                call_num, elapsed_ms,
                usage.prompt_tokens, cached, usage.completion_tokens, usage.total_tokens,
            )
        else:
            log.info("LLM call #%d — %.0fms (no usage info)", call_num, elapsed_ms)

        if elapsed_ms > 3000:
            log.warning(
                "LLM call #%d slow — %.0fms. This may cause a visible text delay for listeners.",
                call_num, elapsed_ms,
            )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content (possible content filter or token limit)")
        parsed = json.loads(content.strip())
        clean_src = parsed.get("clean_src", "")
        self._pending = parsed.get("pending", "")

        if not clean_src:
            log.info("LLM call #%d — chunk filtered to empty (filler/false start)", call_num)

        raw_tone = parsed.get("tone", "calm")
        tone = raw_tone if raw_tone in _VALID_TONES else "calm"
        if raw_tone not in _VALID_TONES:
            log.warning("LLM call #%d — unknown tone %r, defaulting to calm", call_num, raw_tone)

        result = {"clean_src": clean_src, "tone": tone}
        for lang in self._target_languages:
            result[lang["llm_key"]] = parsed.get(lang["llm_key"], "")

        if clean_src:
            self._context.append((clean_src, result.get(self._ref_key, "")))

        return result
