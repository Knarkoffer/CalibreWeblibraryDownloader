#!/usr/bin/env python3

import logging
import sqlite3
import time
from pathlib import Path

BOOK_COLUMNS = [
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
]


CREATE_BOOKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS BOOKS (
    file_hash TEXT NOT NULL,
    title TEXT,
    author_sort TEXT,
    language TEXT,
    identifiers TEXT,
    tags TEXT,
    format TEXT NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    calibre_address TEXT,
    date_added TEXT NOT NULL,
    PRIMARY KEY (file_hash)
);
"""


def ensure_database(database_file: str) -> None:
    database_path = Path(database_file)
    if database_path.parent != Path("."):
        database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_file, timeout=30) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute(CREATE_BOOKS_TABLE_SQL)


def add_item_to_db(
    database_file: str,
    book_details: dict,
    retry_attempts: int = 5,
) -> bool:
    ensure_database(database_file)

    item = {column: book_details.get(column, "") for column in BOOK_COLUMNS}

    if not item.get("file_hash"):
        raise ValueError("book_details must include file_hash")

    columns = ", ".join(item.keys())
    placeholders = ", ".join("?" for _ in item)
    query = f"INSERT INTO BOOKS ({columns}) VALUES ({placeholders})"

    for attempt in range(1, retry_attempts + 1):
        try:
            with sqlite3.connect(database_file, timeout=30) as connection:
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute(query, list(item.values()))
            logging.debug("Item added to database")
            return True

        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                logging.debug("Item already in database")
                return False
            raise RuntimeError(
                f"Could not insert book into database: {error}"
            ) from error

        except sqlite3.OperationalError as error:
            if "database is locked" in str(error).lower() and attempt < retry_attempts:
                logging.debug("Database is locked, retrying")
                time.sleep(min(attempt, 5))
                continue
            raise RuntimeError(f"Could not write to database: {error}") from error

    return False


def was_downloaded_from_calibre_server(
    database_file: str,
    calibre_address: str,
    title: str,
    author_sort: str,
    book_format: str,
    size: int,
) -> bool:
    ensure_database(database_file)

    query = """
    SELECT 1
    FROM BOOKS
    WHERE calibre_address = ?
      AND title = ?
      AND author_sort = ?
      AND format = ?
      AND size = ?
    LIMIT 1
    """
    values = (
        calibre_address,
        title,
        author_sort,
        book_format.upper(),
        size,
    )

    with sqlite3.connect(database_file, timeout=30) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection.execute(query, values).fetchone() is not None
