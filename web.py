#!/usr/bin/env python3

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from helpers import format_file_size

# Calibre's metadata size can be slightly lower than the actual HTTP body.
# Keep this internal so normal users do not have to tune a safety margin.
DOWNLOAD_SIZE_TOLERANCE_PERCENT = 25
DOWNLOAD_SIZE_TOLERANCE_MIN_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RequestSettings:
    timeout: int | float
    verify: bool = True
    allow_redirects: bool = False


@dataclass(frozen=True)
class HeadResult:
    status: int
    headers: dict
    error: requests.RequestException | None = None


class DownloadSizeLimitExceeded(OSError):
    def __init__(
        self,
        actual_size: int,
        metadata_size: int,
        allowed_size: int,
    ):
        super().__init__(
            f"File size ({format_download_size(actual_size)}) exceeds Calibre "
            f"stated size ({format_download_size(metadata_size)}); "
            f"{format_size_overage(actual_size, metadata_size)} above stated size"
        )


def format_download_size(size_bytes: int) -> str:
    return f"{format_file_size(size_bytes)} ({size_bytes:,} bytes)"


def format_size_overage(actual_size: int, allowed_size: int) -> str:
    if allowed_size <= 0:
        return "unknown amount"

    overage_percent = (actual_size - allowed_size) / allowed_size * 100
    if 0 < overage_percent < 0.1:
        return "<0.1%"
    return f"{overage_percent:.1f}%"


def allowed_download_size(metadata_size: int) -> int:
    tolerance_by_percent = metadata_size * DOWNLOAD_SIZE_TOLERANCE_PERCENT // 100
    tolerance = max(tolerance_by_percent, DOWNLOAD_SIZE_TOLERANCE_MIN_BYTES)
    return metadata_size + tolerance


def uses_https(server_address: str) -> bool:
    return server_address.lower().startswith("https://")


def http_address_for_https(server_address: str) -> str:
    return "http://" + server_address.split("://", 1)[1]


def is_https_to_plain_http_error(error: BaseException | None) -> bool:
    if not isinstance(error, requests.exceptions.SSLError):
        return False

    message = str(error).lower()
    return "wrong version number" in message or "wrong_version_number" in message


def evaluate_server(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
) -> bool:
    return (
        resolve_server_address(
            requests_session,
            server_address,
            request_settings,
        )
        is not None
    )


def resolve_server_address(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
) -> str | None:
    result = evaluate_server_candidate(
        requests_session,
        server_address,
        request_settings,
    )
    if result.connectable:
        return server_address

    if uses_https(server_address) and is_https_to_plain_http_error(result.error):
        fallback_address = http_address_for_https(server_address)
        logging.info(
            "Retrying %s as plain HTTP: %s",
            server_address,
            fallback_address,
        )
        fallback_result = evaluate_server_candidate(
            requests_session,
            fallback_address,
            request_settings,
        )
        if fallback_result.connectable:
            return fallback_address

    return None


@dataclass(frozen=True)
class ServerEvaluationResult:
    connectable: bool
    error: requests.RequestException | None = None


def evaluate_server_candidate(
    requests_session: requests.Session,
    server_address: str,
    request_settings: RequestSettings,
) -> ServerEvaluationResult:
    result = get_head_result(
        requests_session,
        server_address + "/ajax/library-info",
        request_settings,
    )
    if result.status != 200:
        logging.info("Server not reachable or not a Calibre server: %s", server_address)
        return ServerEvaluationResult(False, result.error)

    server_name = result.headers.get("Server", "")
    if not server_name.lower().startswith("calibre"):
        logging.info(
            "Unexpected server header for %s: %s",
            server_address,
            server_name or "<missing>",
        )
        return ServerEvaluationResult(False)

    logging.info("Server %s is a connectable Calibre server", server_address)
    return ServerEvaluationResult(True)


def download_file(
    requests_session: requests.Session,
    file_url: str,
    file_path: str,
    request_settings: RequestSettings,
    max_retries: int = 3,
    retry_backoff: int | float = 2,
    max_bytes: int | None = None,
) -> bool:
    destination_path = Path(file_path)
    partial_path = destination_path.with_name(destination_path.name + ".part")
    size_limit = allowed_download_size(max_bytes) if max_bytes is not None else None

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
            content_length = response.headers.get("Content-Length")
            if size_limit is not None and content_length:
                try:
                    content_length_bytes = int(content_length)
                    if content_length_bytes > size_limit:
                        raise DownloadSizeLimitExceeded(
                            content_length_bytes,
                            max_bytes,
                            size_limit,
                        )
                except ValueError:
                    pass

            destination_path.parent.mkdir(parents=True, exist_ok=True)

            bytes_written = 0
            with partial_path.open("wb") as output_stream:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        if (
                            size_limit is not None
                            and bytes_written + len(chunk) > size_limit
                        ):
                            raise DownloadSizeLimitExceeded(
                                bytes_written + len(chunk),
                                max_bytes,
                                size_limit,
                            )
                        output_stream.write(chunk)
                        bytes_written += len(chunk)

            if partial_path.stat().st_size == 0:
                raise OSError(f"Downloaded file is empty: {file_url}")

            os.replace(partial_path, destination_path)
            return True

        except DownloadSizeLimitExceeded as error:
            logging.warning(error)
            return False

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
        response_data = response.json()
        if not isinstance(response_data, dict):
            return None
        library_map = response_data.get("library_map")
        if not isinstance(library_map, dict):
            return None
        return library_map
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
        response_data = response.json()
        if not isinstance(response_data, dict):
            return None
        return response_data
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
    result = get_head_result(requests_session, url, request_settings)
    return result.status, result.headers


def get_head_result(
    requests_session: requests.Session,
    url: str,
    request_settings: RequestSettings,
) -> HeadResult:
    try:
        response = requests_session.head(
            url,
            timeout=request_settings.timeout,
            verify=request_settings.verify,
            allow_redirects=request_settings.allow_redirects,
        )
        return HeadResult(response.status_code, response.headers)
    except requests.RequestException as error:
        logging.debug("HEAD request failed for %s: %s", url, error)
        return HeadResult(0, {}, error)
    finally:
        if "response" in locals():
            response.close()
