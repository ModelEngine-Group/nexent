# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional SDK sink for sanitized model-attempt observations."""

import asyncio
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor.facts import get_fact_sink
from nexent.monitor.monitoring import get_agent_monitoring_context


logger = logging.getLogger(__name__)
_suppressed = ContextVar("suppress_model_attempts", default=False)


class AttemptObservation:
    def __init__(self, request, profile, attempt):
        self.sink = get_fact_sink() if request.purpose == "agent" and not _suppressed.get() else None
        context = get_agent_monitoring_context() if self.sink is not None else None
        if context is not None and context.is_debug:
            self.sink = None
        self.payload = {
            "tenant_id": (context.tenant_id if context else None) or profile.identity.tenant_id,
            "fact_kind": "model",
            "fact_id": sha256(f"{request.request_id}:{attempt}".encode()).hexdigest(),
            "call_context_id": request.request_id,
            "model_id": profile.outlet_id,
            "model_type": profile.identity.model_type,
            "agent_id": context.agent_id if context else None,
            "agent_run_id": (context.monitoring_run_id if context else None) or request.run_id,
            "root_run_id": context.monitoring_root_run_id if context else None,
            "initiator_group_ids": context.monitoring_group_ids if context else None,
        }
        self.started = None
        self.first_content = None
        self.last_content = None
        self.completed = False
        self.usage = None
        self.terminal = None
        self._finish_lock = Lock()

    @classmethod
    def for_client(cls, tenant_id, model_id, model_type, *, trace_enabled=False):
        if (get_fact_sink() is None and not trace_enabled) or _suppressed.get():
            return None
        context = get_agent_monitoring_context()
        tenant_id = tenant_id or (context.tenant_id if context else None)
        if not tenant_id:
            return None
        request = SimpleNamespace(purpose="agent", request_id=uuid4().hex, run_id=None)
        profile = SimpleNamespace(outlet_id=model_id,
                                  identity=SimpleNamespace(tenant_id=tenant_id, model_type=model_type))
        return cls(request, profile, 1)

    def _emit(self, **fields):
        if self.sink is None:
            return
        try:
            self.sink({**self.payload, **fields})
        except Exception as error:
            logger.warning("Model monitoring observation rejected error=%s", type(error).__name__)

    def dispatch(self):
        if self.started is not None or (self.sink is None and "trace_id" not in self.payload):
            return
        self.started = monotonic()
        self.payload["started_at"] = datetime.now(timezone.utc).isoformat()
        self._emit(record_revision=1, outcome="started")

    def bind_trace(self, span_context):
        if self.started is None and span_context.is_valid:
            self.payload.update(trace_id=f"{span_context.trace_id:032x}", span_id=f"{span_context.span_id:016x}")

    def observe_usage(self, usage):
        if usage is not None and usage.origin == "provider":
            self.record_provider_counts({
                key: getattr(usage, key) for key in ("input_tokens", "output_tokens", "total_tokens")
            })

    def complete(self, usage):
        self.observe_usage(usage)
        self.completed = True

    def record_provider_counts(self, counts: dict | None):
        """Keep valid provider counts without applying legacy zero defaults."""
        observed = {field: value for field, value in (counts or {}).items()
                    if type(value) is int and 0 <= value < 2**63}
        if observed:
            self.usage = {**(self.usage or {}), **observed}

    def content(self):
        if self.started is None:
            return
        self.last_content = monotonic()
        if self.first_content is None:
            self.first_content = self.last_content

    @property
    def ttft_ms(self):
        if self.first_content is not None:
            return int((self.first_content - self.started) * 1000)

    def finish(self, error=None):
        with self._finish_lock:
            if self.started is None or self.terminal is not None:
                return
            self.terminal = self._measure_terminal(error)
        self._emit(record_revision=2, **self.terminal)

    def _measure_terminal(self, error):
        if isinstance(error, GeneratorExit) and self.completed:
            error = None
        cancelled = isinstance(error, (RunTerminated, asyncio.CancelledError, GeneratorExit))
        outcome = ("cancelled" if cancelled else "failed" if error is not None
                   else "succeeded" if self.completed else "unknown")
        now = max(datetime.now(timezone.utc), datetime.fromisoformat(self.payload["started_at"]))
        values = dict(self.usage or {})
        if self.first_content is not None:
            values["ttft_ms"] = self.ttft_ms
            generation_time = self.last_content - self.first_content
            if outcome == "succeeded" and generation_time > 0 and values.get("output_tokens") is not None:
                values["generation_rate"] = values["output_tokens"] / generation_time
        if error is not None and not cancelled:
            code = getattr(getattr(error, "error", error), "category", None)
            values["error_category"] = code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,50}", code) else "MODEL_FAILURE"
        return {"outcome": outcome, "ended_at": now.isoformat(),
                "duration_ms": int((monotonic() - self.started) * 1000), **values}


@contextmanager
def suppress_model_attempts():
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)
