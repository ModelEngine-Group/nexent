# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collect source facts for the executed portion of an Agent run."""

from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic_ns

from .facts import emit_fact, get_fact_sink
from .monitoring import AgentRunMetadata


_OUTCOMES = {"completed": "succeeded", "failed": "failed", "stopped": "cancelled"}


class AgentRunObservation:
    def __init__(self, metadata: AgentRunMetadata, run_id: str):
        self._identity = {
            "tenant_id": metadata.tenant_id,
            "fact_kind": "agent",
            "fact_id": run_id,
            "call_context_id": run_id,
            "agent_run_id": run_id,
            "root_run_id": metadata.monitoring_root_run_id,
            "agent_id": metadata.agent_id,
            "agent_version_no": metadata.agent_version_no,
            "is_root": run_id == metadata.monitoring_root_run_id,
            "initiator_group_ids": metadata.monitoring_group_ids,
        }
        if not self._identity["is_root"]:
            self._identity["parent_run_id"] = metadata.monitoring_parent_run_id
        self._terminal: dict | None = None

    @classmethod
    def from_context(cls, metadata: AgentRunMetadata | None):
        """Require trusted execution ancestry independently of trajectory capture."""
        if get_fact_sink() is None or metadata is None or metadata.is_debug:
            return None
        run_id = metadata.monitoring_run_id
        root_id = metadata.monitoring_root_run_id
        parent_id = metadata.monitoring_parent_run_id
        if not run_id or not root_id:
            return None
        if run_id == root_id and parent_id is not None:
            return None
        if run_id != root_id and parent_id in {None, run_id}:
            return None
        if not metadata.tenant_id or metadata.agent_id is None:
            return None
        return cls(metadata, run_id)

    @contextmanager
    def measure(self, stop_event):
        """Time the adapter's run call, retaining terminal fields for later reporting."""
        if stop_event.is_set():
            yield
            return
        started_at = datetime.now(timezone.utc)
        started = {**self._identity, "started_at": started_at.isoformat()}
        emit_fact({**started, "record_revision": 1, "outcome": "started"})
        started_ns = monotonic_ns()
        try:
            yield
        finally:
            duration_ms = (monotonic_ns() - started_ns) // 1_000_000
            ended_at = max(started_at, datetime.now(timezone.utc))
            self._terminal = {
                **started, "record_revision": 2, "ended_at": ended_at.isoformat(), "duration_ms": duration_ms,
            }

    def report_terminal(self, attempt_outcome: str | None) -> None:
        """Publish the measured execution with the worker's final outcome."""
        if self._terminal is not None:
            emit_fact({**self._terminal, "outcome": _OUTCOMES.get(attempt_outcome, "unknown")})
