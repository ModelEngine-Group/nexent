import re
from typing import List, Optional


def remove_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks including inner content."""
    if not text:
        return text
    return re.sub(r"(?:<think>)?.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)


def convert_list_to_string(items: Optional[List[int]]) -> str:
    """
    Convert list of integers to comma-separated string for database storage

    Args:
        items: List of integers or None

    Returns:
        Comma-separated string, empty string if None
    """
    if items is None:
        return ""
    return ",".join(str(item) for item in items)


def convert_string_to_list(items_str: Optional[str]) -> List[int]:
    """
    Convert comma-separated string to list of integers for processing

    Args:
        items_str: Comma-separated string or None

    Returns:
        List of integers, empty list if None or empty string
    """
    if not items_str or items_str.strip() == "":
        return []
    return [int(item.strip()) for item in items_str.split(",") if item.strip().isdigit()]
