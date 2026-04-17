import json
from collections import deque

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
        self._context: deque[tuple[str, str]] = deque(maxlen=context_window)
        self._pending: str = ""

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

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content (possible content filter or token limit)")
        parsed = json.loads(content.strip())
        clean_src = parsed.get("clean_src", "")
        self._pending = parsed.get("pending", "")

        result = {"clean_src": clean_src}
        for lang in self._target_languages:
            result[lang["llm_key"]] = parsed.get(lang["llm_key"], "")

        if clean_src:
            self._context.append((clean_src, result.get(self._ref_key, "")))

        return result
