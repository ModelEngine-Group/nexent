"""Validation helpers for deployment configuration values."""

import math


def parse_positive_int(raw_value: object, name: str, default: int) -> int:
    """Parse a positive integer, falling back to ``default`` when unset."""
    value = default if raw_value is None else raw_value
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def parse_positive_float(raw_value: object, name: str, default: float) -> float:
    """Parse a finite positive float, falling back to ``default`` when unset."""
    value = default if raw_value is None else raw_value
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed
