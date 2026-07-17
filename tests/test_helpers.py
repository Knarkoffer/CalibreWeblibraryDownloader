import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import argument_to_list, filter_and_sort, fix_windows_filenames


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
        self.assertEqual(fix_windows_filenames('a<b>c:d"e/f\\g|h?i*j'), "abcdefghij")


if __name__ == "__main__":
    unittest.main()
