"""Utilities for formatting byte quantities."""

from typing import Optional


def bytes_to_readable(size_bytes: Optional[int]) -> Optional[str]:
    """Convert a byte quantity to a human-readable string."""
    if size_bytes is None:
        return None
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"
