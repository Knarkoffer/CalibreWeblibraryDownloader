#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import os
import platform
import re
import sys
import time
import uuid
from dataclasses import dataclass

import requests
import yaml

try:
    from iso639 import Lang
except ModuleNotFoundError as error:
    if error.name != "iso639":
        raise
    Lang = None

from config_loader import CONFIG_FILE, AppConfig, load_config
from database import (
    BookSourceKey,
    add_item_to_db,
    book_source_key,
    downloaded_book_keys,
    downloaded_book_keys_for_calibre_server,
    ensure_database,
)
from helpers import (
    argument_to_list,
    ascii_filename_segment,
    filter_and_sort,
    fix_windows_filenames,
    format_file_size,
    generate_filehash,
)
from rules import Rule, explain_book, explain_format_size, validate_rules
from web import (
    RequestSettings,
    download_file,
    list_libraries,
    list_library_content,
    resolve_server_address,
)

RULES_FILE = "rules.yaml"
LANGUAGE_DEPENDENCY_MESSAGE = (
    "Missing required dependency iso639-lang. Activate the project virtual "
    "environment or install dependencies with `python -m pip install -e .`."
)
BOOK_ENTRY_SEPARATOR = "-" * 30
DEFAULT_LOG_BOOK_AUTHOR_LIMIT = 3
DEFAULT_LOG_BOOK_ENTRY_MAX_LENGTH = 180


class DependencyError(RuntimeError):
    pass


@dataclass
class RunOptions:
    dry_run: bool = False
    explain_rules: bool = False
    limit: int | None = None
    library: str | None = None
    verbose: bool = False


@dataclass
class RunStats:
    servers_evaluated: int = 0
    servers_connectable: int = 0
    libraries_scanned: int = 0
    books_seen: int = 0
    books_rejected: int = 0
    books_without_preferred_format: int = 0
    books_skipped_metadata: int = 0
    books_already_present: int = 0
    books_skipped_global_metadata_duplicates: int = 0
    downloads_planned: int = 0
    downloads_attempted: int = 0
    downloads_succeeded: int = 0
    downloads_failed: int = 0
    database_inserts: int = 0
    database_duplicates: int = 0


def load_rules(rules_file: str = RULES_FILE) -> list[Rule]:
    with open(rules_file, encoding="utf-8") as rules_stream:
        rules_data = yaml.safe_load(rules_stream) or {}

    rules = rules_data.get("rules", [])
    return validate_rules(rules)


def configure_logging(config: AppConfig, verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if config.debug_mode or verbose else logging.INFO,
        format=config.logstamp_format,
    )
    logging.getLogger("urllib3").setLevel(logging.DEBUG if verbose else logging.WARNING)


def build_proxy_dict(config: AppConfig) -> dict[str, str]:
    if not config.proxy.enabled:
        return {}

    return {proxy.protocol: proxy.url() for proxy in config.proxy.proxies}


def build_requests_session(config: AppConfig) -> requests.Session:
    requests_session = requests.Session()
    requests_session.headers.update({"User-Agent": config.user_agent})
    requests_session.proxies.update(build_proxy_dict(config))
    return requests_session


def build_request_settings(config: AppConfig) -> RequestSettings:
    return RequestSettings(
        timeout=config.timeout,
        verify=config.verify_ssl,
        allow_redirects=config.allow_redirects,
    )


def build_server_evaluation_request_settings(
    config: AppConfig,
    request_settings: RequestSettings,
) -> RequestSettings:
    timeout = getattr(config, "server_evaluation_timeout", None)
    if timeout is None:
        timeout = request_settings.timeout

    return RequestSettings(
        timeout=timeout,
        verify=request_settings.verify,
        allow_redirects=request_settings.allow_redirects,
    )


def normalize_server_address(server_url: str) -> str:
    candidate = server_url.strip()
    if not re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        candidate = f"http://{candidate}"

    match = re.fullmatch(r"(https?://[^/\s]+)/*", candidate, flags=re.IGNORECASE)
    if not match:
        raise ValueError(
            "Server entries must be a hostname or base URL without a path: "
            f"{server_url!r}"
        )

    return match.group(1).lower()


def require_language_dependency() -> None:
    if Lang is None:
        raise DependencyError(LANGUAGE_DEPENDENCY_MESSAGE)


def language_names(language_codes: list[str]) -> list[str]:
    require_language_dependency()

    names = []
    for language_code in language_codes:
        try:
            names.append(Lang(language_code).name)
        except (KeyError, ValueError):
            names.append(language_code)
    return names


def language_rule_values(language_codes: list[str]) -> list[str]:
    values = []
    for group in language_rule_groups(language_codes):
        for value in group:
            if value not in values:
                values.append(value)
    return values


def language_rule_groups(language_codes: list[str]) -> list[list[str]]:
    language_names_for_codes = language_names(language_codes)
    groups = []
    for language_code, language_name in zip(
        language_codes,
        language_names_for_codes,
        strict=True,
    ):
        group = []
        for value in (language_code, language_name):
            if value not in group:
                group.append(value)
        groups.append(group)
    return groups


def author_display(book_metadata: dict, max_authors: int | None = None) -> str:
    authors = book_metadata.get("authors") or []
    if not isinstance(authors, list):
        return str(authors)
    if not authors:
        return "Unknown Author"
    visible_authors = [str(author) for author in authors if author]
    if not visible_authors:
        return "Unknown Author"
    if max_authors and len(visible_authors) > max_authors:
        remaining_authors = len(visible_authors) - max_authors
        visible_authors = visible_authors[:max_authors] + [f"{remaining_authors} more"]
    return " & ".join(visible_authors)


def filename_author_display(book_metadata: dict) -> str:
    authors = book_metadata.get("authors") or []
    if not isinstance(authors, list):
        return str(authors)
    return next((str(author) for author in authors if author), "Unknown Author")


def book_author_title_display(
    book_metadata: dict,
    max_authors: int | None = None,
) -> str:
    book_title = str(book_metadata.get("title") or "Untitled")
    return f"{author_display(book_metadata, max_authors)} - {book_title}"


def book_label(book_metadata: dict, max_authors: int | None = None) -> str:
    book_id = book_metadata.get("application_id", "unknown")
    return f"{book_id} - {book_author_title_display(book_metadata, max_authors)}"


def log_book_author_limit(config: AppConfig) -> int:
    return getattr(config, "log_book_author_limit", DEFAULT_LOG_BOOK_AUTHOR_LIMIT)


def log_book_entry_max_length(config: AppConfig) -> int:
    return getattr(
        config,
        "log_book_entry_max_length",
        DEFAULT_LOG_BOOK_ENTRY_MAX_LENGTH,
    )


def truncate_log_text(value: str, max_length: int) -> str:
    if max_length <= 0 or len(value) <= max_length:
        return value
    if max_length <= 3:
        return "." * max_length
    return value[: max_length - 3].rstrip() + "..."


def log_book_entry(
    config: AppConfig,
    level: int,
    message: str,
    *args,
) -> None:
    if args:
        message = message % args
    logging.log(level, truncate_log_text(message, log_book_entry_max_length(config)))


def log_server_list_loaded(server_count: int) -> None:
    server_word = "server" if server_count == 1 else "servers"
    logging.info("Server list loaded, connecting to %s %s", server_count, server_word)


def hashed_book_filename(book_metadata: dict, book_format: str, file_hash: str) -> str:
    book_title = str(book_metadata.get("title") or "Untitled")
    safe_file_hash = ascii_filename_segment(file_hash, fallback="HASH")
    safe_book_format = ascii_filename_segment(book_format, fallback="book").lower()
    preserved_suffix = f" [{safe_file_hash}].{safe_book_format}"
    return fix_windows_filenames(
        f"{filename_author_display(book_metadata)} - {book_title}{preserved_suffix}",
        preserved_suffix=preserved_suffix,
    )


def temporary_download_path(
    destination_dir: str,
    book_format: str,
) -> str:
    safe_book_format = ascii_filename_segment(book_format, fallback="download")
    return os.path.join(
        destination_dir,
        f".download-{os.getpid()}-{uuid.uuid4().hex}.{safe_book_format}",
    )


def library_display_name(library_id: str, library_details: object) -> str:
    if isinstance(library_details, dict):
        return str(library_details.get("name", library_id))
    return str(library_details)


def log_library_list(server_address: str, libraries: dict) -> None:
    logging.info("Libraries found at %s:", server_address)
    for library_id, library_details in libraries.items():
        logging.info(
            "  %s (%s)", library_display_name(library_id, library_details), library_id
        )


def log_library_book_count(library_name: str, library_content: dict) -> None:
    logging.info("Library %s contains %s books", library_name, len(library_content))


def library_matches(library_id: str, library_details: object, requested: str) -> bool:
    requested_value = requested.casefold()
    return requested_value in {
        library_id.casefold(),
        library_display_name(library_id, library_details).casefold(),
    }


def filter_libraries(libraries: dict, requested_library: str | None) -> dict:
    if not requested_library:
        return libraries

    return {
        library_id: library_details
        for library_id, library_details in libraries.items()
        if library_matches(library_id, library_details, requested_library)
    }


def iter_library_books(library_content: dict):
    for book_id, book_metadata in library_content.items():
        if isinstance(book_metadata, dict):
            yield str(book_id), dict(book_metadata)


def get_download_links(book_metadata: dict) -> dict:
    links = {}
    main_format = book_metadata.get("main_format")
    other_formats = book_metadata.get("other_formats")

    if isinstance(main_format, dict):
        links.update(main_format)
    if isinstance(other_formats, dict):
        links.update(other_formats)

    return links


def get_format_details(book_metadata: dict, book_format: str) -> dict | None:
    format_metadata = book_metadata.get("format_metadata")
    if not isinstance(format_metadata, dict):
        logging.debug("Skipping format %s: missing format metadata", book_format)
        return None

    metadata = format_metadata.get(book_format)
    if not isinstance(metadata, dict):
        logging.debug("Skipping format %s: missing format metadata", book_format)
        return None

    required_keys = ("size", "path")
    missing_keys = [key for key in required_keys if key not in metadata]
    if missing_keys:
        logging.debug(
            "Skipping format %s: missing metadata keys %s",
            book_format,
            ", ".join(missing_keys),
        )
        return None

    return metadata


def download_failure_limit_reached(config: AppConfig, failure_count: int) -> bool:
    failure_limit = getattr(config, "max_consecutive_download_failures", 0)
    return failure_limit > 0 and failure_count >= failure_limit


def browse_library(
    library_content: dict,
    server_address: str,
    requests_session: requests.Session,
    request_settings: RequestSettings,
    config: AppConfig,
    rules: list[Rule],
    options: RunOptions,
    stats: RunStats,
    downloaded_server_books: set[BookSourceKey] | None = None,
    downloaded_global_books: set[BookSourceKey] | None = None,
    consecutive_download_failures: int = 0,
) -> int:
    if downloaded_server_books is None:
        downloaded_server_books = set()
    if downloaded_global_books is None:
        downloaded_global_books = set()

    total_books = len(library_content)
    for book_number, (fallback_book_id, book_metadata) in enumerate(
        iter_library_books(library_content),
        start=1,
    ):
        if options.limit is not None and stats.books_seen >= options.limit:
            return consecutive_download_failures

        if stats.books_seen:
            logging.debug(BOOK_ENTRY_SEPARATOR)
        stats.books_seen += 1
        language_codes = book_metadata.get("languages", [])
        book_metadata["language_rule_groups"] = language_rule_groups(language_codes)
        book_metadata["language_rule_values"] = language_rule_values(language_codes)
        book_metadata["languages"] = language_names(language_codes)
        book_title = str(book_metadata.get("title") or "Untitled")
        book_log_label = book_author_title_display(
            book_metadata,
            log_book_author_limit(config),
        )
        log_book_entry(
            config,
            logging.DEBUG,
            "Evaluating %s/%s: %s",
            book_number,
            total_books,
            book_log_label,
        )

        available_formats = book_metadata.get("formats") or []
        if not isinstance(available_formats, list):
            stats.books_skipped_metadata += 1
            log_book_entry(
                config,
                logging.DEBUG,
                "Skipping %s: invalid formats metadata",
                book_title,
            )
            continue

        book_formats = filter_and_sort(available_formats, config.target_formats)
        if not book_formats:
            stats.books_without_preferred_format += 1
            log_book_entry(
                config,
                logging.DEBUG,
                "Skipping %s: no preferred formats available",
                book_title,
            )
            continue

        rule_decision = explain_book(rules, book_metadata)
        if not rule_decision.wanted:
            stats.books_rejected += 1
            if options.explain_rules:
                log_book_entry(
                    config,
                    logging.INFO,
                    "Rejected %s: %s",
                    book_label(book_metadata, log_book_author_limit(config)),
                    rule_decision.reason,
                )
            continue

        downloaded_or_present = False
        acceptable_format_seen = False
        size_rejections = []
        download_links = get_download_links(book_metadata)
        book_id = str(book_metadata.get("application_id", fallback_book_id))

        for book_format in book_formats:
            if downloaded_or_present:
                break

            format_details = get_format_details(book_metadata, book_format)
            if not format_details:
                stats.books_skipped_metadata += 1
                continue

            download_path = download_links.get(book_format)
            if not download_path:
                stats.books_skipped_metadata += 1
                logging.debug(
                    "Skipping %s %s: missing download link", book_id, book_format
                )
                continue

            book_format_lcase = book_format.lower()
            file_size_b = format_details["size"]

            size_decision = explain_format_size(rules, book_format, file_size_b)
            if not size_decision.wanted:
                size_rejections.append(size_decision)
                if options.explain_rules:
                    log_book_entry(
                        config,
                        logging.INFO,
                        "Rejected %s as %s: %s",
                        book_label(book_metadata, log_book_author_limit(config)),
                        book_format.upper(),
                        size_decision.reason,
                    )
                continue

            acceptable_format_seen = True
            source_key = book_source_key(
                book_metadata.get("title", ""),
                book_metadata.get("author_sort", ""),
                book_format,
                file_size_b,
            )

            if options.dry_run:
                stats.downloads_planned += 1
                log_book_entry(
                    config,
                    logging.INFO,
                    "Would download %s [%s].%s",
                    book_log_label,
                    "HASH",
                    book_format_lcase,
                )
                downloaded_or_present = True
                continue

            if source_key in downloaded_server_books:
                stats.books_already_present += 1
                log_book_entry(
                    config,
                    logging.INFO,
                    "Skipping %s as %s: downloaded from this Calibre server previously",
                    book_log_label,
                    book_format.upper(),
                )
                downloaded_or_present = True
                continue

            if source_key in downloaded_global_books:
                stats.books_skipped_global_metadata_duplicates += 1
                log_book_entry(
                    config,
                    logging.INFO,
                    "Skipping %s as %s: matching title, author, format, and size "
                    "already exist in the database",
                    book_log_label,
                    book_format.upper(),
                )
                downloaded_or_present = True
                continue

            destination_dir = os.path.join(config.storage_path, book_format_lcase)
            download_file_path = temporary_download_path(
                destination_dir,
                book_format_lcase,
            )
            download_url = server_address + download_path

            log_book_entry(
                config,
                logging.DEBUG,
                "Downloading %s as %s (%s)",
                book_log_label,
                book_format.upper(),
                format_file_size(file_size_b),
            )

            os.makedirs(destination_dir, exist_ok=True)
            stats.downloads_attempted += 1
            if not download_file(
                requests_session,
                download_url,
                download_file_path,
                request_settings,
                max_retries=config.download_retries,
                retry_backoff=config.retry_backoff,
            ):
                stats.downloads_failed += 1
                consecutive_download_failures += 1
                if download_failure_limit_reached(
                    config,
                    consecutive_download_failures,
                ):
                    logging.info(
                        "Stopping downloads from %s after %s consecutive failed "
                        "download attempts",
                        server_address,
                        consecutive_download_failures,
                    )
                    return consecutive_download_failures
                continue

            stats.downloads_succeeded += 1
            consecutive_download_failures = 0
            downloaded_or_present = True
            file_hash = generate_filehash(download_file_path)
            destination_filename = hashed_book_filename(
                book_metadata,
                book_format_lcase,
                file_hash,
            )
            destination_file_path = os.path.join(destination_dir, destination_filename)
            book_identifiers = [
                f"{key}:{value}"
                for key, value in book_metadata.get("identifiers", {}).items()
            ]
            downloaded_book_details = {
                "file_hash": file_hash,
                "title": book_metadata.get("title", ""),
                "author_sort": book_metadata.get("author_sort", ""),
                "language": ", ".join(book_metadata.get("languages", [])),
                "identifiers": ", ".join(book_identifiers),
                "tags": ", ".join(book_metadata.get("tags", [])),
                "format": book_format.upper(),
                "filename": destination_filename,
                "size": file_size_b,
                "calibre_address": server_address,
                "date_added": time.strftime("%Y-%m-%d"),
            }

            if add_item_to_db(config.database_file, downloaded_book_details):
                downloaded_server_books.add(source_key)
                downloaded_global_books.add(source_key)
                stats.database_inserts += 1
                if os.path.isfile(destination_file_path):
                    stats.books_already_present += 1
                    logging.debug("File exists: %s", destination_file_path)
                    os.remove(download_file_path)
                else:
                    os.replace(download_file_path, destination_file_path)
                    logging.debug("Saved %s", destination_file_path)
            else:
                downloaded_server_books.add(source_key)
                downloaded_global_books.add(source_key)
                stats.database_duplicates += 1
                logging.debug(
                    "Duplicate file hash %s, removing downloaded file",
                    file_hash,
                )
                os.remove(download_file_path)
            time.sleep(config.wait_time)

        if size_rejections and not acceptable_format_seen and not downloaded_or_present:
            stats.books_rejected += 1

    return consecutive_download_failures


def iter_server_addresses(server_urls: list[str]):
    for server_url in server_urls:
        try:
            yield normalize_server_address(server_url)
        except ValueError as error:
            logging.error(error)


def process_servers(
    server_urls: list[str],
    requests_session: requests.Session,
    request_settings: RequestSettings,
    config: AppConfig,
    rules: list[Rule],
    options: RunOptions,
) -> RunStats:
    stats = RunStats()
    server_evaluation_request_settings = build_server_evaluation_request_settings(
        config,
        request_settings,
    )
    downloaded_global_books = set()
    if (
        getattr(config, "skip_global_metadata_duplicates", False)
        and not options.dry_run
    ):
        downloaded_global_books = downloaded_book_keys(config.database_file)
        logging.info(
            "Loaded %s global book metadata records for duplicate pre-checking; "
            "this may use more memory on large databases",
            len(downloaded_global_books),
        )

    log_server_list_loaded(len(server_urls))

    for server_address in iter_server_addresses(server_urls):
        stats.servers_evaluated += 1
        logging.info("Evaluating server %s", server_address)
        resolved_server_address = resolve_server_address(
            requests_session,
            server_address,
            server_evaluation_request_settings,
        )
        if resolved_server_address is None:
            continue
        server_address = resolved_server_address

        stats.servers_connectable += 1
        logging.info("Listing libraries")
        libraries = list_libraries(requests_session, server_address, request_settings)
        if not libraries:
            logging.info("No libraries found at %s", server_address)
            continue

        log_library_list(server_address, libraries)
        libraries_to_scan = filter_libraries(libraries, options.library)
        if not libraries_to_scan:
            logging.info(
                "No library matching %r found at %s",
                options.library,
                server_address,
            )
            continue

        downloaded_server_books = set()
        consecutive_download_failures = 0
        if not options.dry_run:
            downloaded_server_books = downloaded_book_keys_for_calibre_server(
                config.database_file,
                server_address,
            )
            logging.debug(
                "Loaded %s previously downloaded book records for %s",
                len(downloaded_server_books),
                server_address,
            )

        for library_id, library_details in libraries_to_scan.items():
            if options.limit is not None and stats.books_seen >= options.limit:
                logging.info("Stopping after reaching limit of %s books", options.limit)
                return stats

            stats.libraries_scanned += 1
            library_name = library_display_name(library_id, library_details)
            logging.info("Listing content for library: %s", library_name)
            library_content = list_library_content(
                requests_session,
                server_address,
                request_settings,
                library_id,
            )
            if library_content is not None:
                log_library_book_count(library_name, library_content)
            if library_content:
                consecutive_download_failures = browse_library(
                    library_content,
                    server_address,
                    requests_session,
                    request_settings,
                    config,
                    rules,
                    options,
                    stats,
                    downloaded_server_books,
                    downloaded_global_books,
                    consecutive_download_failures,
                )
                if download_failure_limit_reached(
                    config,
                    consecutive_download_failures,
                ):
                    break

    return stats


def positive_int(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error

    if parsed_value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed_value


def log_summary(stats: RunStats, options: RunOptions) -> None:
    mode = "dry-run" if options.dry_run else "download"
    logging.info(
        "Summary [%s]: servers %s/%s connectable, libraries %s, books %s, "
        "rejected %s, no preferred format %s, metadata skips %s, already present %s, "
        "global metadata duplicates %s, planned %s, attempted %s, downloaded %s, "
        "failed %s, db inserts %s, db duplicates %s",
        mode,
        stats.servers_connectable,
        stats.servers_evaluated,
        stats.libraries_scanned,
        stats.books_seen,
        stats.books_rejected,
        stats.books_without_preferred_format,
        stats.books_skipped_metadata,
        stats.books_already_present,
        stats.books_skipped_global_metadata_duplicates,
        stats.downloads_planned,
        stats.downloads_attempted,
        stats.downloads_succeeded,
        stats.downloads_failed,
        stats.database_inserts,
        stats.database_duplicates,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=os.path.basename(__file__),
        description="Download books from a public Calibre library.",
        epilog=(
            "Use either a server address like 127.0.0.1:8080 or a text file "
            "with one server per line. Memory-intensive global metadata duplicate "
            "pre-checking is controlled in config.yaml, not by a command flag."
        ),
    )
    parser.add_argument(
        "-s",
        "--servers",
        type=argument_to_list,
        default=[],
        help="server list, comma separated servers, or a file with one server per line",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=CONFIG_FILE,
        help=f"path to YAML config file, defaults to {CONFIG_FILE}",
    )
    parser.add_argument(
        "-r",
        "--rules",
        default=RULES_FILE,
        help=f"path to YAML rules file, defaults to {RULES_FILE}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list matching downloads without writing files or the database",
    )
    parser.add_argument(
        "--explain-rules",
        action="store_true",
        help="log the rule that rejects each skipped book",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="stop after inspecting this many books",
    )
    parser.add_argument(
        "--library",
        help="only scan the library with this id or display name",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show detailed HTTP connection logging",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="validate the YAML config file and exit",
    )
    parser.add_argument(
        "--validate-rules",
        action="store_true",
        help="validate the YAML rules file and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_config:
            load_config(args.config)
            print(f"Config OK: {args.config}")

        if args.validate_rules:
            rules = load_rules(args.rules)
            print(f"Rules OK: {args.rules} ({len(rules)} rules)")

        if args.validate_config or args.validate_rules:
            return 0

        if not args.servers:
            parser.print_help(sys.stderr)
            return 1

        config = load_config(args.config)
        rules = load_rules(args.rules)
        require_language_dependency()
    except DependencyError as error:
        print(f"Dependency error: {error}", file=sys.stderr)
        return 1
    except (
        FileNotFoundError,
        ValueError,
        yaml.YAMLError,
    ) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    configure_logging(config, verbose=args.verbose)
    if not config.verify_ssl:
        requests.packages.urllib3.disable_warnings()

    if platform.system() == "Windows":
        os.system("cls")

    options = RunOptions(
        dry_run=args.dry_run,
        explain_rules=args.explain_rules,
        limit=args.limit,
        library=args.library,
        verbose=args.verbose,
    )
    if not options.dry_run:
        os.makedirs(config.storage_path, exist_ok=True)
        ensure_database(config.database_file)

    requests_session = build_requests_session(config)
    request_settings = build_request_settings(config)
    stats = process_servers(
        args.servers,
        requests_session,
        request_settings,
        config,
        rules,
        options,
    )
    log_summary(stats, options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
