import sys
import tempfile
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web import (
    RequestSettings,
    download_file,
    evaluate_server,
    list_libraries,
    list_library_content,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        headers=None,
        chunks=None,
        json_data=None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or [b"content"]
        self._json_data = json_data or {}
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.last_get_url = None
        self.last_get_kwargs = None
        self.last_head_url = None
        self.last_head_kwargs = None
        self.get_call_count = 0

    def get(self, url, **kwargs):
        self.get_call_count += 1
        self.last_get_url = url
        self.last_get_kwargs = kwargs
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    def head(self, url, **kwargs):
        self.last_head_url = url
        self.last_head_kwargs = kwargs
        return self.responses[0]


class WebTestCase(unittest.TestCase):
    def test_download_file_writes_atomically_and_passes_request_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "book.epub"
            session = FakeSession(FakeResponse(chunks=[b"hello", b" world"]))
            settings = RequestSettings(timeout=7, verify=False, allow_redirects=False)

            self.assertTrue(
                download_file(
                    session,
                    "http://example.com/book.epub",
                    str(destination),
                    settings,
                    max_retries=1,
                )
            )

            self.assertEqual(destination.read_bytes(), b"hello world")
            self.assertFalse(destination.with_name("book.epub.part").exists())
            self.assertEqual(session.last_get_kwargs["timeout"], 7)
            self.assertFalse(session.last_get_kwargs["verify"])
            self.assertFalse(session.last_get_kwargs["allow_redirects"])

    def test_download_file_retries_transient_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "book.epub"
            session = FakeSession(FakeResponse(status_code=500), FakeResponse())

            self.assertTrue(
                download_file(
                    session,
                    "http://example.com/book.epub",
                    str(destination),
                    RequestSettings(timeout=7),
                    max_retries=2,
                    retry_backoff=0,
                )
            )
            self.assertEqual(session.get_call_count, 2)

    def test_download_file_removes_partial_file_on_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "book.epub"
            session = FakeSession(FakeResponse(status_code=500))

            self.assertFalse(
                download_file(
                    session,
                    "http://example.com/book.epub",
                    str(destination),
                    RequestSettings(timeout=7),
                    max_retries=1,
                )
            )

            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name("book.epub.part").exists())

    def test_evaluate_server_accepts_calibre_server(self):
        session = FakeSession(FakeResponse(headers={"Server": "calibre"}))
        self.assertTrue(
            evaluate_server(
                session,
                "http://example.com",
                RequestSettings(timeout=7),
            )
        )

    def test_evaluate_server_accepts_versioned_calibre_server(self):
        session = FakeSession(FakeResponse(headers={"Server": "calibre 9.11.0"}))
        self.assertTrue(
            evaluate_server(
                session,
                "http://example.com",
                RequestSettings(timeout=7),
            )
        )

    def test_evaluate_server_rejects_non_calibre_server(self):
        session = FakeSession(FakeResponse(headers={"Server": "nginx"}))
        self.assertFalse(
            evaluate_server(
                session,
                "http://example.com",
                RequestSettings(timeout=7),
            )
        )

    def test_list_libraries_returns_library_map(self):
        session = FakeSession(
            FakeResponse(json_data={"library_map": {"Calibre_Library": "Main"}})
        )

        self.assertEqual(
            list_libraries(session, "http://example.com", RequestSettings(timeout=7)),
            {"Calibre_Library": "Main"},
        )
        self.assertEqual(
            session.last_get_url,
            "http://example.com/ajax/library-info",
        )

    def test_list_library_content_uses_books_endpoint_and_returns_book_map(self):
        session = FakeSession(FakeResponse(json_data={"123": {"title": "Book"}}))

        self.assertEqual(
            list_library_content(
                session,
                "http://example.com",
                RequestSettings(timeout=7),
                "Calibre_Library",
            ),
            {"123": {"title": "Book"}},
        )
        self.assertEqual(
            session.last_get_url,
            "http://example.com/ajax/books/Calibre_Library",
        )


if __name__ == "__main__":
    unittest.main()
