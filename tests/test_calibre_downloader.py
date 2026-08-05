import hashlib
import logging
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibre_downloader import (
    RunOptions,
    RunStats,
    author_display,
    book_author_title_display,
    browse_library,
    build_server_evaluation_request_settings,
    configure_logging,
    download_failure_limit_reached,
    filename_author_display,
    filter_libraries,
    format_file_size,
    get_format_details,
    hashed_book_filename,
    iter_library_books,
    language_names,
    language_rule_groups,
    language_rule_values,
    library_display_name,
    load_rules,
    log_library_book_count,
    log_library_list,
    log_summary,
    main,
    normalize_server_address,
    positive_int,
    process_servers,
    session_log_file_path,
    temporary_download_path,
)
from rules import validate_rules
from web import RequestSettings


class CalibreDownloaderTestCase(unittest.TestCase):
    def tearDown(self):
        logging.getLogger("urllib3").setLevel(logging.NOTSET)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()

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

    def test_iter_library_books_sorts_by_author_sort_then_title(self):
        library_content = {
            "30": {
                "title": "Foundation and Empire",
                "authors": ["Isaac Asimov"],
                "author_sort": "Asimov, Isaac",
            },
            "20": {
                "title": "Hidden Riches",
                "authors": ["Nora Roberts"],
                "author_sort": "Roberts, Nora",
            },
            "10": {
                "title": "Foundation",
                "authors": ["Isaac Asimov"],
                "author_sort": "Asimov, Isaac",
            },
        }

        books = list(iter_library_books(library_content))

        self.assertEqual([book_id for book_id, _book in books], ["10", "30", "20"])

    def test_iter_library_books_falls_back_to_first_author(self):
        library_content = {
            "1": {"title": "Zulu", "authors": ["Zed Writer"]},
            "2": {"title": "Alpha", "authors": ["Alice Writer"]},
        }

        books = list(iter_library_books(library_content))

        self.assertEqual([book_id for book_id, _book in books], ["2", "1"])

    def test_language_names_converts_iso639_codes(self):
        self.assertEqual(
            language_names(["spa", "eng", "zho"]),
            ["Spanish", "English", "Chinese"],
        )

    def test_language_rule_values_include_codes_and_names(self):
        self.assertEqual(
            language_rule_values(["spa", "eng", "zho"]),
            ["spa", "Spanish", "eng", "English", "zho", "Chinese"],
        )

    def test_language_rule_groups_keep_codes_and_names_together(self):
        self.assertEqual(
            language_rule_groups(["eng", "zho"]),
            [["eng", "English"], ["zho", "Chinese"]],
        )

    def test_language_names_requires_iso639_dependency(self):
        with patch("calibre_downloader.Lang", None):
            with self.assertRaisesRegex(
                RuntimeError,
                "Missing required dependency iso639-lang",
            ):
                language_names(["spa"])

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

    def test_configure_logging_writes_session_log_file(self):
        config = SimpleNamespace(
            debug_mode=True,
            logstamp_format="%(message)s",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "session.log"

            with redirect_stderr(StringIO()):
                configure_logging(config, log_file=log_file)
                logging.info("Saved for later")
                for handler in logging.getLogger().handlers:
                    handler.flush()

            self.assertIn(
                "INFO root: Saved for later",
                log_file.read_text(encoding="utf-8"),
            )

    def test_session_log_file_path_uses_timestamped_log_name(self):
        with patch("calibre_downloader.time.strftime", return_value="20260730-123456"):
            self.assertEqual(
                session_log_file_path(),
                Path("logs") / "calibre-downloader-20260730-123456.log",
            )

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

    def test_browse_library_logs_spacer_between_book_entries(self):
        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
        library_content = {
            "1": {"title": "One", "formats": [], "languages": ["eng"]},
            "2": {"title": "Two", "formats": [], "languages": ["eng"]},
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

        first_entry = "DEBUG:root:Evaluating 1/2: Unknown Author - One"
        spacer = "DEBUG:root:------------------------------"
        second_entry = "DEBUG:root:Evaluating 2/2: Unknown Author - Two"
        self.assertIn(first_entry, logs.output)
        self.assertIn(spacer, logs.output)
        self.assertIn(second_entry, logs.output)
        self.assertLess(logs.output.index(first_entry), logs.output.index(spacer))
        self.assertLess(logs.output.index(spacer), logs.output.index(second_entry))

    def test_author_display_compacts_long_author_lists(self):
        book_metadata = {
            "authors": ["Author One", "Author Two", "Author Three", "Author Four"]
        }

        self.assertEqual(
            author_display(book_metadata, max_authors=2),
            "Author One & Author Two & 2 more",
        )
        self.assertEqual(
            author_display(book_metadata, max_authors=0),
            "Author One & Author Two & Author Three & Author Four",
        )

    def test_book_author_title_display_uses_compact_author_display(self):
        book_metadata = {
            "title": "Anthology",
            "authors": ["Author One", "Author Two", "Author Three", "Author Four"],
        }

        self.assertEqual(
            book_author_title_display(book_metadata, max_authors=3),
            "Author One & Author Two & Author Three & 1 more - Anthology",
        )

    def test_browse_library_truncates_long_book_entry_logs(self):
        stats = RunStats()
        config = SimpleNamespace(
            target_formats=["epub"],
            log_book_author_limit=2,
            log_book_entry_max_length=90,
        )
        library_content = {
            "1": {
                "title": "Very Long Book Title " * 8,
                "authors": [
                    "Author One",
                    "Author Two",
                    "Author Three",
                    "Author Four",
                    "Author Five",
                ],
                "formats": [],
                "languages": ["eng"],
            }
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

        evaluating_log = next(
            log_entry
            for log_entry in logs.output
            if log_entry.startswith("DEBUG:root:Evaluating")
        )
        rendered_message = evaluating_log.removeprefix("DEBUG:root:")
        self.assertLessEqual(len(rendered_message), 90)
        self.assertIn("Author One & Author Two & 3 more", rendered_message)
        self.assertTrue(rendered_message.endswith("..."))
        skipped_log = next(
            log_entry
            for log_entry in logs.output
            if log_entry.startswith("DEBUG:root:Skipping")
        )
        rendered_message = skipped_log.removeprefix("DEBUG:root:")
        self.assertLessEqual(len(rendered_message), 90)
        self.assertTrue(
            rendered_message.startswith("Skipping: no preferred formats available:")
        )

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

    def test_browse_library_can_reject_language_by_iso639_code(self):
        class FakeLang:
            def __init__(self, language_code):
                self.name = {"spa": "Spanish"}[language_code]

        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
        library_content = {
            "1": {
                "title": "Libro",
                "formats": ["epub"],
                "languages": ["spa"],
            }
        }
        rules = validate_rules(
            [
                {
                    "name": "Skip Spanish code",
                    "metadata": "Language",
                    "regex": "^spa$",
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

    def test_browse_library_rejects_oversized_selected_format(self):
        stats = RunStats()
        config = SimpleNamespace(target_formats=["epub"])
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
                        "size": 151_000_000,
                        "path": "server-name.epub",
                    }
                },
            }
        }
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
                rules,
                RunOptions(explain_rules=True),
                stats,
            )

        download_file.assert_not_called()
        self.assertEqual(stats.books_rejected, 1)
        self.assertEqual(stats.downloads_attempted, 0)
        self.assertIn(
            "INFO:root:Rejected: Oversized books (Size): EPUB 151 MB > 150 MB: "
            "5 - Example Author - Example Novel as EPUB",
            logs.output,
        )

    def test_browse_library_tries_next_format_after_size_rejection(self):
        pdf_size = 151_000_000
        epub_content = b"small epub"
        captured_book_details = {}
        downloaded_urls = []
        captured_download_kwargs = {}

        def fake_download_file(
            _requests_session,
            download_url,
            file_path,
            _request_settings,
            **kwargs,
        ):
            downloaded_urls.append(download_url)
            captured_download_kwargs.update(kwargs)
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            Path(file_path).write_bytes(epub_content)
            return True

        def fake_add_item_to_db(_database_file, book_details):
            captured_book_details.update(book_details)
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            stats = RunStats()
            config = SimpleNamespace(
                target_formats=["pdf", "epub"],
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
                    "formats": ["pdf", "epub"],
                    "languages": ["eng"],
                    "identifiers": {},
                    "tags": [],
                    "main_format": {"pdf": "/get/pdf/5"},
                    "other_formats": {"epub": "/get/epub/5"},
                    "format_metadata": {
                        "pdf": {
                            "size": pdf_size,
                            "path": "server-name.pdf",
                        },
                        "epub": {
                            "size": len(epub_content),
                            "path": "server-name.epub",
                        },
                    },
                }
            }
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

            with (
                patch("calibre_downloader.download_file", fake_download_file),
                patch("calibre_downloader.add_item_to_db", fake_add_item_to_db),
                self.assertLogs(level="INFO") as logs,
            ):
                browse_library(
                    library_content,
                    "http://example.com",
                    SimpleNamespace(),
                    SimpleNamespace(),
                    config,
                    rules,
                    RunOptions(explain_rules=True),
                    stats,
                )

            self.assertEqual(downloaded_urls, ["http://example.com/get/epub/5"])
            self.assertEqual(captured_download_kwargs["max_bytes"], len(epub_content))
            self.assertEqual(captured_book_details["format"], "EPUB")
            self.assertEqual(captured_book_details["size"], len(epub_content))
            self.assertEqual(stats.books_rejected, 0)
            self.assertEqual(stats.downloads_attempted, 1)
            self.assertEqual(stats.downloads_succeeded, 1)
            self.assertIn(
                "INFO:root:Rejected: Oversized books (Size): PDF 151 MB > 150 MB: "
                "5 - Example Author - Example Novel as PDF",
                logs.output,
            )

    def test_browse_library_normalizes_malformed_metadata_collections(self):
        content = b"book bytes"
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
                    "languages": "eng",
                    "identifiers": ["not", "a", "mapping"],
                    "tags": {"not": "a list"},
                    "main_format": {"epub": "/get/epub/5"},
                    "other_formats": {},
                    "format_metadata": {
                        "epub": {
                            "size": str(len(content)),
                            "path": "server-name.epub",
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

            self.assertEqual(captured_book_details["language"], "English")
            self.assertEqual(captured_book_details["identifiers"], "")
            self.assertEqual(captured_book_details["tags"], "")
            self.assertEqual(captured_book_details["size"], len(content))

    def test_browse_library_stops_after_consecutive_download_failures(self):
        attempted_urls = []

        def fake_download_file(
            _requests_session,
            download_url,
            _file_path,
            _request_settings,
            **_kwargs,
        ):
            attempted_urls.append(download_url)
            return False

        stats = RunStats()
        config = SimpleNamespace(
            target_formats=["epub"],
            storage_path="downloads",
            database_file="books.sqlite",
            download_retries=1,
            retry_backoff=0,
            max_consecutive_download_failures=2,
        )
        rules = validate_rules(
            [
                {
                    "name": "Unwanted title",
                    "metadata": "Title",
                    "regex": "^Rejected",
                    "wanted": False,
                }
            ]
        )
        library_content = {
            "1": self.book_metadata("Rejected by rule", "/get/epub/1"),
            "2": self.book_metadata("First failed download", "/get/epub/2"),
            "3": self.book_metadata("Second failed download", "/get/epub/3"),
            "4": self.book_metadata("Should not be attempted", "/get/epub/4"),
        }

        with (
            patch("calibre_downloader.download_file", fake_download_file),
            self.assertLogs(level="INFO") as logs,
        ):
            consecutive_failures = browse_library(
                library_content,
                "http://example.com",
                SimpleNamespace(),
                SimpleNamespace(),
                config,
                rules,
                RunOptions(),
                stats,
            )

        self.assertEqual(consecutive_failures, 2)
        self.assertEqual(
            attempted_urls,
            ["http://example.com/get/epub/2", "http://example.com/get/epub/3"],
        )
        self.assertEqual(stats.books_seen, 3)
        self.assertEqual(stats.books_rejected, 1)
        self.assertEqual(stats.downloads_failed, 2)
        self.assertIn(
            "INFO:root:Stopping downloads from http://example.com after 2 "
            "consecutive failed download attempts",
            logs.output,
        )

    def test_download_failure_limit_can_be_disabled(self):
        self.assertFalse(
            download_failure_limit_reached(
                SimpleNamespace(max_consecutive_download_failures=0),
                100,
            )
        )

    def test_process_servers_stops_scanning_server_after_download_failure_limit(self):
        config = SimpleNamespace(
            database_file="books.sqlite",
            max_consecutive_download_failures=2,
        )

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com",
            ),
            patch(
                "calibre_downloader.list_libraries",
                return_value={"main": "Main", "archive": "Archive"},
            ),
            patch(
                "calibre_downloader.list_library_content",
                side_effect=[{"1": {"title": "One"}}, {"2": {"title": "Two"}}],
            ) as list_content,
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server",
                return_value=set(),
            ),
            patch("calibre_downloader.browse_library", return_value=2) as browse,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                RequestSettings(timeout=300),
                config,
                [],
                RunOptions(),
            )

        self.assertEqual(list_content.call_count, 1)
        self.assertEqual(browse.call_count, 1)

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
                self.assertLogs(level="DEBUG") as logs,
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

            self.assertIn(
                "DEBUG:root:Downloading Example Author - Example Novel "
                "as EPUB (10 B)",
                logs.output,
            )
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
            "INFO:root:Skipping: downloaded from this Calibre server previously: "
            "Example Author - Example Novel as EPUB",
            logs.output,
        )

    def test_browse_library_skips_global_metadata_duplicate(self):
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

        downloaded_global_books = {("Example Novel", "Author, Example", "EPUB", 123)}

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
                set(),
                downloaded_global_books,
            )

        download_file.assert_not_called()
        self.assertEqual(stats.books_skipped_global_metadata_duplicates, 1)
        self.assertIn(
            "INFO:root:Skipping: matching title, author, format, and size already "
            "exist in the database: Example Author - Example Novel as EPUB",
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
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com",
            ),
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
                RequestSettings(timeout=300),
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
        self.assertEqual(browse.call_args_list[0].args[9], set())
        self.assertEqual(browse.call_args_list[1].args[9], set())

    def test_process_servers_dry_run_does_not_load_downloaded_books(self):
        config = SimpleNamespace(database_file="books.sqlite")

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com",
            ),
            patch("calibre_downloader.list_libraries", return_value={"main": "Main"}),
            patch(
                "calibre_downloader.list_library_content",
                return_value={"1": {"title": "One"}},
            ),
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server"
            ) as load_downloaded_books,
            patch("calibre_downloader.downloaded_book_keys") as load_global_books,
            patch("calibre_downloader.browse_library") as browse,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                RequestSettings(timeout=300),
                config,
                [],
                RunOptions(dry_run=True),
            )

        load_downloaded_books.assert_not_called()
        load_global_books.assert_not_called()
        self.assertEqual(browse.call_count, 1)
        self.assertEqual(browse.call_args.args[8], set())
        self.assertEqual(browse.call_args.args[9], set())

    def test_process_servers_logs_server_count_before_evaluation(self):
        config = SimpleNamespace(database_file="books.sqlite")

        with (
            patch("calibre_downloader.resolve_server_address", return_value=None),
            self.assertLogs(level="INFO") as logs,
        ):
            process_servers(
                ["one.example", "two.example", "three.example"],
                SimpleNamespace(),
                RequestSettings(timeout=300),
                config,
                [],
                RunOptions(),
            )

        self.assertIn(
            "INFO:root:Server list loaded, connecting to 3 servers",
            logs.output,
        )
        self.assertLess(
            logs.output.index("INFO:root:Server list loaded, connecting to 3 servers"),
            logs.output.index("INFO:root:Evaluating server http://one.example"),
        )

    def test_process_servers_logs_current_server_on_keyboard_interrupt(self):
        config = SimpleNamespace(database_file="books.sqlite")

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://resolved.example",
            ),
            patch("calibre_downloader.list_libraries", return_value={"main": "Main"}),
            patch(
                "calibre_downloader.list_library_content",
                return_value={"1": {"title": "One"}},
            ),
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server",
                return_value=set(),
            ),
            patch("calibre_downloader.browse_library", side_effect=KeyboardInterrupt),
            self.assertLogs(level="INFO") as logs,
            self.assertRaises(KeyboardInterrupt),
        ):
            process_servers(
                ["https://example.com"],
                SimpleNamespace(),
                RequestSettings(timeout=300),
                config,
                [],
                RunOptions(),
            )

        self.assertIn(
            "INFO:root:Interrupted by user while connected to http://resolved.example",
            logs.output,
        )

    def test_process_servers_loads_global_downloaded_books_when_configured(self):
        config = SimpleNamespace(
            database_file="books.sqlite",
            skip_global_metadata_duplicates=True,
        )
        global_books = {("Example Novel", "Author, Example", "EPUB", 123)}

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com",
            ),
            patch("calibre_downloader.list_libraries", return_value={"main": "Main"}),
            patch(
                "calibre_downloader.list_library_content",
                return_value={"1": {"title": "One"}},
            ),
            patch(
                "calibre_downloader.downloaded_book_keys_for_calibre_server",
                return_value=set(),
            ),
            patch(
                "calibre_downloader.downloaded_book_keys",
                return_value=global_books,
            ) as load_global_books,
            patch("calibre_downloader.browse_library") as browse,
            self.assertLogs(level="INFO") as logs,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                RequestSettings(timeout=300),
                config,
                [],
                RunOptions(),
            )

        load_global_books.assert_called_once_with("books.sqlite")
        self.assertIs(browse.call_args.args[9], global_books)
        self.assertIn(
            "INFO:root:Loaded 1 global book metadata records for duplicate "
            "pre-checking; this may use more memory on large databases",
            logs.output,
        )
        self.assertLess(
            logs.output.index(
                "INFO:root:Loaded 1 global book metadata records for duplicate "
                "pre-checking; this may use more memory on large databases"
            ),
            logs.output.index("INFO:root:Server list loaded, connecting to 1 server"),
        )

    def test_process_servers_uses_short_timeout_for_server_evaluation_only(self):
        config = SimpleNamespace(
            database_file="books.sqlite",
            server_evaluation_timeout=15,
        )
        request_settings = RequestSettings(timeout=300, verify=False)

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com",
            ) as resolve,
            patch("calibre_downloader.list_libraries", return_value={}) as libraries,
        ):
            process_servers(
                ["example.com"],
                SimpleNamespace(),
                request_settings,
                config,
                [],
                RunOptions(dry_run=True),
            )

        self.assertEqual(resolve.call_args.args[2].timeout, 15)
        self.assertIs(libraries.call_args.args[2], request_settings)

    def test_process_servers_uses_resolved_server_address_for_scan(self):
        config = SimpleNamespace(database_file="books.sqlite")
        request_settings = RequestSettings(timeout=300, verify=False)
        session = SimpleNamespace()

        with (
            patch(
                "calibre_downloader.resolve_server_address",
                return_value="http://example.com:8083",
            ) as resolve,
            patch("calibre_downloader.list_libraries", return_value={}) as libraries,
        ):
            process_servers(
                ["https://example.com:8083"],
                session,
                request_settings,
                config,
                [],
                RunOptions(dry_run=True),
            )

        resolve.assert_called_once_with(
            session,
            "https://example.com:8083",
            build_server_evaluation_request_settings(config, request_settings),
        )
        libraries.assert_called_once_with(
            session,
            "http://example.com:8083",
            request_settings,
        )

    def test_server_evaluation_request_settings_falls_back_to_main_timeout(self):
        request_settings = RequestSettings(timeout=300, verify=False)

        evaluation_settings = build_server_evaluation_request_settings(
            SimpleNamespace(),
            request_settings,
        )

        self.assertEqual(evaluation_settings.timeout, 300)
        self.assertFalse(evaluation_settings.verify)

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

    def test_get_format_details_normalizes_integer_string_size(self):
        self.assertEqual(
            get_format_details(
                {
                    "format_metadata": {
                        "epub": {
                            "size": "123",
                            "path": "server-name.epub",
                        }
                    }
                },
                "epub",
            ),
            {
                "size": 123,
                "path": "server-name.epub",
            },
        )

    def test_get_format_details_rejects_invalid_sizes(self):
        for size in ("unknown", -1, True, None, {"bytes": 123}):
            with self.subTest(size=size):
                self.assertIsNone(
                    get_format_details(
                        {
                            "format_metadata": {
                                "epub": {
                                    "size": size,
                                    "path": "server-name.epub",
                                }
                            }
                        },
                        "epub",
                    )
                )

    def test_format_file_size_uses_decimal_units(self):
        self.assertEqual(format_file_size(999), "999 B")
        self.assertEqual(format_file_size(2400000), "2.4 MB")
        self.assertEqual(format_file_size(1000000), "1 MB")
        self.assertEqual(format_file_size(None), "unknown size")

    def test_log_summary_handles_empty_stats(self):
        with self.assertLogs(level="INFO") as logs:
            log_summary(RunStats(), RunOptions(dry_run=True))

        self.assertIn("Summary [dry-run]", logs.output[0])

    def test_main_returns_interrupt_exit_code(self):
        config = SimpleNamespace(verify_ssl=True)

        with (
            patch("calibre_downloader.load_config", return_value=config),
            patch("calibre_downloader.load_rules", return_value=[]),
            patch("calibre_downloader.require_language_dependency"),
            patch("calibre_downloader.configure_logging"),
            patch(
                "calibre_downloader.session_log_file_path", return_value="session.log"
            ),
            patch("calibre_downloader.build_requests_session", return_value=Mock()),
            patch(
                "calibre_downloader.build_request_settings",
                return_value=RequestSettings(timeout=300),
            ),
            patch("calibre_downloader.process_servers", side_effect=KeyboardInterrupt),
        ):
            exit_code = main(["--servers", "example.com", "--dry-run"])

        self.assertEqual(exit_code, 130)

    def book_metadata(self, title, download_path):
        return {
            "application_id": title,
            "title": title,
            "authors": ["Example Author"],
            "author_sort": "Author, Example",
            "formats": ["epub"],
            "languages": ["eng"],
            "identifiers": {},
            "tags": [],
            "main_format": {"epub": download_path},
            "other_formats": {},
            "format_metadata": {
                "epub": {
                    "size": 123,
                    "path": "server-name.epub",
                }
            },
        }


if __name__ == "__main__":
    unittest.main()
