import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules import Rule, evaluate_book, explain_book, explain_format_size, validate_rules


class RulesTestCase(unittest.TestCase):
    def test_evaluate_book_handles_missing_application_id(self):
        rules = validate_rules(
            [
                {
                    "name": "Skip Sample",
                    "metadata": "Title",
                    "regex": "Sample",
                    "wanted": False,
                }
            ]
        )

        self.assertFalse(evaluate_book(rules, {"title": "Sample Book"}))

    def test_explain_book_returns_rule_reason(self):
        rules = validate_rules(
            [
                {
                    "name": "Skip Sample",
                    "metadata": "Title",
                    "regex": "Sample",
                    "wanted": False,
                }
            ]
        )

        decision = explain_book(rules, {"title": "Sample Book"})

        self.assertFalse(decision.wanted)
        self.assertEqual(decision.reason, "Skip Sample (Title): Sample Book")

    def test_validate_rules_returns_typed_rules_with_compiled_regex(self):
        rules = validate_rules(
            [
                {
                    "name": "Skip Sample",
                    "metadata": "Title",
                    "regex": "Sample",
                    "wanted": False,
                }
            ]
        )

        self.assertIsInstance(rules[0], Rule)
        self.assertEqual(rules[0].pattern, "Sample")
        self.assertTrue(rules[0].regex.search("Sample Book"))

    def test_validate_rules_accepts_match_all(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "regex": "French",
                    "match": "all",
                    "wanted": False,
                }
            ]
        )

        self.assertEqual(rules[0].match, "all")

    def test_validate_rules_accepts_values(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted authors",
                    "metadata": "Author",
                    "values": ["James Patterson", "Dean Koontz"],
                    "wanted": False,
                }
            ]
        )

        self.assertEqual(rules[0].values, ("James Patterson", "Dean Koontz"))
        self.assertIsNone(rules[0].regex)
        self.assertFalse(rules[0].case_sensitive)

    def test_values_match_exactly_and_case_insensitively_by_default(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted authors",
                    "metadata": "Author",
                    "values": ["James Patterson"],
                    "wanted": False,
                }
            ]
        )

        self.assertFalse(evaluate_book(rules, {"authors": [" james patterson "]}))
        self.assertTrue(evaluate_book(rules, {"authors": ["James Patterson Jr."]}))

    def test_values_can_match_case_sensitively(self):
        rules = validate_rules(
            [
                {
                    "name": "Case-sensitive author",
                    "metadata": "Author",
                    "values": ["calibre"],
                    "case_sensitive": True,
                    "wanted": False,
                }
            ]
        )

        self.assertFalse(evaluate_book(rules, {"authors": ["calibre"]}))
        self.assertTrue(evaluate_book(rules, {"authors": ["Calibre"]}))

    def test_validate_rules_accepts_size_rule(self):
        rules = validate_rules(
            [
                {
                    "name": "Oversized books",
                    "metadata": "Size",
                    "max_mb": 150,
                    "wanted": False,
                }
            ]
        )

        self.assertEqual(rules[0].metadata, "Size")
        self.assertEqual(rules[0].max_mb, 150)
        self.assertIsNone(rules[0].regex)

    def test_validate_rules_accepts_identifier_rule(self):
        rules = validate_rules(
            [
                {
                    "name": "Project Gutenberg books",
                    "metadata": "Identifier",
                    "regex": r"(?i)(^gutenberg:|gutenberg\.org/ebooks/)",
                    "wanted": False,
                }
            ]
        )

        self.assertEqual(rules[0].metadata, "Identifier")
        self.assertTrue(
            rules[0].regex.search("uri:http://www.gutenberg.org/ebooks/46345")
        )

    def test_identifier_rule_matches_mapping_value(self):
        rules = validate_rules(
            [
                {
                    "name": "Project Gutenberg books",
                    "metadata": "Identifier",
                    "regex": r"(?i)(^gutenberg:|gutenberg\.org/ebooks/)",
                    "wanted": False,
                }
            ]
        )

        decision = explain_book(
            rules,
            {"identifiers": {"uri": "http://www.gutenberg.org/ebooks/46345"}},
        )

        self.assertFalse(decision.wanted)
        self.assertEqual(
            decision.reason,
            "Project Gutenberg books (Identifier): "
            "http://www.gutenberg.org/ebooks/46345",
        )

    def test_identifier_rule_matches_raw_identifier_string(self):
        rules = validate_rules(
            [
                {
                    "name": "Project Gutenberg books",
                    "metadata": "Identifier",
                    "regex": r"(?i)(^gutenberg:|gutenberg\.org/ebooks/)",
                    "wanted": False,
                }
            ]
        )

        decision = explain_book(
            rules,
            {"identifiers": "uri:http://www.gutenberg.org/ebooks/46345"},
        )

        self.assertFalse(decision.wanted)
        self.assertEqual(
            decision.reason,
            "Project Gutenberg books (Identifier): "
            "uri:http://www.gutenberg.org/ebooks/46345",
        )

    def test_explain_format_size_rejects_oversized_format(self):
        rules = validate_rules(
            [
                {
                    "name": "Oversized books",
                    "metadata": "Size",
                    "max_mb": 150,
                    "wanted": False,
                }
            ]
        )

        decision = explain_format_size(rules, "epub", 151_000_000)

        self.assertFalse(decision.wanted)
        self.assertEqual(
            decision.reason,
            "Oversized books (Size): EPUB 151 MB > 150 MB",
        )

    def test_validate_rules_rejects_bad_regex(self):
        with self.assertRaises(ValueError):
            validate_rules(
                [
                    {
                        "name": "Bad",
                        "metadata": "Title",
                        "regex": "[",
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_regex_and_values_together(self):
        with self.assertRaisesRegex(ValueError, "exactly one of: regex, values"):
            validate_rules(
                [
                    {
                        "name": "Ambiguous",
                        "metadata": "Author",
                        "regex": "Sample",
                        "values": ["Sample"],
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_empty_values(self):
        with self.assertRaisesRegex(ValueError, "non-empty list of strings"):
            validate_rules(
                [
                    {
                        "name": "Empty",
                        "metadata": "Author",
                        "values": [],
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_non_boolean_case_sensitive(self):
        with self.assertRaisesRegex(ValueError, "case_sensitive must be true or false"):
            validate_rules(
                [
                    {
                        "name": "Bad case sensitivity",
                        "metadata": "Author",
                        "values": ["Sample"],
                        "case_sensitive": "no",
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_size_rule_without_max_mb(self):
        with self.assertRaisesRegex(ValueError, "max_mb must be a positive number"):
            validate_rules(
                [
                    {
                        "name": "Oversized books",
                        "metadata": "Size",
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_unknown_metadata(self):
        with self.assertRaisesRegex(ValueError, "metadata must be one of"):
            validate_rules(
                [
                    {
                        "name": "Bad",
                        "metadata": "Publisher",
                        "regex": "Sample",
                        "wanted": False,
                    }
                ]
            )

    def test_validate_rules_rejects_unknown_match_mode(self):
        with self.assertRaisesRegex(ValueError, "match must be one of"):
            validate_rules(
                [
                    {
                        "name": "Bad",
                        "metadata": "Language",
                        "regex": "French",
                        "match": "none",
                        "wanted": False,
                    }
                ]
            )

    def test_language_rule_defaults_to_any_match(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "regex": "^(French|German)$",
                    "wanted": False,
                }
            ]
        )

        decision = explain_book(
            rules,
            {
                "language_rule_groups": [
                    ["eng", "English"],
                    ["fra", "French"],
                ],
            },
        )

        self.assertFalse(decision.wanted)
        self.assertEqual(decision.reason, "Unwanted languages (Language): French")

    def test_language_rule_match_all_keeps_mixed_wanted_and_unwanted_languages(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "regex": "^(French|German)$",
                    "match": "all",
                    "wanted": False,
                }
            ]
        )

        self.assertTrue(
            explain_book(
                rules,
                {
                    "language_rule_groups": [
                        ["eng", "English"],
                        ["fra", "French"],
                    ],
                },
            ).wanted
        )

    def test_language_rule_match_all_rejects_only_unwanted_languages(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "regex": "^(fra|German)$",
                    "match": "all",
                    "wanted": False,
                }
            ]
        )

        decision = explain_book(
            rules,
            {
                "language_rule_groups": [
                    ["fra", "French"],
                    ["deu", "German"],
                ],
            },
        )

        self.assertFalse(decision.wanted)
        self.assertEqual(
            decision.reason, "Unwanted languages (Language): French, German"
        )

    def test_language_rule_match_all_does_not_reject_missing_languages(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "regex": "^(French|German)$",
                    "match": "all",
                    "wanted": False,
                }
            ]
        )

        self.assertTrue(explain_book(rules, {"language_rule_groups": []}).wanted)

    def test_values_support_language_match_all(self):
        rules = validate_rules(
            [
                {
                    "name": "Unwanted languages",
                    "metadata": "Language",
                    "values": ["French", "German"],
                    "match": "all",
                    "wanted": False,
                }
            ]
        )

        mixed_decision = explain_book(
            rules,
            {
                "language_rule_groups": [
                    ["eng", "English"],
                    ["fra", "French"],
                ],
            },
        )
        unwanted_decision = explain_book(
            rules,
            {
                "language_rule_groups": [
                    ["fra", "French"],
                    ["deu", "German"],
                ],
            },
        )

        self.assertTrue(mixed_decision.wanted)
        self.assertFalse(unwanted_decision.wanted)
        self.assertEqual(
            unwanted_decision.reason,
            "Unwanted languages (Language): French, German",
        )


if __name__ == "__main__":
    unittest.main()
