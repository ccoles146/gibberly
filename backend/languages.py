# SUPPORTED_LANGUAGES = [
#     {"code": "en", "name": "English",    "voice": "en-US-AndrewNeural",    "llm_key": "en_text"},
#     {"code": "de", "name": "German",     "voice": "de-DE-KatjaNeural",     "llm_key": "de_text"},
#     {"code": "es", "name": "Spanish",    "voice": "es-ES-ElviraNeural",    "llm_key": "es_text"},
#     {"code": "fr", "name": "French",     "voice": "fr-FR-DeniseNeural",    "llm_key": "fr_text"},
#     {"code": "hr", "name": "Croatian",   "voice": "hr-HR-GabrijelaNeural", "llm_key": "hr_text"},
#     {"code": "pt", "name": "Portuguese", "voice": "pt-BR-FranciscaNeural", "llm_key": "pt_text"},
#     {"code": "pl", "name": "Polish",     "voice": "pl-PL-ZofiaNeural",     "llm_key": "pl_text"},
#     {"code": "ro", "name": "Romanian",   "voice": "ro-RO-AlinaNeural",     "llm_key": "ro_text"},
#     {"code": "uk", "name": "Ukrainian",  "voice": "uk-UA-PolinaNeural",    "llm_key": "uk_text"},
# ]
SUPPORTED_LANGUAGES = [
    {"code": "en", "name": "English",    "voice": "en-US-AndrewNeural",    "llm_key": "en_text"},
    {"code": "de", "name": "German",     "voice": "de-DE-KatjaNeural",     "llm_key": "de_text"},
    {"code": "es", "name": "Spanish",    "voice": "es-ES-ElviraNeural",    "llm_key": "es_text"},
    {"code": "fr", "name": "French",     "voice": "fr-FR-DeniseNeural",    "llm_key": "fr_text"},
    {"code": "hr", "name": "Croatian",   "voice": "hr-HR-GabrijelaNeural", "llm_key": "hr_text"},
]

def get_target_languages(source_lang_code: str) -> list[dict]:
    """Return SUPPORTED_LANGUAGES excluding the entry matching source_lang_code."""
    return [lang for lang in SUPPORTED_LANGUAGES if lang["code"] != source_lang_code]
