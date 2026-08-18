import unittest

from voicely_languages import (
    normalize_language_tag,
    parse_languages,
    validate_translation_response,
)


class LanguageTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_language_tags(self):
        self.assertEqual(normalize_language_tag("zh_hant_tw"), "zh-Hant-TW")
        self.assertEqual(parse_languages("EN, en, pt_br"), ["en", "pt-BR"])

    def test_malformed_translation_response_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_translation_response([], ["en", "es"])

    def test_unknown_original_falls_back_and_filters_translations(self):
        result = validate_translation_response(
            {"original_language": "xx", "translations": {"ES": "Hola", "xx": "x"}},
            ["en", "es"],
        )
        self.assertEqual(result, {
            "original_language": "en", "translations": {"es": "Hola"}
        })
