#!/usr/bin/env python3

import logging
import re
from dataclasses import dataclass
from typing import Any

from helpers import format_file_size

COMMON_RULE_KEYS = {"name", "metadata", "wanted"}
SUPPORTED_METADATA = {"Language", "Author", "Title", "Tags", "Series", "Size"}
SUPPORTED_MATCH_MODES = {"any", "all"}
SIZE_BYTES_PER_MB = 1_000_000


@dataclass(frozen=True)
class Rule:
    name: str
    metadata: str
    wanted: bool
    pattern: str = ""
    regex: re.Pattern[str] | None = None
    max_mb: float | None = None
    match: str = "any"


@dataclass(frozen=True)
class RuleDecision:
    wanted: bool
    rule_name: str = ""
    metadata: str = ""
    value: str = ""

    @property
    def reason(self) -> str:
        if not self.rule_name:
            return ""
        return f"{self.rule_name} ({self.metadata}): {self.value}"


def validate_rules(rules: Any) -> list[Rule]:
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")

    parsed_rules = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"rule {index} must be an object")

        missing_keys = sorted(COMMON_RULE_KEYS - rule.keys())
        if missing_keys:
            raise ValueError(
                f"rule {index} is missing required keys: {', '.join(missing_keys)}"
            )

        name = require_rule_string(rule["name"], index, "name")
        metadata = require_rule_string(rule["metadata"], index, "metadata")

        if metadata not in SUPPORTED_METADATA:
            supported_values = ", ".join(sorted(SUPPORTED_METADATA))
            raise ValueError(
                f"rule {index} metadata must be one of: {supported_values}"
            )

        wanted = rule["wanted"]
        if not isinstance(wanted, bool):
            raise ValueError(f"rule {index} wanted must be true or false")

        if metadata == "Size":
            max_mb = require_positive_number(rule.get("max_mb"), index, "max_mb")
            if wanted:
                raise ValueError(f"rule {index} Size rules must set wanted to false")
            parsed_rules.append(
                Rule(
                    name=name,
                    metadata=metadata,
                    wanted=wanted,
                    max_mb=max_mb,
                )
            )
            continue

        pattern = require_rule_string(rule.get("regex"), index, "regex")
        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"rule {index} has invalid regex: {error}") from error

        match = require_match_mode(rule.get("match", "any"), index)

        parsed_rules.append(
            Rule(
                name=name,
                metadata=metadata,
                wanted=wanted,
                pattern=pattern,
                regex=regex,
                match=match,
            )
        )

    return parsed_rules


def require_rule_string(value: Any, index: int, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"rule {index} {key} must be a non-empty string")
    return value


def require_positive_number(value: Any, index: int, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"rule {index} {key} must be a positive number")
    if value <= 0:
        raise ValueError(f"rule {index} {key} must be a positive number")
    return float(value)


def require_match_mode(value: Any, index: int) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_MATCH_MODES:
        supported_values = ", ".join(sorted(SUPPORTED_MATCH_MODES))
        raise ValueError(f"rule {index} match must be one of: {supported_values}")
    return value


def evaluate_book(rules: list[Rule], book_metadata: dict) -> bool:
    """Evaluate if a book is wanted based on the user defined rules."""

    return explain_book(rules, book_metadata).wanted


def explain_book(rules: list[Rule], book_metadata: dict) -> RuleDecision:
    if not rules:
        logging.debug("No rules defined, assuming book is wanted")
        return RuleDecision(wanted=True)

    checks = [
        (
            "Language",
            metadata_value_groups(
                book_metadata.get("language_rule_groups")
                or book_metadata.get("language_rule_values")
                or book_metadata.get("languages", [])
                or []
            ),
        ),
        ("Author", metadata_value_groups(book_metadata.get("authors", []) or [])),
        (
            "Title",
            metadata_value_groups(
                [book_metadata.get("title", "")] if book_metadata.get("title") else []
            ),
        ),
        (
            "Tags",
            metadata_value_groups(
                [tag.strip() for tag in book_metadata.get("tags", []) or []]
            ),
        ),
        (
            "Series",
            metadata_value_groups(
                [book_metadata.get("series", "")] if book_metadata.get("series") else []
            ),
        ),
    ]

    for target_metadata, value_groups in checks:
        decision = check_metadata_rules(rules, target_metadata, value_groups)
        if not decision.wanted:
            logging.debug("Book is not wanted, reason: %s", decision.reason)
            return decision

    return RuleDecision(wanted=True)


def metadata_value_groups(values: Any) -> list[list[str]]:
    if isinstance(values, str):
        values = [values]

    groups = []
    for value in values:
        if isinstance(value, (list, tuple)):
            group = [str(item) for item in value if item not in (None, "")]
        else:
            group = [str(value)] if value not in (None, "") else []
        if group:
            groups.append(group)
    return groups


def explain_format_size(
    rules: list[Rule],
    book_format: str,
    size_bytes: object,
) -> RuleDecision:
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        logging.debug("Skipping size rules for %s: invalid size", book_format)
        return RuleDecision(wanted=True)

    for rule in rules:
        if rule.metadata != "Size" or rule.max_mb is None:
            continue

        max_bytes = rule.max_mb * SIZE_BYTES_PER_MB
        if size > max_bytes:
            decision = RuleDecision(
                wanted=rule.wanted,
                rule_name=rule.name,
                metadata="Size",
                value=(
                    f"{book_format.upper()} {format_file_size(size)} "
                    f"> {format_max_mb(rule.max_mb)}"
                ),
            )
            logging.debug("Book is not wanted, reason: %s", decision.reason)
            return decision

    return RuleDecision(wanted=True)


def format_max_mb(max_mb: float) -> str:
    formatted_size = f"{max_mb:.1f}".removesuffix(".0")
    return f"{formatted_size} MB"


def check_rule(
    rules: list[Rule],
    target_metadata: str,
    input_string: str,
) -> tuple[bool, str]:
    """Check if the input string matches any of the user defined rules."""

    for rule in rules:
        if (
            target_metadata == rule.metadata
            and rule.regex is not None
            and rule.regex.search(input_string or "")
        ):
            return rule.wanted, rule.name

    return True, ""


def check_metadata_rules(
    rules: list[Rule],
    target_metadata: str,
    value_groups: list[list[str]],
) -> RuleDecision:
    for rule in rules:
        if target_metadata != rule.metadata or rule.regex is None:
            continue

        if rule.match == "all":
            if value_groups and all(
                any(rule.regex.search(value or "") for value in group)
                for group in value_groups
            ):
                return RuleDecision(
                    wanted=rule.wanted,
                    rule_name=rule.name,
                    metadata=target_metadata,
                    value=", ".join(group[-1] for group in value_groups),
                )
            continue

        for group in value_groups:
            for value in group:
                if rule.regex.search(value or ""):
                    return RuleDecision(
                        wanted=rule.wanted,
                        rule_name=rule.name,
                        metadata=target_metadata,
                        value=value,
                    )

    return RuleDecision(wanted=True)
