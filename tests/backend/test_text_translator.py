import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


def _make_translator():
    from backend.text_translator import TextTranslator
    return TextTranslator("tr-key", "westeurope")


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_english_text(mock_client_class):
    mock_response = MagicMock()
    mock_response.json.return_value = [{"translations": [{"text": "God is good."}]}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    result = asyncio.run(translator.translate("Gott ist gut."))
    assert result == "God is good."


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_for_empty_input(mock_client_class):
    translator = _make_translator()
    result = asyncio.run(translator.translate(""))
    assert result is None
    mock_client_class.assert_not_called()


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_for_whitespace_input(mock_client_class):
    translator = _make_translator()
    result = asyncio.run(translator.translate("   "))
    assert result is None
    mock_client_class.assert_not_called()


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_returns_none_on_http_error(mock_client_class):
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    result = asyncio.run(translator.translate("Gott ist gut."))
    assert result is None


@patch("backend.text_translator.httpx.AsyncClient")
def test_translate_sends_correct_headers(mock_client_class):
    mock_response = MagicMock()
    mock_response.json.return_value = [{"translations": [{"text": "God is good."}]}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    translator = _make_translator()
    asyncio.run(translator.translate("Gott ist gut."))

    call_kwargs = mock_client.post.call_args
    headers = call_kwargs.kwargs["headers"]
    assert headers["Ocp-Apim-Subscription-Key"] == "tr-key"
    assert headers["Ocp-Apim-Subscription-Region"] == "westeurope"
