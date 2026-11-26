# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional SDK sink for sanitized MCP tool-call observations."""

import asyncio
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from time import monotonic
from uuid import uuid4

from opentelemetry.trace import get_current_span

from nexent.consts.mcp_errors import classify_mcp_failure
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor.facts import get_fact_sink
from nexent.monitor.monitoring import get_agent_monitoring_context


logger = logging.getLogger(__name__)
_suppressed = ContextVar("suppress_mcp_tool_calls", default=False)


class McpToolCallObservation:
    """One fact identity per MCP tool invocation, completed by a terminal revision.

    The observation is inert (``sink=None``) when suppressed, when the sink is
    unbound at construction, when the monitoring context is absent, for debug
    runs, or when the context carries no tenant; inertness costs one context
    read at most.
    """

    def __init__(self, tool_name, server=None):
        self.sink = None if _suppressed.get() else get_fact_sink()
        context = get_agent_monitoring_context() if self.sink is not None else None
        if context is None or context.is_debug or not context.tenant_id:
            self.sink = None
        invocation = uuid4().hex
        server = server or {}
        self.payload = {
            "tenant_id": context.tenant_id if context else None,
            "fact_kind": "mcp_tool",
            "fact_id": sha256(invocation.encode()).hexdigest(),
            "call_context_id": invocation,
            "agent_id": context.agent_id if context else None,
            "agent_run_id": context.monitoring_run_id if context else None,
            "root_run_id": context.monitoring_root_run_id if context else None,
            "initiator_group_ids": context.monitoring_group_ids if context else None,
            "mcp_server_id": server.get("mcp_server_id"),
            "mcp_server_name": server.get("mcp_server_name"),
            "mcp_server_type": server.get("mcp_server_type") or "unknown",
            "tool_name": tool_name,
        }
        self.started = None
        self.terminal = None
        self._finish_lock = Lock()

    def _emit(self, **fields):
        if self.sink is None:
            return
        try:
            self.sink({**self.payload, **fields})
        except Exception as error:
            logger.warning("MCP tool monitoring observation rejected error=%s", type(error).__name__)

    def dispatch(self):
        if self.started is not None or self.sink is None:
            return
        self._bind_current_span()
        self.started = monotonic()
        self.payload["started_at"] = datetime.now(timezone.utc).isoformat()
        self._emit(record_revision=1, outcome="started")

    def _bind_current_span(self):
        span = get_current_span()
        if span is None or not span.is_recording():
            return
        span_context = span.get_span_context()
        if span_context.is_valid:
            self.payload.update(trace_id=f"{span_context.trace_id:032x}", span_id=f"{span_context.span_id:016x}")

    def finish(self, error=None):
        with self._finish_lock:
            if self.started is None or self.terminal is not None:
                return
            self.terminal = self._measure_terminal(error)
        self._emit(record_revision=2, **self.terminal)

    def _measure_terminal(self, error):
        cancelled = isinstance(error, (RunTerminated, asyncio.CancelledError, GeneratorExit))
        outcome = "cancelled" if cancelled else "failed" if error is not None else "succeeded"
        now = max(datetime.now(timezone.utc), datetime.fromisoformat(self.payload["started_at"]))
        values = {}
        if error is not None and not cancelled:
            values["error_category"] = self._error_category(error)
        return {"outcome": outcome, "ended_at": now.isoformat(),
                "duration_ms": int((monotonic() - self.started) * 1000), **values}

    @staticmethod
    def _error_category(error):
        category, _leaf = classify_mcp_failure(error)
        if isinstance(category, str):
            category = category.upper()
        return category if isinstance(category, str) and re.fullmatch(r"[A-Z0-9_]{1,50}", category) \
            else "MCP_TOOL_FAILURE"


@contextmanager
def observe_mcp_tool_call(server, tool_name):
    """Record exactly one caller-observed MCP tool-call fact around the wrapped call."""
    observation = McpToolCallObservation(tool_name=tool_name, server=server)
    observation.dispatch()
    try:
        yield observation
    except BaseException as error:
        observation.finish(error)
        raise
    finally:
        observation.finish()


@contextmanager
def suppress_mcp_tool_calls():
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def resolve_mcp_server_identity(url, tool_name=None):
    """Resolve server identity for one URL from the live run's monitoring catalog.

    The backend builds the per-run catalog (design D-003); entries are plain
    dicts ``{url, mcp_server_id, mcp_server_name, mcp_server_type}`` with an
    optional ``tool_types`` override map for endpoints hosting several tool
    origins. Returns the identity subset, or ``None`` when the context is
    absent or the catalog does not carry the URL so facts fall back to the
    normalized ``unknown`` type. A per-tool override replaces only
    ``mcp_server_type`` (design section 3: local endpoint ``api_convert``).
    """
    context = get_agent_monitoring_context()
    if context is None or not url:
        return None
    catalog = getattr(context, "monitoring_mcp_servers", None) or []
    for entry in catalog:
        if isinstance(entry, dict) and entry.get("url") == url:
            identity = {key: entry[key] for key in
                        ("mcp_server_id", "mcp_server_name", "mcp_server_type") if key in entry}
            overrides = entry.get("tool_types") or {}
            if tool_name and isinstance(overrides, dict) and tool_name in overrides:
                identity["mcp_server_type"] = overrides[tool_name]
            return identity
    return None
