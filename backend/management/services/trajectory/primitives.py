# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe query errors, bounded work and server-side opaque references."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from contracts.errors.trajectory import QueryError

from .cache import ByteCache

CURRENT_CANCEL = ContextVar("trajectory_query_cancel", default=None)


@dataclass
class Budget:
    max_bytes: int = 256 * 1024 * 1024
    max_nodes: int = 100_000
    seconds: float = 30
    used_bytes: int = 0
    used_nodes: int = 0
    max_retained: int = 32 * 1024 * 1024
    retained: int = 0

    def __post_init__(self):
        self.cancel_event = CURRENT_CANCEL.get()
        self.deadline = time.monotonic() + self.seconds

    def check(self, *, size=0, nodes=0, retained=0):
        self.used_bytes += size
        self.used_nodes += nodes
        self.retained += retained
        if (
            (self.cancel_event is not None and self.cancel_event.is_set())
            or self.used_bytes > self.max_bytes
            or self.used_nodes > self.max_nodes
            or self.retained > self.max_retained
            or time.monotonic() > self.deadline
        ):
            raise QueryError("query_budget_exceeded", 503, retry_after=2)


class ReferenceStore:
    """Keep immutable reference state in a bounded process-local cache."""

    def __init__(self, *, max_bytes=16 * 1024 * 1024, ttl=1800):
        self.cache = ByteCache(max_bytes=max_bytes, ttl=ttl)

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


def finite_number(value, *, integer=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        if integer and isinstance(value, (int, str)) and re.fullmatch(r"[0-9]+", str(value)):
            return int(value)
        result = float(value)
        if not math.isfinite(result) or result < 0 or (integer and not result.is_integer()):
            return None
        return int(result) if integer else result
    except (ValueError, TypeError, OverflowError):
        return None


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
