# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep public source merging and document-key conversion at the Management boundary."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from nexent.storage.errors import InvalidInput


def build_chunk_payload(base_fields, metadata, ensure_create_time=True):
    payload = {key: value for key, value in (base_fields or {}).items() if value is not None}
    payload.update({key: value for key, value in (metadata or {}).items() if value is not None})
    if ensure_create_time and "create_time" not in payload:
        payload["create_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def merge_chunk_source(source, patch):
    result = deepcopy(source)
    for name, value in patch.items():
        result[name] = (merge_chunk_source(result[name], value)
                        if isinstance(result.get(name), dict) and isinstance(value, dict)
                        else deepcopy(value))
    return result


def public_chunk_key(value):
    def escape(item):
        if isinstance(item, list):
            return ",".join(escape(part) for part in item)
        if isinstance(item, dict):
            raise InvalidInput()
        return str(item).lower() if isinstance(item, bool) else str(item)

    key = uuid4().hex if value is None or value == "" or value == [] else escape(value)
    if not key or len(key.encode("utf-8")) > 512:
        raise InvalidInput()
    return key
