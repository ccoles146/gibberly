import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_cleaned_text(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Der Herr ist gut."
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("Ähm, der Herr ist gut."))
    assert result == "Der Herr ist gut."


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_empty_string_for_empty_input(mock_client_class):
    mock_client_class.return_value = MagicMock()

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean(""))
    assert result == ""
    # API must NOT be called for empty input
    mock_client_class.return_value.chat.completions.create.assert_not_called()


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_returns_empty_string_for_whitespace_input(mock_client_class):
    mock_client_class.return_value = MagicMock()

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("   "))
    assert result == ""


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_raises_on_api_error(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    try:
        asyncio.run(cleaner.clean("Test text"))
        assert False, "Expected exception"
    except Exception as e:
        assert "API error" in str(e)


@patch("backend.llm_cleaner.AsyncAzureOpenAI")
def test_clean_strips_whitespace_from_response(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "  Der Herr ist gut.  \n"
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    from backend.llm_cleaner import LLMCleaner
    cleaner = LLMCleaner("https://ep.openai.azure.com/", "key", "gpt-4o-mini")

    result = asyncio.run(cleaner.clean("Ähm, der Herr ist gut."))
    assert result == "Der Herr ist gut."
