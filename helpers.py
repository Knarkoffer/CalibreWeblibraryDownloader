#!/usr/bin/env python3

import hashlib
import os


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


def fix_windows_filenames(candidate_filename: str) -> str:
    """Fixes filenames that are not allowed in Windows
    Args:
        candidate_filename (str): The filename to be fixed
    Returns:
        str: The fixed filename
    """

    output_filename = candidate_filename

    unwanted_characters = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]

    for character in unwanted_characters:
        output_filename = output_filename.replace(character, "")

    return output_filename


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
