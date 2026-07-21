# Calibre Weblibrary Downloader

Calibre Weblibrary Downloader downloads ebooks from publicly accessible Calibre web libraries, applies rule-based metadata filters, and keeps a local SQLite record of downloaded files to avoid duplicates.

## Features

- Download books from Calibre web libraries with anonymous access enabled.
- Prefer ebook formats according to the configured priority order.
- Skip unwanted books with regular-expression rules for language, author, title, tag, or series metadata.
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
- `proxy` can be enabled when downloads should go through an HTTP or HTTPS proxy.
- `download_retries` and `retry_backoff` control retry behavior for failed downloads.

Copy `rules.example.yaml` to `rules.yaml`, then edit `rules.yaml` to skip books that match unwanted metadata. The local `rules.yaml` file is ignored by Git so each user can keep their own filtering preferences. If no rules are defined, matching Calibre libraries are treated as downloadable.

Copy `books.example.sqlite` to `books.sqlite` before first use if you want to start from the bundled empty tracking database. Keep a backup if you rely on it to prevent duplicate downloads across runs.

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

## Acknowledgments

- Kovid Goyal for creating the excellent application calibre.

## Disclaimer

Use this tool only with libraries and books that you are allowed to access and download. The project does not bypass authentication or access controls.
