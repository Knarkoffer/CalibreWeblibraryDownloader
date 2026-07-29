from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

CONFIG_FILE = "config.yaml"


@dataclass(frozen=True)
class ProxyEntry:
    protocol: str
    address: str
    port: int
    auth: bool = False
    username: str = ""
    password: str = ""

    def url(self) -> str:
        auth_part = ""
        if self.auth:
            auth_part = f"{self.username}:{self.password}@"
        return f"{self.protocol}://{auth_part}{self.address}:{self.port}"


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool
    proxies: list[ProxyEntry]


@dataclass(frozen=True)
class AppConfig:
    debug_mode: bool
    wait_time: int | float
    timeout: int | float
    user_agent: str
    storage_path: str
    database_file: str
    logstamp_format: str
    target_formats: list[str]
    proxy: ProxyConfig
    verify_ssl: bool = False
    allow_redirects: bool = False
    download_retries: int = 3
    retry_backoff: int | float = 2
    server_evaluation_timeout: int | float = 0
    max_consecutive_download_failures: int = 10
    skip_global_metadata_duplicates: bool = False
    log_book_author_limit: int = 3
    log_book_entry_max_length: int = 180


REQUIRED_CONFIG_KEYS = {
    "debug_mode",
    "wait_time",
    "timeout",
    "user_agent",
    "storage_path",
    "database_file",
    "logstamp_format",
    "target_formats",
    "proxy",
}


def load_config(config_file: str = CONFIG_FILE) -> AppConfig:
    with pathlib.Path(config_file).open(encoding="utf-8") as config_stream:
        config_data = yaml.safe_load(config_stream) or {}

    if not isinstance(config_data, dict):
        raise ValueError("config must be a YAML mapping")

    return parse_config(config_data)


def parse_config(config_data: dict[str, Any]) -> AppConfig:
    missing_keys = sorted(REQUIRED_CONFIG_KEYS - config_data.keys())
    if missing_keys:
        raise ValueError(f"Missing required config keys: {', '.join(missing_keys)}")

    proxy_data = require_mapping(config_data["proxy"], "proxy")
    proxies_data = proxy_data.get("proxies", [])
    if not isinstance(proxies_data, list):
        raise ValueError("config proxy.proxies must be a list")

    proxy_enabled = require_bool(proxy_data.get("enabled"), "proxy.enabled")
    proxies = [
        parse_proxy_entry(proxy_config, index, proxy_enabled)
        for index, proxy_config in enumerate(proxies_data, start=1)
    ]
    if proxy_enabled and not proxies:
        raise ValueError("config proxy.proxies must not be empty when proxy is enabled")

    target_formats = config_data["target_formats"]
    if not isinstance(target_formats, list) or not target_formats:
        raise ValueError("config target_formats must be a non-empty list")
    if not all(isinstance(item, str) and item for item in target_formats):
        raise ValueError("config target_formats must only contain non-empty strings")

    download_retries = config_data.get("download_retries", 3)
    if not isinstance(download_retries, int) or download_retries < 1:
        raise ValueError("config download_retries must be a positive integer")

    retry_backoff = require_non_negative_number(
        config_data.get("retry_backoff", 2),
        "retry_backoff",
    )
    server_evaluation_timeout = require_non_negative_number(
        config_data.get("server_evaluation_timeout", config_data["timeout"]),
        "server_evaluation_timeout",
    )
    max_consecutive_download_failures = require_non_negative_integer(
        config_data.get("max_consecutive_download_failures", 10),
        "max_consecutive_download_failures",
    )
    log_book_author_limit = require_non_negative_integer(
        config_data.get("log_book_author_limit", 3),
        "log_book_author_limit",
    )
    log_book_entry_max_length = require_non_negative_integer(
        config_data.get("log_book_entry_max_length", 180),
        "log_book_entry_max_length",
    )

    return AppConfig(
        debug_mode=require_bool(config_data["debug_mode"], "debug_mode"),
        wait_time=require_non_negative_number(config_data["wait_time"], "wait_time"),
        timeout=require_non_negative_number(config_data["timeout"], "timeout"),
        user_agent=require_non_empty_string(config_data["user_agent"], "user_agent"),
        storage_path=require_non_empty_string(
            config_data["storage_path"],
            "storage_path",
        ),
        database_file=require_non_empty_string(
            config_data["database_file"],
            "database_file",
        ),
        logstamp_format=require_non_empty_string(
            config_data["logstamp_format"],
            "logstamp_format",
        ),
        target_formats=target_formats,
        proxy=ProxyConfig(enabled=proxy_enabled, proxies=proxies),
        verify_ssl=require_bool(config_data.get("verify_ssl", False), "verify_ssl"),
        allow_redirects=require_bool(
            config_data.get("allow_redirects", False),
            "allow_redirects",
        ),
        download_retries=download_retries,
        retry_backoff=retry_backoff,
        server_evaluation_timeout=server_evaluation_timeout,
        max_consecutive_download_failures=max_consecutive_download_failures,
        skip_global_metadata_duplicates=require_bool(
            config_data.get("skip_global_metadata_duplicates", False),
            "skip_global_metadata_duplicates",
        ),
        log_book_author_limit=log_book_author_limit,
        log_book_entry_max_length=log_book_entry_max_length,
    )


def parse_proxy_entry(
    proxy_config: Any,
    index: int,
    proxy_enabled: bool,
) -> ProxyEntry:
    proxy_mapping = require_mapping(proxy_config, f"proxy.proxies[{index}]")
    protocol = require_non_empty_string(
        proxy_mapping.get("protocol"),
        f"proxy.proxies[{index}].protocol",
    )
    address = str(proxy_mapping.get("address", "") or "")
    port = proxy_mapping.get("port", 0)
    auth = require_bool(
        proxy_mapping.get("auth", False), f"proxy.proxies[{index}].auth"
    )
    username = str(proxy_mapping.get("username", "") or "")
    password = str(proxy_mapping.get("password", "") or "")

    if proxy_enabled:
        if not address:
            raise ValueError(f"config proxy.proxies[{index}].address is required")
        if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
            raise ValueError(f"config proxy.proxies[{index}].port must be positive")

    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError(f"config proxy.proxies[{index}].port must be an integer")

    return ProxyEntry(
        protocol=protocol,
        address=address,
        port=port,
        auth=auth,
        username=username,
        password=password,
    )


def require_mapping(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"config {key} must be an object")
    return value


def require_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"config {key} must be true or false")
    return value


def require_non_empty_string(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"config {key} must be a non-empty string")
    return value


def require_non_negative_number(value: Any, key: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"config {key} must be a non-negative number")
    return value


def require_non_negative_integer(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"config {key} must be a non-negative integer")
    return value
