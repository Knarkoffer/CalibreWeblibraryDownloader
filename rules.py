#!/usr/bin/env python3

import logging
import re
from dataclasses import dataclass
from typing import Any

REQUIRED_RULE_KEYS = {"name", "metadata", "regex", "wanted"}
SUPPORTED_METADATA = {"Language", "Author", "Title", "Tags", "Series"}


@dataclass(frozen=True)
class Rule:
    name: str
    metadata: str
    pattern: str
    wanted: bool
    regex: re.Pattern[str]


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

        missing_keys = sorted(REQUIRED_RULE_KEYS - rule.keys())
        if missing_keys:
            raise ValueError(
                f"rule {index} is missing required keys: {', '.join(missing_keys)}"
            )

        name = require_rule_string(rule["name"], index, "name")
        metadata = require_rule_string(rule["metadata"], index, "metadata")
        pattern = require_rule_string(rule["regex"], index, "regex")

        if metadata not in SUPPORTED_METADATA:
            supported_values = ", ".join(sorted(SUPPORTED_METADATA))
            raise ValueError(
                f"rule {index} metadata must be one of: {supported_values}"
            )

        wanted = rule["wanted"]
        if not isinstance(wanted, bool):
            raise ValueError(f"rule {index} wanted must be true or false")

        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"rule {index} has invalid regex: {error}") from error

        parsed_rules.append(
            Rule(
                name=name,
                metadata=metadata,
                pattern=pattern,
                wanted=wanted,
                regex=regex,
            )
        )

    return parsed_rules


def require_rule_string(value: Any, index: int, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"rule {index} {key} must be a non-empty string")
    return value


def evaluate_book(rules: list[Rule], book_metadata: dict) -> bool:
    """Evaluate if a book is wanted based on the user defined rules."""

    return explain_book(rules, book_metadata).wanted


def explain_book(rules: list[Rule], book_metadata: dict) -> RuleDecision:
    if not rules:
        logging.debug("No rules defined, assuming book is wanted")
        return RuleDecision(wanted=True)

    checks = [
        ("Language", book_metadata.get("languages", []) or []),
        ("Author", book_metadata.get("authors", []) or []),
        (
            "Title",
            [book_metadata.get("title", "")] if book_metadata.get("title") else [],
        ),
        ("Tags", [tag.strip() for tag in book_metadata.get("tags", []) or []]),
        (
            "Series",
            [book_metadata.get("series", "")] if book_metadata.get("series") else [],
        ),
    ]

    for target_metadata, values in checks:
        for value in values:
            book_wanted, rule_name = check_rule(rules, target_metadata, value)
            if not book_wanted:
                decision = RuleDecision(
                    wanted=False,
                    rule_name=rule_name,
                    metadata=target_metadata,
                    value=value,
                )
                logging.debug("Book is not wanted, reason: %s", decision.reason)
                return decision

    return RuleDecision(wanted=True)


def check_rule(
    rules: list[Rule],
    target_metadata: str,
    input_string: str,
) -> tuple[bool, str]:
    """Check if the input string matches any of the user defined rules."""

    for rule in rules:
        if target_metadata == rule.metadata and rule.regex.search(input_string or ""):
            return rule.wanted, rule.name

    return True, ""
