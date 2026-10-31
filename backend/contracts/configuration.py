# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validation helpers for deployment configuration values."""

import math
from pathlib import Path


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


def parse_port(raw_value: object, name: str, default: int) -> int:
    """Parse a TCP port while keeping environment declarations assignment-only."""
    port = parse_positive_int(raw_value, name, default)
    if port > 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


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


def _parse_otlp_headers(headers_str: str) -> dict:
    """Parse OTLP headers string into dict. Format: 'key1=value1,key2=value2'"""
    if not headers_str:
        return {}
    headers = {}
    for pair in headers_str.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def _collect_version_candidates(version_file=None):
    """Build the ordered list of candidate paths to read ``APP_VERSION`` from.

    The order is: env override (test/script hook), the container image path,
    and finally the local repository root. Exposed as a separate function so
    tests can drive the resolver deterministically without monkey-patching
    ``pathlib.Path`` globally.
    """
    candidates = []
    override = version_file
    if override:
        candidates.append(Path(override))
    candidates.append(Path("/opt/nexent/VERSION"))
    # backend/contracts/configuration.py -> backend/contracts -> backend -> <repo-root>
    candidates.append(Path(__file__).resolve().parents[2] / "VERSION")
    return candidates


def _read_version_from(candidate):
    """Return the parsed version string from ``candidate`` or ``None``.

    Reads only the first non-blank line and strips surrounding whitespace.
    Returns ``None`` if the file is missing, unreadable, or its first line
    is empty after trimming.
    """
    try:
        if not candidate.is_file():
            return None
        first_line = candidate.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not first_line:
        return None
    version = first_line[0].strip()
    return version or None


def _resolve_app_version(default: str = "v2.2.1", *, version_file=None) -> str:
    """Read the semantic app version from the VERSION file.

    Search order:
      1. Explicit ``APP_VERSION_FILE`` environment override (test/script hook).
      2. Container path ``/opt/nexent/VERSION`` (set by the runtime Dockerfile).
      3. ``<repo-root>/VERSION`` for local development, where ``<repo-root>`` is
         derived from this file's location (backend/contracts -> repo root).
      4. Hardcoded default as a last resort.
    """
    for candidate in _collect_version_candidates(version_file):
        version = _read_version_from(candidate)
        if version is not None:
            return version
    return default


def _require_positive(value, message):
    """Keep the established environment validation and error message."""
    if value <= 0:
        raise ValueError(message)
    return value


def _build_otlp_headers(headers_str, authorization, x_api_key, langsmith_api_key, langsmith_project, langfuse_version):
    OTLP_HEADERS = _parse_otlp_headers(headers_str)
    if authorization:
        OTLP_HEADERS["Authorization"] = authorization
    if x_api_key:
        OTLP_HEADERS["x-api-key"] = x_api_key
    elif langsmith_api_key:
        OTLP_HEADERS["x-api-key"] = langsmith_api_key
    if langsmith_project:
        OTLP_HEADERS["Langsmith-Project"] = langsmith_project
    if langfuse_version:
        OTLP_HEADERS["x-langfuse-ingestion-version"] = langfuse_version


    return OTLP_HEADERS
