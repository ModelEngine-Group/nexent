"""Compatibility seam for optional in-process thread lifecycle observers.

The default implementation intentionally has no external telemetry side effects.
Thread diagnostics remain available through ThreadManager snapshots and metrics.
"""

from __future__ import annotations

from typing import Any


class NoOpThreadTelemetry:
    """Preserve the manager observer contract without exporting state changes."""

    def record_snapshot(
        self,
        service_name: str,
        event: str,
        execution: Any,
        counts: tuple[int, int, int, int],
        *,
        dedicated: bool,
        **fields: Any,
    ) -> None:
        return None


_thread_telemetry = NoOpThreadTelemetry()


def get_thread_telemetry() -> NoOpThreadTelemetry:
    return _thread_telemetry
