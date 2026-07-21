import hashlib
import logging
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibre_downloader import (
    RunOptions,
    RunStats,
    author_display,
    browse_library,
    configure_logging,
    filename_author_display,
    filter_libraries,
    get_format_details,
    hashed_book_filename,
    library_display_name,
    load_rules,
    log_library_book_count,
    log_library_list,
    log_summary,
    main,
    normalize_server_address,
    positive_int,
    process_servers,
    temporary_download_path,
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
                    "title": "Example Novel",
                    "authors": ["Example Author"],
                    "author_sort": "Author, Example",
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
            downloaded_server_books = set()

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
                    downloaded_server_books,
                )

            expected_filename = f"Example Author - Example Novel [{expected_hash}].epub"
            expected_path = Path(temp_dir) / "epub" / expected_filename

            self.assertTrue(expected_path.is_file())
            self.assertEqual(expected_path.read_bytes(), content)
            self.assertEqual(captured_book_details["file_hash"], expected_hash)
            self.assertEqual(captured_book_details["filename"], expected_filename)
            self.assertIn(
                ("Example Novel", "Author, Example", "EPUB", len(content)),
                downloaded_server_books,
            )

    def test_browse_library_skips_book_downloaded_from_same_server_before(self):
        stats = RunStats()
        config = SimpleNamespace(
            target_formats=["epub"],
            storage_path="downloads",
            database_file="books.sqlite",
        )
        library_content = {
            "5": {
                "application_id": 5,
                "title": "Example Novel",
                "authors": ["Example Author"],
                "author_sort": "Author, Example",
                "formats": ["epub"],
                "languages": ["eng"],
                "main_format": {"epub": "/get/epub/5"},
                "other_formats": {},
                "format_metadata": {
                    "epub": {
                        "size": 123,
                        "path": "server-name.epub",
                    }
                },
            }
        }

        downloaded_server_books = {("Example Novel", "Author, Example", "EPUB", 123)}

        with (
            patch("calibre_downloader.download_file", Mock()) as download_file,
            self.assertLogs(level="INFO") as logs,
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
                downloaded_server_books,
            )

        download_file.assert_not_called()
        self.assertEqual(stats.books_already_present, 1)
        self.assertIn(
            "INFO:root:Skipping Example Author - Example Novel as EPUB: "
            "downloaded from this Calibre server previously",
            logs.output,
        )

    def test_browse_library_dry_run_ignores_downloaded_server_cache(self):
        stats = RunStats()
        config = SimpleNamespace(
            target_formats=["epub"],
            storage_path="downloads",
            database_file="books.sqlite",
        )
        library_content = {
            "5": {
                "application_id": 5,
                "title": "Example Novel",
                "authors": ["Example Author"],
                "author_sort": "Author, Example",
                "formats": ["epub"],
                "languages": ["eng"],
                "main_format": {"epub": "/get/epub/5"},
                "other_formats": {},
                "format_metadata": {
                    "epub": {
                        "size": 123,
                        "path": "server-name.epub",
                    }
                },
            }
        }

        downloaded_server_books = {("Example Novel", "Author, Example", "EPUB", 123)}

        with self.assertLogs(level="INFO") as logs:
            browse_library(
                library_content,
                "http://example.com",
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                [],
                RunOptions(dry_run=True),
                stats,
                downloaded_server_books,
            )

        self.assertEqual(stats.downloads_planned, 1)
        self.assertIn(
            "INFO:root:Would download Example Author - Example Novel [HASH].epub",
            logs.output,
        )

    def test_process_servers_loads_downloaded_books_once_per_server(self):
        config = SimpleNamespace(database_file="books.sqlite")
        previous_books = {("Example Novel", "Author, Example", "EPUB", 123)}

        with (
            patch("calibre_downloader.evaluate_server", return_value=True),
            patch(
                "calibre_downloader.list_libraries",
                return_value={"main": "Main", "archive": "Archive"},
            ),
            patch(
                "calibre_downloader.list_library_content",
                side_effect=[{"1": {"title": "One"}}, {"2": {"title": "Two"}}],
            ),
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server",
                return_value=previous_books,
            ) as load_downloaded_books,
            patch("calibre_downloader.browse_library") as browse,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                [],
                RunOptions(),
            )

        load_downloaded_books.assert_called_once_with(
            "books.sqlite",
            "http://example.com",
        )
        self.assertEqual(browse.call_count, 2)
        self.assertIs(browse.call_args_list[0].args[8], previous_books)
        self.assertIs(browse.call_args_list[1].args[8], previous_books)

    def test_process_servers_dry_run_does_not_load_downloaded_books(self):
        config = SimpleNamespace(database_file="books.sqlite")

        with (
            patch("calibre_downloader.evaluate_server", return_value=True),
            patch("calibre_downloader.list_libraries", return_value={"main": "Main"}),
            patch(
                "calibre_downloader.list_library_content",
                return_value={"1": {"title": "One"}},
            ),
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server"
            ) as load_downloaded_books,
            patch("calibre_downloader.browse_library") as browse,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                [],
                RunOptions(dry_run=True),
            )

        load_downloaded_books.assert_not_called()
        self.assertEqual(browse.call_count, 1)
        self.assertEqual(browse.call_args.args[8], set())

    def test_temporary_download_path_uses_pid_and_uuid(self):
        temp_path = temporary_download_path("downloads", "epub")

        filename = Path(temp_path).name
        prefix, pid, uuid_hex = filename.removesuffix(".epub").split("-")
        self.assertEqual(temp_path, str(Path("downloads") / filename))
        self.assertEqual(prefix, ".download")
        self.assertEqual(pid, str(os.getpid()))
        self.assertEqual(len(uuid_hex), 32)
        int(uuid_hex, 16)

    def test_filename_author_display_uses_only_first_author(self):
        self.assertEqual(
            filename_author_display({"authors": ["First Author", "Second Author"]}),
            "First Author",
        )
        self.assertEqual(filename_author_display({"authors": []}), "Unknown Author")

    def test_hashed_book_filename_uses_first_author_only(self):
        file_hash = "36AD266D607757AF357D59FE0A1A4277"
        filename = hashed_book_filename(
            {
                "authors": [
                    "Primary Test Author",
                    "Secondary Test Author",
                    "Tertiary Test Author",
                ],
                "title": "Example Anthology Title",
            },
            "epub",
            file_hash,
        )

        self.assertTrue(filename.startswith("Primary Test Author - "))
        self.assertNotIn("Secondary Test Author", filename)
        self.assertTrue(filename.endswith(f" [{file_hash}].epub"))

    def test_hashed_book_filename_truncates_long_names_and_preserves_hash(self):
        file_hash = "36AD266D607757AF357D59FE0A1A4277"
        filename = hashed_book_filename(
            {
                "authors": ["Extremely Long Author Name " * 12],
                "title": "Very Long Book Title " * 20,
            },
            "epub",
            file_hash,
        )

        self.assertLessEqual(len(filename.encode("utf-8")), 255)
        self.assertTrue(filename.endswith(f" [{file_hash}].epub"))

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
