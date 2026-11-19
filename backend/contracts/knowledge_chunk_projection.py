# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Versioned public source fields remain separate from trusted execution identity."""

import json

PUBLIC_CHUNK_SOURCE_KEY = "nexent_public_chunk_v1"
PUBLIC_CHUNK_FIELDS = frozenset(
    {
        "id",
        "title",
        "filename",
        "path_or_url",
        "content",
        "create_time",
        "language",
        "author",
        "date",
    }
)


def _source_fields(location):
    if PUBLIC_CHUNK_SOURCE_KEY not in location:
        return None
    fields = location[PUBLIC_CHUNK_SOURCE_KEY]
    if not isinstance(fields, dict):
        raise TypeError("Public chunk source fields must be an object")
    return fields


def public_chunk_source(content, location):
    fields = _source_fields(location)
    return None if fields is None else {**fields, "content": content}


def public_chunk_value(location, name, default=None):
    fields = _source_fields(location)
    return default if fields is None else fields.get(name, default)


def _keyword_matches(value, requested):
    pending = [value]
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            if value == requested:
                return True
        elif (
            type(value) in {int, float, bool}
            and json.dumps(value, allow_nan=False) == requested
        ):
            return True
    return False


def public_id_matches(location, requested):
    return _keyword_matches(public_chunk_value(location, "id"), requested)


def public_path_matches(location, requested):
    fields = _source_fields(location)
    value = (
        fields.get("path_or_url")
        if isinstance(fields, dict)
        else location.get("path_or_url", "")
    )
    return _keyword_matches(value, requested)
