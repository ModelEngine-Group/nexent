# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Dependency-free defaults and normalization for span export exclusions."""

from collections.abc import Iterable


DEFAULT_EXCLUDED_ELASTICSEARCH_OPERATIONS = (
    "search",
    "indices.stats",
    "indices.get_settings",
    "indices.get_alias",
    "bulk",
    "indices.exists",
    "indices.delete",
)
DEFAULT_EXCLUDED_SPAN_NAMES = (
    "knowledge.process.submit",
    "knowledge.upload.batch",
)


def normalize_span_exclusions(values: str | Iterable[str]) -> list[str]:
    """Normalize exact names, preserving an explicit empty list and entry order."""
    entries = values.split(",") if isinstance(values, str) else values
    names = []
    for entry in entries:
        if not isinstance(entry, str):
            raise TypeError("Span exclusion entries must be strings")
        name = entry.strip()
        if name:
            names.append(name)
    return list(dict.fromkeys(names))
