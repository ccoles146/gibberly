def test_all_languages_have_required_keys():
    from backend.languages import SUPPORTED_LANGUAGES
    for lang in SUPPORTED_LANGUAGES:
        assert "code" in lang
        assert "name" in lang
        assert "voice" in lang
        assert "llm_key" in lang
        assert lang["llm_key"] == f"{lang['code']}_text"


def test_language_count():
    from backend.languages import SUPPORTED_LANGUAGES
    assert len(SUPPORTED_LANGUAGES) == 5


def test_get_target_languages_excludes_source():
    from backend.languages import get_target_languages
    targets = get_target_languages("de")
    codes = [l["code"] for l in targets]
    assert "de" not in codes
    assert "en" in codes


def test_get_target_languages_excludes_english_source():
    from backend.languages import get_target_languages
    targets = get_target_languages("en")
    codes = [l["code"] for l in targets]
    assert "en" not in codes
    assert "de" in codes


def test_get_target_languages_preserves_order():
    from backend.languages import SUPPORTED_LANGUAGES, get_target_languages
    targets = get_target_languages("xx")  # unknown source — all kept
    assert targets == SUPPORTED_LANGUAGES


def test_no_duplicate_codes():
    from backend.languages import SUPPORTED_LANGUAGES
    codes = [lang["code"] for lang in SUPPORTED_LANGUAGES]
    assert len(codes) == len(set(codes))
