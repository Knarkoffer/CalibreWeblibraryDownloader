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


if __name__ == "__main__":
    unittest.main()
