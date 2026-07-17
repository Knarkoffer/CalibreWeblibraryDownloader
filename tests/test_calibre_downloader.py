import hashlib
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibre_downloader import (
    RunOptions,
    RunStats,
    author_display,
    browse_library,
    configure_logging,
    filter_libraries,
    get_format_details,
    library_display_name,
    load_rules,
    log_library_book_count,
    log_library_list,
    log_summary,
    main,
    normalize_server_address,
    positive_int,
)
from rules import validate_rules


class CalibreDownloaderTestCase(unittest.TestCase):
    def tearDown(self):
        logging.getLogger("urllib3").setLevel(logging.NOTSET)

    def test_normalize_server_address_accepts_hostname_and_strips_slash(self):
        self.assertEqual(
            normalize_server_address("Example.com:8080/"),
            "http://example.com:8080",
        )

    def test_normalize_server_address_rejects_path(self):
        with self.assertRaises(ValueError):
            normalize_server_address("https://example.com/books")

    def test_load_rules_validates_regexes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.yaml"
            rules_file.write_text(
                "\n".join(
                    [
                        "rules:",
                        "  - name: Bad",
                        "    metadata: Title",
                        "    regex: '['",
                        "    wanted: false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_rules(str(rules_file))

    def test_validate_rules_mode_accepts_alternate_rules_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "alternate-rules.yaml"
            rules_file.write_text("rules: []\n", encoding="utf-8")
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["--validate-rules", "--rules", str(rules_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("Rules OK", output.getvalue())

    def test_validate_config_mode_does_not_require_servers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.yaml"
            config_file.write_text(
                """
debug_mode: true
wait_time: 0
timeout: 10
user_agent: Mozilla/5.0
storage_path: downloads
database_file: books.sqlite
logstamp_format: "%(message)s"
target_formats:
  - epub
proxy:
  enabled: false
  proxies: []
""",
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["--validate-config", "--config", str(config_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("Config OK", output.getvalue())

    def test_configure_logging_suppresses_urllib3_without_verbose(self):
        config = SimpleNamespace(
            debug_mode=True,
            logstamp_format="%(message)s",
        )

        configure_logging(config, verbose=False)

        self.assertEqual(logging.getLogger("urllib3").level, logging.WARNING)

    def test_configure_logging_allows_urllib3_with_verbose(self):
        config = SimpleNamespace(
            debug_mode=False,
            logstamp_format="%(message)s",
        )

        configure_logging(config, verbose=True)

        self.assertEqual(logging.getLogger("urllib3").level, logging.DEBUG)

    def test_browse_library_respects_book_limit(self):
        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
        library_content = {
            "1": {"title": "One", "formats": []},
            "2": {"title": "Two", "formats": []},
            "3": {"title": "Three", "formats": []},
        }

        browse_library(
            library_content,
            "http://example.com",
            SimpleNamespace(),
            SimpleNamespace(),
            config,
            [],
            RunOptions(limit=2),
            stats,
        )

        self.assertEqual(stats.books_seen, 2)

    def test_browse_library_converts_languages_before_rules(self):
        class FakeLang:
            def __init__(self, language_code):
                self.name = {"deu": "German"}[language_code]

        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
        library_content = {
            "1": {
                "title": "Buch",
                "formats": ["epub"],
                "languages": ["deu"],
            }
        }
        rules = validate_rules(
            [
                {
                    "name": "Skip German",
                    "metadata": "Language",
                    "regex": "^German$",
                    "wanted": False,
                }
            ]
        )

        with patch("calibre_downloader.Lang", FakeLang):
            browse_library(
                library_content,
                "http://example.com",
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                rules,
                RunOptions(),
                stats,
            )

        self.assertEqual(stats.books_seen, 1)
        self.assertEqual(stats.books_rejected, 1)

    def test_library_display_name_accepts_calibre_library_map_values(self):
        self.assertEqual(library_display_name("Calibre_Library", "Main"), "Main")
        self.assertEqual(
            library_display_name("Calibre_Library", {"name": "Main"}),
            "Main",
        )

    def test_log_library_list_prints_libraries_before_scanning(self):
        libraries = {
            "Calibre_Library": "Main",
            "archive": "Archive",
        }

        with self.assertLogs(level="INFO") as logs:
            log_library_list("http://example.com", libraries)

        self.assertEqual(
            logs.output,
            [
                "INFO:root:Libraries found at http://example.com:",
                "INFO:root:  Main (Calibre_Library)",
                "INFO:root:  Archive (archive)",
            ],
        )

    def test_log_library_book_count_prints_total(self):
        with self.assertLogs(level="INFO") as logs:
            log_library_book_count(
                "Main",
                {
                    "1": {"title": "One"},
                    "2": {"title": "Two"},
                },
            )

        self.assertEqual(
            logs.output,
            ["INFO:root:Library Main contains 2 books"],
        )

    def test_browse_library_logs_position_and_total(self):
        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
        library_content = {
            "1": {"title": "One", "formats": []},
            "2": {"title": "Two", "formats": []},
        }

        with self.assertLogs(level="DEBUG") as logs:
            browse_library(
                library_content,
                "http://example.com",
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                [],
                RunOptions(),
                stats,
            )

        self.assertIn(
            "DEBUG:root:Evaluating 1/2: Unknown Author - One",
            logs.output,
        )
        self.assertIn(
            "DEBUG:root:Evaluating 2/2: Unknown Author - Two",
            logs.output,
        )

    def test_browse_library_renames_download_with_readable_hash_filename(self):
        content = b"book bytes"
        expected_hash = hashlib.md5(content).hexdigest().upper()
        captured_book_details = {}

        def fake_download_file(
            _requests_session,
            _download_url,
            file_path,
            _request_settings,
            **_kwargs,
        ):
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            Path(file_path).write_bytes(content)
            return True

        def fake_add_item_to_db(_database_file, book_details):
            captured_book_details.update(book_details)
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            stats = RunStats()
            config = SimpleNamespace(
                target_formats=["epub"],
                storage_path=temp_dir,
                database_file="books.sqlite",
                download_retries=1,
                retry_backoff=0,
                wait_time=0,
            )
            library_content = {
                "5": {
                    "application_id": 5,
                    "title": "The Nightingale",
                    "authors": ["Kristin Hannah"],
                    "author_sort": "Hannah, Kristin",
                    "formats": ["epub"],
                    "languages": ["eng"],
                    "identifiers": {},
                    "tags": [],
                    "main_format": {"epub": "/get/epub/5"},
                    "other_formats": {},
                    "format_metadata": {
                        "epub": {
                            "size": len(content),
                            "path": "old-server-name.epub",
                        }
                    },
                }
            }

            with (
                patch("calibre_downloader.download_file", fake_download_file),
                patch("calibre_downloader.add_item_to_db", fake_add_item_to_db),
            ):
                browse_library(
                    library_content,
                    "http://example.com",
                    SimpleNamespace(),
                    SimpleNamespace(),
                    config,
                    [],
                    RunOptions(),
                    stats,
                )

            expected_filename = (
                f"Kristin Hannah - The Nightingale [{expected_hash}].epub"
            )
            expected_path = Path(temp_dir) / "epub" / expected_filename

            self.assertTrue(expected_path.is_file())
            self.assertEqual(expected_path.read_bytes(), content)
            self.assertEqual(captured_book_details["file_hash"], expected_hash)
            self.assertEqual(captured_book_details["filename"], expected_filename)

    def test_filter_libraries_accepts_id_or_display_name(self):
        libraries = {
            "Calibre_Library": "Main",
            "small": "Small Library",
        }

        self.assertEqual(
            filter_libraries(libraries, "small"),
            {"small": "Small Library"},
        )
        self.assertEqual(
            filter_libraries(libraries, "small library"),
            {"small": "Small Library"},
        )
        self.assertEqual(
            filter_libraries(libraries, "missing"),
            {},
        )

    def test_positive_int_rejects_zero(self):
        with self.assertRaisesRegex(Exception, "positive integer"):
            positive_int("0")

    def test_author_display_handles_empty_authors(self):
        self.assertEqual(author_display({"authors": []}), "Unknown Author")

    def test_get_format_details_requires_size_and_path(self):
        self.assertIsNone(
            get_format_details({"format_metadata": {"epub": {"size": 123}}}, "epub")
        )

    def test_log_summary_handles_empty_stats(self):
        with self.assertLogs(level="INFO") as logs:
            log_summary(RunStats(), RunOptions(dry_run=True))

        self.assertIn("Summary [dry-run]", logs.output[0])


if __name__ == "__main__":
    unittest.main()
