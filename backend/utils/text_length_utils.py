"""Shared helpers for limits expressed in Chinese or ASCII display width."""

import unicodedata


def get_display_width(value: str) -> int:
    """Return a display width where CJK and full-width characters use two units."""
    return sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in value)


def truncate_to_display_width(value: str, max_width: int, suffix: str = "") -> str:
    """Truncate text without splitting characters and keep the optional suffix within the limit."""
    if get_display_width(value) <= max_width:
        return value

    suffix_width = get_display_width(suffix)
    prefix_width_limit = max(max_width - suffix_width, 0)
    current_width = 0
    kept_chars: list[str] = []

    for char in value:
        char_width = get_display_width(char)
        if current_width + char_width > prefix_width_limit:
            break
        kept_chars.append(char)
        current_width += char_width

    return "".join(kept_chars) + suffix
