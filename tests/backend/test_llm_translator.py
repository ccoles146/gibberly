import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_response(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_clean_de_and_en_text(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_de": "Das ist gut", "en_text": "That is good"}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("Ähm das ist gut")

    assert result == {"clean_de": "Das ist gut", "en_text": "That is good"}


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_empty_input_returns_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("   ")

    assert result == {"clean_de": "", "en_text": ""}
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_builds_context_window(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_de": "Satz eins", "en_text": "Sentence one"}'),
        _make_mock_response('{"clean_de": "Satz zwei", "en_text": "Sentence two"}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", context_window=5)

    await translator.translate("Satz eins")
    await translator.translate("Ähm Satz zwei")

    second_call = mock_client.chat.completions.create.call_args_list[1]
    messages = second_call.kwargs["messages"]
    user_msg = messages[-1]["content"]
    assert "Satz eins" in user_msg
    assert "Sentence one" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_context_window_limited(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", context_window=2)

    for i in range(3):
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                json.dumps({"clean_de": f"Satz {i}", "en_text": f"Sentence {i}"})
            )
        )
        await translator.translate(f"Satz {i}")

    assert len(translator._context) == 2
    assert translator._context[0] == ("Satz 1", "Sentence 1")
    assert translator._context[1] == ("Satz 2", "Sentence 2")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_raises_on_api_error(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")

    with pytest.raises(Exception, match="timeout"):
        await translator.translate("Das ist gut")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_error_does_not_update_context(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")

    try:
        await translator.translate("Das ist gut")
    except Exception:
        pass

    assert len(translator._context) == 0


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_all_filler_returns_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_de": "", "en_text": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini")
    result = await translator.translate("Ähm äh")

    assert result == {"clean_de": "", "en_text": ""}
    assert len(translator._context) == 0
