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
