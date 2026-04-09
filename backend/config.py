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
    backend_host: str
    backend_port: int
    stt_silence_timeout_ms: int
    stt_time_cap_s: float
    llm_context_window: int


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
        stt_time_cap_s=float(os.environ.get("STT_TIME_CAP_S", "4.0")),
        llm_context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", "5")),
    )


settings = _load()
