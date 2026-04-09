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
