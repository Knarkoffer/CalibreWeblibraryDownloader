#!/usr/bin/env python3

import hashlib
import os
import unicodedata
from pathlib import PureWindowsPath

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"/\\|?*')
EXTRA_UNSAFE_FILENAME_CHARACTERS = frozenset("!'")
FILENAME_UNSAFE_CHARACTERS = (
    WINDOWS_RESERVED_CHARACTERS | EXTRA_UNSAFE_FILENAME_CHARACTERS
)
MAX_FILENAME_BYTES = 255
EMOJI_JOINER_AND_SELECTOR_CHARACTERS = frozenset(("\u200d", "\ufe0e", "\ufe0f"))
EMOJI_LIKE_UNICODE_CATEGORIES = frozenset(("Me", "Sk", "So"))


def generate_filehash(file_path: str) -> str:
    """Generates a MD5-hash of the file
    Args:
        file_path (str): Path to the file
    Returns:
        str: MD5-hash of the file
    """

    block_size = 65536
    hash_method = hashlib.md5()

    if os.path.isfile(file_path):
        with open(file_path, mode="rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                hash_method.update(block)

    return str(hash_method.hexdigest()).upper()


def fix_windows_filenames(
    candidate_filename: str,
    preserved_suffix: str = "",
    max_bytes: int = MAX_FILENAME_BYTES,
) -> str:
    """Fixes filenames that are not allowed in Windows.

    The final filename keeps UTF-8 printable characters, then removes
    filesystem-reserved and locally unsafe characters, plus Windows-only edge cases.

    Args:
        candidate_filename (str): The filename to be fixed
    Returns:
        str: The fixed filename
    """

    output_filename = enforce_utf8_printable(candidate_filename)

    for character in FILENAME_UNSAFE_CHARACTERS:
        output_filename = output_filename.replace(character, "")

    output_filename = collapse_chained_spaces(output_filename)
    output_filename = output_filename.rstrip(" .")
    if not output_filename:
        return "Untitled"

    path = PureWindowsPath(output_filename)
    if path.stem.upper() in WINDOWS_RESERVED_NAMES:
        output_filename = f"_{output_filename}"

    return truncate_filename_utf8_bytes(output_filename, preserved_suffix, max_bytes)


def collapse_chained_spaces(value: str) -> str:
    while "  " in value:
        value = value.replace("  ", " ")
    return value


def truncate_filename_utf8_bytes(
    filename: str,
    preserved_suffix: str = "",
    max_bytes: int = MAX_FILENAME_BYTES,
) -> str:
    """Trim a filename component to a UTF-8 byte limit."""

    if len(filename.encode("utf-8")) <= max_bytes:
        return filename

    suffix = preserved_suffix if filename.endswith(preserved_suffix) else ""
    if not suffix:
        suffix = PureWindowsPath(filename).suffix

    suffix_bytes = len(suffix.encode("utf-8"))
    if suffix and suffix_bytes < max_bytes:
        prefix = filename[: -len(suffix)]
        prefix = truncate_utf8_bytes(prefix, max_bytes - suffix_bytes).rstrip(" .")
        if prefix:
            return f"{prefix}{suffix}"

        fallback_prefix = "Untitled"
        if len(f"{fallback_prefix}{suffix}".encode()) <= max_bytes:
            return f"{fallback_prefix}{suffix}"

    return truncate_utf8_bytes(filename, max_bytes).rstrip(" .") or "Untitled"


def truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    """Trim text without splitting a UTF-8 character."""

    output_text = []
    used_bytes = 0
    for character in text:
        character_bytes = character.encode("utf-8")
        if used_bytes + len(character_bytes) > max_bytes:
            break
        output_text.append(character)
        used_bytes += len(character_bytes)

    return "".join(output_text)


def enforce_utf8_printable(candidate_text: str) -> str:
    """Keep only characters that are printable and UTF-8 encodable."""

    output_text = []
    for character in str(candidate_text):
        if not character.isprintable():
            continue
        try:
            character.encode("utf-8")
        except UnicodeEncodeError:
            continue
        if is_emoji_like_filename_character(character):
            continue
        output_text.append(character)
    return "".join(output_text)


def is_emoji_like_filename_character(character: str) -> bool:
    if character in EMOJI_JOINER_AND_SELECTOR_CHARACTERS:
        return True
    return unicodedata.category(character) in EMOJI_LIKE_UNICODE_CATEGORIES


def ascii_filename_segment(candidate_text: str, fallback: str = "unknown") -> str:
    """Return a conservative ASCII-only segment for temporary filenames."""

    output_text = "".join(
        character
        for character in str(candidate_text)
        if character.isascii()
        and character.isprintable()
        and character not in FILENAME_UNSAFE_CHARACTERS
    ).strip(" .")
    return output_text or fallback


def format_file_size(size_bytes: object) -> str:
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        return "unknown size"

    if size < 0:
        return "unknown size"

    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while size >= 1000 and unit_index < len(units) - 1:
        size /= 1000
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"

    formatted_size = f"{size:.1f}".removesuffix(".0")
    return f"{formatted_size} {units[unit_index]}"


def find_nth(haystack: str, needle: str, n: int) -> int:
    """
    Finds the nth position of a string in a string
    Args:
        haystack (str): The string to search in
        needle (str): The string to search for
        n (int): The nth position to search for
    Returns:
        int: The position of the nth occurrence of the string
    """

    parts = haystack.split(needle, n + 1)

    if len(parts) <= n + 1:
        return -1

    return len(haystack) - len(parts[-1]) - len(needle)


def filter_and_sort(list_to_sort: list, preferred_order: list) -> list:
    """
    Filters and sorts a list based on a preferred order.

    Only items in `list_to_sort` that also appear in `preferred_order` are included.
    The returned list preserves the order defined by `preferred_order`.

    Args:
        list_to_sort (list): The list of items to be filtered and sorted.
        preferred_order (list): The list defining the desired order of items.

    Returns:
        list: A filtered and sorted list containing only the items from `list_to_sort`
              that appear in `preferred_order`, ordered accordingly.

    Example:
        list_to_sort = ["kepub", "epub", "pdf", "mobi"]
        preferred_order = ["epub", "mobi"]
        result = filter_and_sort(list_to_sort, preferred_order)
        # result -> ["epub", "mobi"]
    """
    order_map = {val: i for i, val in enumerate(preferred_order)}
    return sorted(
        (x for x in list_to_sort if x in order_map), key=lambda x: order_map[x]
    )


def argument_to_list(input_data: str) -> list:
    """Convert a command-line argument into a list of server entries.

    If the input is a file, read one entry per line. Otherwise, split
    comma-separated input or return the single supplied entry.
    Args:
        input_data (str): Input source, either a file or a comma separated string
    Returns:
        list: The converted list
    """

    output_list = list()
    if os.path.isfile(input_data):
        with open(input_data, encoding="utf-8") as f:
            output_list = f.read().splitlines()
    else:
        if "," in input_data:
            output_list = input_data.split(",")
        else:
            output_list.append(input_data)

    # Trim all entries
    output_list = list(map(str.strip, output_list))

    # Removes empty entries
    output_list = list(filter(None, output_list))

    return output_list
