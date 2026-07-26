# Calibre Weblibrary Downloader

Calibre Weblibrary Downloader downloads ebooks from publicly accessible Calibre web libraries, applies rule-based metadata filters, and keeps a local SQLite record of downloaded files to avoid duplicates.

## Features

- Download books from Calibre web libraries with anonymous access enabled.
- Prefer ebook formats according to the configured priority order, with fallback to
  the next format when a preferred format is rejected by rules.
- Skip unwanted books with rules for maximum file size, language, author, title, tag, or series metadata.
- Track downloaded files in a local SQLite database.
- Use optional HTTP and HTTPS proxy settings.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Create local config and rule files from the tracked examples:

```bash
cp config.example.yaml config.yaml
cp rules.example.yaml rules.yaml
```

Copy `config.example.yaml` to `config.yaml`, then edit `config.yaml` before running the script.

- `storage_path` sets where downloaded books are written.
- `database_file` points to the SQLite tracking database.
- `target_formats` controls which ebook formats are downloaded and their priority order.
- `server_evaluation_timeout` controls the initial server reachability check.
- `timeout` controls library metadata requests and downloads.
- `proxy` can be enabled when downloads should go through an HTTP or HTTPS proxy.
- `download_retries` and `retry_backoff` control retry behavior for failed downloads.
- `max_consecutive_download_failures` skips the rest of a server after this many failed download attempts in a row. Set it to `0` to disable this guard.
- `skip_global_metadata_duplicates` is off by default. When enabled, the downloader loads all existing `title`, `author_sort`, `format`, and `size` database keys into memory and skips matching books before download, even across different Calibre servers. This reduces duplicate network downloads but may use noticeably more memory with very large databases.
- `log_book_author_limit` shortens long anthology author lists in log output by showing the first configured number of authors plus `X more`. Set it to `0` to show every author.
- `log_book_entry_max_length` caps rendered book-entry log messages so very long author/title combinations do not dominate the log. Set it to `0` to disable truncation.

Copy `rules.example.yaml` to `rules.yaml`, then edit `rules.yaml` to skip books that match unwanted metadata or exceed the maximum selected-format file size. The local `rules.yaml` file is ignored by Git so each user can keep their own filtering preferences. If no rules are defined, matching Calibre libraries are treated as downloadable.

Copy `books.example.sqlite` to `books.sqlite` before first use if you want to start from the bundled empty tracking database. Keep a backup if you rely on it to prevent duplicate downloads across runs.

The downloader also applies an internal download-size safety margin. Calibre's
metadata size is treated as an expected size, not an exact byte-for-byte limit,
so tiny HTTP size mismatches are accepted while clearly oversized responses are
stopped.

## Rules

Rules are evaluated before a matching book is downloaded. Text metadata rules use `regex` against `Language`, `Author`, `Title`, `Tags`, or `Series`. Size rules use `metadata: Size` with `max_mb`, and are checked per candidate format so an oversized preferred format can fall through to the next allowed format.

Language rules can match either full names such as `Spanish` and `Chinese` or Calibre's three-letter codes such as `spa` and `zho`. When Calibre reports multiple languages for one book, each actual language is evaluated as a group containing both its code and full name. For example, `eng, zho` is treated as two language groups:

```text
eng / English
zho / Chinese
```

By default, regex rules use `match: any`. That means an unwanted-language rule rejects the book if any language group matches the regex. This is useful when any presence of a language should reject the book.

Use `match: all` for unwanted-language rules when mixed-language books should be kept as long as at least one language is acceptable. With this mode, a book is rejected only when every language group matches the unwanted-language regex.

For example, with this rule:

```yaml
- name: Unwanted languages
  metadata: Language
  regex: '^(German|fra|French|Chinese|Spanish|Portuguese)$'
  match: all
  wanted: false
```

These outcomes apply:

- `Chinese` is rejected.
- `French, German` is rejected.
- `English, Chinese` is kept, because `English` does not match the unwanted-language regex.
- `English, French` is kept for the same reason.

## Usage

A great way to find new ones is by using [Shodan](https://www.shodan.io/search?query=%22server%3A+calibre%22).

Pass one Calibre server URL:

```bash
python calibre_downloader.py --servers http://1.2.3.4:8080
```

Pass multiple Calibre server URLs as a comma-separated list:

```bash
python calibre_downloader.py --servers http://1.2.3.4:8080,https://5.6.7.8:443
```

Or pass a text file containing one server URL per line:

```bash
python calibre_downloader.py --servers servers.txt
```

Preview matching downloads without writing files or the database:

```bash
python calibre_downloader.py --servers servers.txt --dry-run
```

Log the rule that rejects each skipped book:

```bash
python calibre_downloader.py --servers servers.txt --explain-rules
```

Scan only one named library from a server:

```bash
python calibre_downloader.py --servers http://1.2.3.4:8080 --library "Calibre Library"
```

Use an alternate rules file:

```bash
python calibre_downloader.py --servers servers.txt --rules test-rules.yaml
```

Inspect only the first five books while testing a server:

```bash
python calibre_downloader.py --servers servers.txt --limit 5
```

Validate local YAML files without contacting any servers:

```bash
python calibre_downloader.py --validate-config
python calibre_downloader.py --validate-rules
```

Show detailed HTTP connection logging while troubleshooting:

```bash
python calibre_downloader.py --servers servers.txt --verbose
```

## Acknowledgments

- Kovid Goyal for creating the excellent application calibre.

## Disclaimer

Use this tool only with libraries and books that you are allowed to access and download. The project does not bypass authentication or access controls.
