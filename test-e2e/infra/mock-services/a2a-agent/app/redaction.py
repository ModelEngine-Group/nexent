"""Redaction helpers for request evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-hw-appkey",
    "x-api-key",
}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def redact_headers(headers: Mapping[str, str]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for name, value in headers.items():
        if name.lower() in SENSITIVE_HEADERS:
            redacted[name] = {"present": bool(value), "sha256": _fingerprint(value)}
        else:
            redacted[name] = value
    return redacted

