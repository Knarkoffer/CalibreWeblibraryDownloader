#!/usr/bin/env python3

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass(frozen=True)
class RequestSettings:
    timeout: int | float
    verify: bool = True
    allow_redirects: bool = False


def evaluate_server(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
) -> bool:
    status, headers = get_head(
        requests_session,
        server_address + "/ajax/library-info",
        request_settings,
    )
    if status != 200:
        logging.info("Server not reachable or not a Calibre server: %s", server_address)
        return False

    server_name = headers.get("Server", "")
    if not server_name.lower().startswith("calibre"):
        logging.info(
            "Unexpected server header for %s: %s",
            server_address,
            server_name or "<missing>",
        )
        return False

    logging.info("Server %s is a connectable Calibre server", server_address)
    return True


def download_file(
    requests_session: requests.Session,
    file_url: str,
    file_path: str,
    request_settings: RequestSettings,
    max_retries: int = 3,
    retry_backoff: int | float = 2,
) -> bool:
    destination_path = Path(file_path)
    partial_path = destination_path.with_name(destination_path.name + ".part")

    if destination_path.is_file():
        logging.debug("File already exists: %s", destination_path)
        return False

    attempts = max(1, max_retries)
    for attempt in range(1, attempts + 1):
        response = None
        try:
            response = requests_session.get(
                file_url,
                stream=True,
                timeout=request_settings.timeout,
                verify=request_settings.verify,
                allow_redirects=request_settings.allow_redirects,
            )
            response.raise_for_status()
            destination_path.parent.mkdir(parents=True, exist_ok=True)

            with partial_path.open("wb") as output_stream:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        output_stream.write(chunk)

            if partial_path.stat().st_size == 0:
                raise OSError(f"Downloaded file is empty: {file_url}")

            os.replace(partial_path, destination_path)
            return True

        except (OSError, requests.RequestException) as error:
            if attempt >= attempts:
                logging.debug("Download failed for %s: %s", file_url, error)
                return False

            delay = retry_backoff * (2 ** (attempt - 1))
            logging.debug(
                "Download failed for %s on attempt %s/%s: %s; retrying in %.1fs",
                file_url,
                attempt,
                attempts,
                error,
                delay,
            )
            if delay:
                time.sleep(delay)

        finally:
            if response is not None:
                response.close()
            if partial_path.exists():
                partial_path.unlink()

    return False


def list_libraries(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
) -> dict | None:
    request_url = server_address + "/ajax/library-info"
    try:
        response = requests_session.get(
            request_url,
            timeout=request_settings.timeout,
            verify=request_settings.verify,
            allow_redirects=request_settings.allow_redirects,
        )
        response.raise_for_status()
        return response.json().get("library_map")
    except (json.JSONDecodeError, requests.RequestException, ValueError) as error:
        logging.debug("Could not list libraries from %s: %s", request_url, error)
        return None
    finally:
        if "response" in locals():
            response.close()


def list_library_content(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
    library_id: str = "Calibre_Library",
) -> dict | None:
    request_url = server_address + f"/ajax/books/{library_id}"
    try:
        response = requests_session.get(
            request_url,
            timeout=request_settings.timeout,
            verify=request_settings.verify,
            allow_redirects=request_settings.allow_redirects,
        )
        response.raise_for_status()
        return response.json()
    except (json.JSONDecodeError, requests.RequestException, ValueError) as error:
        logging.debug("Could not list library content from %s: %s", request_url, error)
        return None
    finally:
        if "response" in locals():
            response.close()


def get_head(
    requests_session: requests.Session,
    url: str,
    request_settings: RequestSettings,
) -> tuple[int, dict]:
    try:
        response = requests_session.head(
            url,
            timeout=request_settings.timeout,
            verify=request_settings.verify,
            allow_redirects=request_settings.allow_redirects,
        )
        return response.status_code, response.headers
    except requests.RequestException as error:
        logging.debug("HEAD request failed for %s: %s", url, error)
        return 0, {}
    finally:
        if "response" in locals():
            response.close()
