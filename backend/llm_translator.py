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
