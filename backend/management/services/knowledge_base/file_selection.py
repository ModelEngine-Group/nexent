# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact object selections shared by ingestion and knowledge tools."""

from urllib.parse import unquote, urlsplit

from nexent.storage.errors import ScopeDenied


def parse_file_selections(paths):
    keys, qualified = [], {}
    for path in paths:
        if not isinstance(path, str) or not path or len(path) > 2048:
            raise ScopeDenied()
        if "://" not in path:
            keys.append(path)
            continue
        parsed = urlsplit(path)
        if (
            parsed.scheme != "s3"
            or not parsed.netloc
            or not parsed.path.startswith("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ScopeDenied()
        qualified.setdefault(parsed.netloc, []).append(unquote(parsed.path[1:]))
    return list(dict.fromkeys(keys)), qualified


def matches_file_selection(row, keys, qualified):
    candidates = (row.get("source_key"), row.get("object_name"))
    return any(key in keys for key in candidates) or any(
        key in qualified.get(row.get("bucket_name"), ()) for key in candidates
    )
