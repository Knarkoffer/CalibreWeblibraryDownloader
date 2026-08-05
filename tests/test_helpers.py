import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import (
    MAX_FILENAME_BYTES,
    argument_to_list,
    ascii_filename_segment,
    filter_and_sort,
    fix_windows_filenames,
)


class HelpersTestCase(unittest.TestCase):
    def test_argument_to_list_splits_and_trims_values(self):
        self.assertEqual(argument_to_list("one, two,,three "), ["one", "two", "three"])

    def test_argument_to_list_reads_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("one\n\ntwo\n")
            path = handle.name
        try:
            self.assertEqual(argument_to_list(path), ["one", "two"])
        finally:
            os.unlink(path)

    def test_filter_and_sort_uses_preferred_order(self):
        self.assertEqual(
            filter_and_sort(["mobi", "pdf", "epub"], ["epub", "mobi"]),
            ["epub", "mobi"],
        )

    def test_fix_windows_filenames_removes_reserved_characters(self):
        self.assertEqual(
            fix_windows_filenames("a!b<c>d:e\"f/g\\h|i?j*k'l"),
            "abcdefghijkl",
        )

    def test_fix_windows_filenames_keeps_only_utf8_printable_characters(self):
        self.assertEqual(
            fix_windows_filenames("Ångström\n\ud800 Book"), "Ångström Book"
        )

    def test_fix_windows_filenames_collapses_chained_spaces(self):
        self.assertEqual(fix_windows_filenames("Hello  From   Me"), "Hello From Me")

    def test_fix_windows_filenames_removes_emoji_like_symbols(self):
        self.assertEqual(
            fix_windows_filenames("Ångström 📚 Family 👨‍👩‍👧‍👦 Key 1️⃣ ©™ ★.epub"),
            "Ångström Family Key 1 .epub",
        )

    def test_fix_windows_filenames_handles_windows_edge_cases(self):
        self.assertEqual(fix_windows_filenames("CON.epub"), "_CON.epub")
        self.assertEqual(fix_windows_filenames("Book. "), "Book")

    def test_fix_windows_filenames_limits_utf8_byte_length(self):
        filename = fix_windows_filenames(f"{'Å' * 300}.epub")

        self.assertLessEqual(len(filename.encode("utf-8")), MAX_FILENAME_BYTES)
        self.assertTrue(filename.endswith(".epub"))

    def test_fix_windows_filenames_preserves_explicit_suffix_when_truncated(self):
        suffix = " [36AD266D607757AF357D59FE0A1A4277].epub"
        filename = fix_windows_filenames(f"{'Long Author ' * 40}{suffix}", suffix)

        self.assertLessEqual(len(filename.encode("utf-8")), MAX_FILENAME_BYTES)
        self.assertTrue(filename.endswith(suffix))

    def test_ascii_filename_segment_keeps_only_safe_ascii_characters(self):
        self.assertEqual(ascii_filename_segment("12/å!|'B\n"), "12B")
        self.assertEqual(ascii_filename_segment("/å|\n"), "unknown")


if __name__ == "__main__":
    unittest.main()
