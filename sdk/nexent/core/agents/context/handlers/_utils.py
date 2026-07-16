"""Shared utilities for context item handlers."""

import hashlib
from typing import Any


def fingerprint(content: Any) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def token_estimate(content: Any) -> int:
    return len(str(content)) // 4
