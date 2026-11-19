# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collect source facts for the executed portion of an Agent run."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from time import monotonic_ns

from .facts import emit_fact, get_fact_sink
from .monitoring import AgentRunMetadata, get_agent_monitoring_context


_OUTCOMES = {"completed": "succeeded", "failed": "failed", "stopped": "cancelled"}
_active_observation: ContextVar["AgentRunObservation | None"] = ContextVar("agent_fact_observation", default=None)


def record_agent_answer(content, *, agent_id=None, invocation_id=None):
    """Observe only the current execution's already classified public answer."""
    observation = _active_observation.get()
    if observation is None or not isinstance(content, str) or not content.strip():
        return
    metadata = get_agent_monitoring_context()
    identity = observation._identity
    if (metadata is None or metadata.monitoring_run_id != identity["agent_run_id"]
            or metadata.agent_id != identity["agent_id"] or metadata.tenant_id != identity["tenant_id"]):
        return
    if agent_id is not None and agent_id != identity["agent_id"]:
        return
    if invocation_id is not None and invocation_id != identity["agent_run_id"]:
        return
    with observation._lock:
        if observation._started_ns is not None and observation._ttft_ms is None:
            observation._ttft_ms = (monotonic_ns() - observation._started_ns) // 1_000_000


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
        self._lock = Lock()
        self._started_ns: int | None = None
        self._ttft_ms: int | None = None

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
        self._started_ns = started_ns
        token = _active_observation.set(self)
        try:
            yield
        finally:
            with self._lock:
                duration_ms = (monotonic_ns() - started_ns) // 1_000_000
                self._started_ns = None
            _active_observation.reset(token)
            ended_at = max(started_at, datetime.now(timezone.utc))
            self._terminal = {
                **started, "record_revision": 2, "ended_at": ended_at.isoformat(), "duration_ms": duration_ms,
            }
            if self._ttft_ms is not None:
                self._terminal["ttft_ms"] = self._ttft_ms

    def report_terminal(self, attempt_outcome: str | None) -> None:
        """Publish the measured execution with the worker's final outcome."""
        if self._terminal is not None:
            emit_fact({**self._terminal, "outcome": _OUTCOMES.get(attempt_outcome, "unknown")})
