# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe query errors, bounded work and authenticated opaque references."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass

from contracts.errors.trajectory import QueryError

CURRENT_CANCEL = ContextVar("trajectory_query_cancel", default=None)


@dataclass
class Budget:
    max_bytes: int = 256 * 1024 * 1024
    max_nodes: int = 100_000
    seconds: float = 8
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


class TokenSigner:
    def __init__(self, secret: str, *, clock=time.time, ttl=1800):
        if len(secret.encode()) < 32:
            raise ValueError("Trajectory signing key must contain at least 32 bytes")
        self.key, self.clock, self.ttl = secret.encode(), clock, ttl

    def sign(self, kind, data):
        raw = json.dumps(
            {"kind": kind, "exp": int(self.clock()) + self.ttl, **data},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
        signature = hmac.new(self.key, encoded, hashlib.sha256).digest()
        return (encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()

    def verify(self, token, kind, **bindings):
        try:
            if not isinstance(token, str) or len(token) > 8192:
                raise ValueError()
            encoded, signature = token.encode("ascii").split(b".")
            expected = base64.urlsafe_b64encode(hmac.new(self.key, encoded, hashlib.sha256).digest()).rstrip(b"=")
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)))
            if data["kind"] != kind or data["exp"] <= self.clock():
                raise ValueError()
            if any(data.get(key) != value for key, value in bindings.items()):
                raise ValueError()
            return data
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise QueryError("invalid_reference") from exc


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
