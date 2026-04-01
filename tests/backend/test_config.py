import os
import pytest
from unittest.mock import patch


def test_config_loads_from_env():
    env = {
        "AZURE_SPEECH_KEY": "test-key",
        "AZURE_SPEECH_REGION": "westeurope",
        "AZURE_WEBPUBSUB_CONNECTION_STRING": "Endpoint=https://test.webpubsub.azure.com;AccessKey=abc123;Version=1.0;",
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
    }
    with patch.dict(os.environ, env, clear=True):
        from backend.config import _load
        with pytest.raises(ValueError, match="AZURE_SPEECH_KEY"):
            _load()
