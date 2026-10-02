"""Kode bahasa (ISO 639-1, sama seperti yang dipakai Whisper) -> nama bahasa dalam Inggris.

Nama bahasa dipakai di prompt TranslateGemma, label dipakai di UI.
"""

LANGUAGES = {
    "id": "Indonesian",
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "ms": "Malay",
    "tl": "Tagalog",
    "jw": "Javanese",
    "su": "Sundanese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "uk": "Ukrainian",
    "pl": "Polish",
    "cs": "Czech",
    "sk": "Slovak",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sr": "Serbian",
    "sl": "Slovenian",
    "da": "Danish",
    "sv": "Swedish",
    "no": "Norwegian",
    "fi": "Finnish",
    "et": "Estonian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "tr": "Turkish",
    "fa": "Persian",
    "he": "Hebrew",
    "ur": "Urdu",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "sw": "Swahili",
    "af": "Afrikaans",
    "ca": "Catalan",
    "km": "Khmer",
    "lo": "Lao",
    "my": "Burmese",
}


def language_name(code):
    return LANGUAGES.get(code, code)


# Label untuk UI: nama asli bahasa (seperti di mockup); selain ini memakai nama Inggris.
_LABELS = {
    "id": "Bahasa Indonesia", "en": "English", "ja": "日本語", "zh": "中文", "ko": "한국어",
    "ar": "العربية", "hi": "हिन्दी", "th": "ไทย", "vi": "Tiếng Việt", "ms": "Bahasa Melayu",
    "jw": "Basa Jawa", "su": "Basa Sunda", "fr": "Français", "de": "Deutsch", "es": "Español",
    "pt": "Português", "it": "Italiano", "nl": "Nederlands", "ru": "Русский", "tr": "Türkçe",
    "pl": "Polski",
}
# Urutan di atas daftar (paling sering dipakai), sisanya abjad.
POPULAR = ["id", "en", "ja", "zh", "ko", "ar", "ms", "th", "vi", "es", "fr", "de"]


def language_label(code):
    return _LABELS.get(code, LANGUAGES.get(code, code))


def sorted_codes(codes):
    codes = list(codes)
    top = [c for c in POPULAR if c in codes]
    rest = sorted((c for c in codes if c not in top), key=language_label)
    return top + rest
