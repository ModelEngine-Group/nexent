# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One execution clock, independent of monitoring and trajectory consumers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic_ns, time_ns


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _read_ns(clock: Callable[[], int]) -> int:
    value = clock()
    if type(value) is not int:
        raise TypeError("Nanosecond clock must return an integer")
    return value


def _unix_ns(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000


@dataclass(frozen=True)
class RunTimingResult:
    """Frozen values shared by every consumer of one completed execution."""

    run_id: str | None
    started_at: datetime
    ended_at: datetime
    duration_ms: int | None
    execution_started_at: datetime | None

    @property
    def started_at_ns(self) -> int:
        return _unix_ns(self.started_at)

    @property
    def ended_at_ns(self) -> int:
        return _unix_ns(self.ended_at)


class RunTiming:
    """Sample lifecycle boundaries once; owners decide when those boundaries occur."""

    def __init__(self, *, run_id: str | None = None, utc_clock_ns: Callable[[], int] | None = None,
                 monotonic_clock_ns: Callable[[], int] | None = None):
        self._lock = Lock()
        self._utc_clock_ns = time_ns if utc_clock_ns is None else utc_clock_ns
        self._monotonic_clock_ns = monotonic_ns if monotonic_clock_ns is None else monotonic_clock_ns
        self._run_id: str | None = None
        self._started_at: datetime | None = None
        self._started_tick = 0
        self._execution_started_at: datetime | None = None
        self._result: RunTimingResult | None = None
        if run_id is not None:
            self.bind_run_id(run_id)

    def _utc_now(self) -> datetime:
        return _EPOCH + timedelta(microseconds=_read_ns(self._utc_clock_ns) // 1000)

    def _require_started(self) -> datetime:
        if self._started_at is None:
            raise RuntimeError("Run timing has not started")
        return self._started_at

    @property
    def run_id(self) -> str | None:
        with self._lock:
            return self._run_id

    @property
    def started_at(self) -> datetime | None:
        with self._lock:
            return self._started_at

    @property
    def started_at_ns(self) -> int | None:
        with self._lock:
            return _unix_ns(self._started_at) if self._started_at is not None else None

    def bind_run_id(self, run_id: str) -> str:
        """Bind a trusted identity after preparation without replacing an existing identity."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Run ID must be a non-empty string")
        with self._lock:
            if self._run_id is not None and self._run_id != run_id:
                raise ValueError("Run timing identity cannot change")
            if self._result is not None and self._run_id is None:
                raise RuntimeError("Run timing has finished")
            self._run_id = run_id
            return run_id

    def start(self) -> datetime:
        """Return the original UTC start even when called again after completion."""
        with self._lock:
            if self._started_at is None:
                started_at = self._utc_now()
                started_tick = _read_ns(self._monotonic_clock_ns)
                self._started_at, self._started_tick = started_at, started_tick
            return self._started_at

    def mark_execution_started(self) -> datetime:
        """Keep the actual execution date separate from the complete lifecycle start."""
        with self._lock:
            self._require_started()
            if self._execution_started_at is None:
                if self._result is not None:
                    raise RuntimeError("Run timing has finished")
                self._execution_started_at = self._utc_now()
            return self._execution_started_at

    def finish(self) -> RunTimingResult:
        """Freeze once; later consumers reuse the same result without reading either clock."""
        with self._lock:
            if self._result is None:
                started_at = self._require_started()
                ended_at = max(started_at, self._utc_now())
                elapsed_ns = _read_ns(self._monotonic_clock_ns) - self._started_tick
                self._result = RunTimingResult(
                    run_id=self._run_id, started_at=started_at, ended_at=ended_at,
                    duration_ms=elapsed_ns // 1_000_000 if elapsed_ns >= 0 else None,
                    execution_started_at=self._execution_started_at,
                )
            return self._result
