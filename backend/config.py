import os
from dataclasses import dataclass
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
    azure_translator_key: str
    azure_translator_region: str
    backend_host: str
    backend_port: int
    stt_chunk_interval_s: float


def _load() -> Settings:
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    pubsub_cs = os.environ.get("AZURE_WEBPUBSUB_CONNECTION_STRING")
    openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    translator_key = os.environ.get("AZURE_TRANSLATOR_KEY")
    translator_region = os.environ.get("AZURE_TRANSLATOR_REGION")

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
    if not translator_key:
        raise ValueError("AZURE_TRANSLATOR_KEY is required")
    if not translator_region:
        raise ValueError("AZURE_TRANSLATOR_REGION is required")

    return Settings(
        azure_speech_key=key,
        azure_speech_region=region,
        azure_webpubsub_connection_string=pubsub_cs,
        azure_openai_endpoint=openai_endpoint,
        azure_openai_api_key=openai_api_key,
        azure_openai_deployment=openai_deployment,
        azure_translator_key=translator_key,
        azure_translator_region=translator_region,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
        stt_chunk_interval_s=float(os.environ.get("STT_CHUNK_INTERVAL_S", "1.5")),
    )


settings = _load()
