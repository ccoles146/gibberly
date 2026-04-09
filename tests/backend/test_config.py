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
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
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
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_SPEECH_KEY"):
            _load()


def test_config_loads_new_azure_fields():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.azure_openai_endpoint == "https://my-openai.openai.azure.com/"
        assert s.azure_openai_api_key == "oai-key"
        assert s.azure_openai_deployment == "gpt-4o-mini"
        assert s.azure_translator_key == "tr-key"
        assert s.azure_translator_region == "westeurope"
        assert s.stt_chunk_interval_s == 1.5  # default


def test_config_chunk_interval_from_env():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_ENDPOINT": "https://my-openai.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
        "STT_CHUNK_INTERVAL_S": "2.0",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        s = _load()
        assert s.stt_chunk_interval_s == 2.0


def test_config_raises_on_missing_openai_endpoint():
    env = {
        "AZURE_SPEECH_KEY": "sk",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://x.webpubsub.azure.com;AccessKey=a;Version=1.0;",
        "AZURE_OPENAI_API_KEY": "oai-key",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini",
        "AZURE_TRANSLATOR_KEY": "tr-key",
        "AZURE_TRANSLATOR_REGION": "westeurope",
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            _load()
