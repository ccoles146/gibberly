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
