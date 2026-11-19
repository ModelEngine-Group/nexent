# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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


def parse_store_size(size_str) -> int:
    """Parse store_size string like '1.5 GB' or '500 MB' into bytes."""
    if size_str is None:
        return 0
    if isinstance(size_str, (int, float)):
        return int(size_str)
    if not isinstance(size_str, str) or not size_str.strip():
        return 0
    try:
        parts = size_str.strip().split()
        if len(parts) != 2:
            return 0
        value = float(parts[0])
        unit = parts[1].upper()
        if unit == "GB":
            return int(value * 1024 * 1024 * 1024)
        elif unit == "MB":
            return int(value * 1024 * 1024)
        elif unit == "KB":
            return int(value * 1024)
        elif unit == "B":
            return int(value)
        return 0
    except (ValueError, IndexError):
        return 0


def vector_bytes_for_display(size):
    """Preserve the original provider's two-decimal format and quota parsing."""
    return parse_store_size(vector_size_for_display(size))


def vector_size_for_display(size):
    """Preserve the original provider's public human-readable storage size."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f'{size:.2f} {unit}'
        size /= 1024
    return f'{size:.2f} PB'
