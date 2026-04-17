import os
import pytest
from unittest.mock import patch


def test_config_loads_from_env():
    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc123;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "BACKEND_HOST": "0.0.0.0",
        "BACKEND_PORT": "8000",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        settings = _load()
        assert settings.azure_speech_key == "test-key"
        assert settings.azure_speech_region == "westeurope"
        assert settings.backend_port == 8000


def test_config_raises_on_missing_speech_key():
    env = {
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_SPEECH_KEY"):
            _load()


def test_config_defaults():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.stt_silence_timeout_ms == 1000
        assert s.stt_time_cap_s == 8.0
        assert s.llm_context_window == 5


def test_config_overrides_from_env():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "STT_SILENCE_TIMEOUT_MS": "1500",
        "STT_TIME_CAP_S": "5.0",
        "LLM_CONTEXT_WINDOW": "8",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.stt_silence_timeout_ms == 1500
        assert s.stt_time_cap_s == 5.0
        assert s.llm_context_window == 8


def test_config_raises_on_missing_openai_endpoint():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            _load()
