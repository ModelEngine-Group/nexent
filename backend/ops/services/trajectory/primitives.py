# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe query errors, bounded work and server-side opaque references."""

from __future__ import annotations

import hashlib
import json
import math
import re
from uuid import uuid4

from contracts.errors.trajectory import QueryError as QueryError
from infrastructure.trace.trajectory_budget import Budget as Budget
from infrastructure.trace.trajectory_budget import CURRENT_CANCEL as CURRENT_CANCEL
from infrastructure.trace.trajectory_budget import finite_number as finite_number

from .cache import ByteCache

class ReferenceStore:
    """Keep immutable reference state in an injected bounded server-side cache."""

    def __init__(self, *, max_bytes=16 * 1024 * 1024, ttl=1800, cache=None):
        self.cache = cache if cache is not None else ByteCache(max_bytes=max_bytes, ttl=ttl)

    def issue(self, kind, data):
        raw = json.dumps({"kind": kind, "data": data}, separators=(",", ":"), allow_nan=False)
        reference = uuid4().hex
        if not self.cache.put(reference, raw, len(raw.encode("utf-8")) * 4 + 256):
            raise QueryError("query_budget_exceeded", 503, retry_after=2)
        return reference

    def resolve(self, reference, kind, **bindings):
        if not isinstance(reference, str) or re.fullmatch(r"[0-9a-f]{32}", reference) is None:
            raise QueryError("invalid_reference")
        raw = self.cache.get(reference)
        if raw is None:
            raise QueryError("invalid_reference")
        entry = json.loads(raw)
        data = entry["data"]
        if entry["kind"] != kind or any(data.get(key) != value for key, value in bindings.items()):
            raise QueryError("invalid_reference")
        return data


def percentiles(values):
    values = sorted(values)

    def percentile(fraction):
        if not values:
            return None
        position = (len(values) - 1) * fraction
        lo, hi = math.floor(position), math.ceil(position)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)

    return {
        **{f"p{int(p * 100)}_ms": percentile(p) for p in (0.5, 0.9, 0.99)},
        "sample_count": len(values),
    }


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
