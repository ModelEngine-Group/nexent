# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound trajectory reads by bytes, retained data, nodes and time."""

import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event

from contracts.errors.trajectory import QueryError

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
    cancel_event: Event | None = None

    def __post_init__(self):
        if self.cancel_event is None:
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
