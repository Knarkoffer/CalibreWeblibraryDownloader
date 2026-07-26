import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import (
    add_item_to_db,
    book_source_key,
    downloaded_book_keys,
    downloaded_book_keys_for_calibre_server,
    ensure_database,
)

BOOK_DETAILS = {
    "file_hash": "ABC123",
    "title": "Example",
    "author_sort": "Author, Example",
    "language": "English",
    "identifiers": "isbn:123",
    "tags": "Fiction",
    "format": "EPUB",
    "filename": "example.epub",
    "size": 123,
    "calibre_address": "http://example.com",
    "date_added": "2026-07-16",
}


class DatabaseTestCase(unittest.TestCase):
    def test_ensure_database_creates_books_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "books.sqlite"
            ensure_database(str(database_file))

            with sqlite3.connect(database_file) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name = 'BOOKS'"
                ).fetchone()[0]
                columns = [
                    row[1]
                    for row in connection.execute("PRAGMA table_info(BOOKS)").fetchall()
                ]

            self.assertEqual(count, 1)
            self.assertEqual(
                columns,
                [
                    "file_hash",
                    "title",
                    "author_sort",
                    "language",
                    "identifiers",
                    "tags",
                    "format",
                    "filename",
                    "size",
                    "calibre_address",
                    "date_added",
                ],
            )

    def test_add_item_to_db_inserts_and_skips_duplicate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "books.sqlite"

            self.assertTrue(add_item_to_db(str(database_file), BOOK_DETAILS))
            self.assertFalse(add_item_to_db(str(database_file), BOOK_DETAILS))

            with sqlite3.connect(database_file) as connection:
                count = connection.execute("SELECT COUNT(*) FROM BOOKS").fetchone()[0]
                row = connection.execute(
                    "SELECT file_hash, title, format, filename, size FROM BOOKS"
                ).fetchone()

            self.assertEqual(count, 1)
            self.assertEqual(row, ("ABC123", "Example", "EPUB", "example.epub", 123))

    def test_book_source_key_normalizes_format(self):
        self.assertEqual(
            book_source_key("Example", "Author, Example", "epub", 123),
            ("Example", "Author, Example", "EPUB", 123),
        )

    def test_downloaded_book_keys_for_calibre_server_matches_source_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "books.sqlite"
            self.assertTrue(add_item_to_db(str(database_file), BOOK_DETAILS))

            self.assertEqual(
                downloaded_book_keys_for_calibre_server(
                    str(database_file),
                    "http://example.com",
                ),
                {("Example", "Author, Example", "EPUB", 123)},
            )
            self.assertEqual(
                downloaded_book_keys_for_calibre_server(
                    str(database_file),
                    "http://other.example.com",
                ),
                set(),
            )

    def test_downloaded_book_keys_returns_all_source_metadata(self):
        other_book_details = dict(
            BOOK_DETAILS,
            file_hash="DEF456",
            title="Other",
            author_sort="Writer, Other",
            size=456,
            calibre_address="http://other.example.com",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "books.sqlite"
            self.assertTrue(add_item_to_db(str(database_file), BOOK_DETAILS))
            self.assertTrue(add_item_to_db(str(database_file), other_book_details))

            self.assertEqual(
                downloaded_book_keys(str(database_file)),
                {
                    ("Example", "Author, Example", "EPUB", 123),
                    ("Other", "Writer, Other", "EPUB", 456),
                },
            )


if __name__ == "__main__":
    unittest.main()
