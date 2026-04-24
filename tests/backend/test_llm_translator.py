import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

ENGLISH_ONLY = [{"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"}]
TWO_LANGS = [
    {"code": "en", "name": "English", "voice": "en-US-AndrewNeural", "llm_key": "en_text"},
    {"code": "es", "name": "Spanish", "voice": "es-ES-ElviraNeural", "llm_key": "es_text"},
]


def _make_mock_response(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_clean_src_and_lang_keys(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Das ist gut", "en_text": "That is good", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Ähm das ist gut")

    assert result["clean_src"] == "Das ist gut"
    assert result["en_text"] == "That is good"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_empty_input_returns_empty_without_api_call(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("   ")

    assert result["clean_src"] == ""
    assert result["en_text"] == ""
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_all_target_language_keys(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Guten Tag", "en_text": "Good day", "es_text": "Buen día", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=TWO_LANGS)
    result = await translator.translate("Guten Tag")

    assert result["en_text"] == "Good day"
    assert result["es_text"] == "Buen día"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_stores_pending_and_sends_in_next_call(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_src": "Und Jesus", "en_text": "And Jesus", "pending": "subject introduced, verb expected"}'),
        _make_mock_response('{"clean_src": "sagte uns", "en_text": "told us", "pending": ""}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

    await translator.translate("Und Jesus")
    assert translator._pending == "subject introduced, verb expected"

    await translator.translate("sagte uns")
    second_call = mock_client.chat.completions.create.call_args_list[1]
    user_msg = second_call.kwargs["messages"][-1]["content"]
    assert "subject introduced, verb expected" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_clears_pending_when_empty(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Fertig", "en_text": "Done", "pending": ""}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    translator._pending = "some prior arc"
    await translator.translate("Fertig")

    assert translator._pending == ""


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_builds_context_window(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    responses = [
        _make_mock_response('{"clean_src": "Satz eins", "en_text": "Sentence one", "pending": ""}'),
        _make_mock_response('{"clean_src": "Satz zwei", "en_text": "Sentence two", "pending": ""}'),
    ]
    mock_client.chat.completions.create = AsyncMock(side_effect=responses)

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY, context_window=5)

    await translator.translate("Satz eins")
    await translator.translate("Satz zwei")

    second_call = mock_client.chat.completions.create.call_args_list[1]
    user_msg = second_call.kwargs["messages"][-1]["content"]
    assert "Satz eins" in user_msg
    assert "Sentence one" in user_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_context_window_limited(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY, context_window=2)

    for i in range(3):
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                json.dumps({"clean_src": f"Satz {i}", "en_text": f"Sentence {i}", "pending": ""})
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
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

    with pytest.raises(Exception, match="timeout"):
        await translator.translate("Das ist gut")


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_error_does_not_update_context(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)

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
        return_value=_make_mock_response('{"clean_src": "", "en_text": "", "pending": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Ähm äh")

    assert result["clean_src"] == ""
    assert result["en_text"] == ""
    assert len(translator._context) == 0


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_system_prompt_lists_all_target_languages(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response('{"clean_src": "x", "en_text": "x", "es_text": "x", "pending": ""}')
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=TWO_LANGS)
    await translator.translate("test")

    call_args = mock_client.chat.completions.create.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "en_text" in system_msg
    assert "es_text" in system_msg


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_returns_tone_field(mock_client_class):
    """translate() includes a 'tone' key in the result dict."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Gott liebt euch", "en_text": "God loves you", "pending": "", "tone": "warm"}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Gott liebt euch")

    assert result["tone"] == "warm"


@pytest.mark.asyncio
@patch("backend.llm_translator.AsyncAzureOpenAI")
async def test_translate_unknown_tone_defaults_to_calm(mock_client_class):
    """An unrecognised tone value from the LLM is coerced to 'calm'."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response(
            '{"clean_src": "Test", "en_text": "Test", "pending": "", "tone": "LOUDLY"}'
        )
    )

    from backend.llm_translator import LLMTranslator
    translator = LLMTranslator("https://ep", "key", "gpt-4o-mini", target_languages=ENGLISH_ONLY)
    result = await translator.translate("Test")

    assert result["tone"] == "calm"
