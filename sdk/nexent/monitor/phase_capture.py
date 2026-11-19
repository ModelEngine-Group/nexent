# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Capture local lifecycle phases before and during the authorized Agent worker."""

from __future__ import annotations

import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps


try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:
    trace = None

from .duration import duration_attributes
from .local_content import local_capture_enabled, safe_local_content
from .preparation_groups import group_memory_preparation
from .run_timing import RunTiming


_MAX_PREPARATION_PHASES = 4096
_preparation = ContextVar("nexent_preparation_phases", default=None)
_parent = ContextVar("nexent_preparation_parent", default=None)
_preparing_run = ContextVar("nexent_preparing_run", default=False)


def _manager():
    from . import get_monitoring_manager

    return get_monitoring_manager()


def _status(span, status):
    try:
        span.set_status(status)
    except Exception:
        _gap(span)


def _gap(span):
    try:
        span.set_attribute("nexent.trajectory.gap", True)
    except Exception:
        pass


class Phase:
    """Write safe DTO attributes without changing the operation's result."""

    def __init__(self, attributes=None, span=None):
        self.attributes = attributes
        self.span = span

    def set_attribute(self, key, value):
        try:
            if self.attributes is not None:
                self.attributes[key] = value
            if self.span is not None:
                self.span.set_attribute(key, value)
        except Exception:
            _gap(self.span or trace.get_current_span())

    def _body(self, field, value):
        if self.attributes is None and self.span is None:
            return
        try:
            self.set_attribute(f"{field}.value", safe_local_content(value))
        except Exception:
            self.set_attribute(f"nexent.availability.{field}", "serialization_failed")
            self.set_attribute("nexent.trajectory.gap", True)

    def set_output(self, value):
        self._body("output", value)


@contextmanager
def trace_phase(name, *, input_value=None, attributes=None):
    """Buffer preparation facts, or trace live work under its current invocation."""
    manager = _manager()
    if trace is None or not local_capture_enabled(manager):
        yield Phase()
        return
    values = {
        "nexent.local_only": True,
        "nexent.node.kind": "phase",
        "openinference.span.kind": "CHAIN",
        **(attributes or {}),
    }
    started_ns, started = time.time_ns(), time.perf_counter()
    records = _preparation.get()
    span, record, token = None, None, None
    try:
        if records is not None and len(records) >= _MAX_PREPARATION_PHASES:
            records[0]["attributes"]["nexent.trajectory.gap"] = True
        elif records is not None:
            record = {
                "name": name,
                "parent": _parent.get(),
                "started_at_ns": started_ns,
                "started_monotonic": started,
                "attributes": values,
                "status": "success",
            }
            records.append(record)
            token = _parent.set(len(records) - 1)
        else:
            span = manager.tracer.start_span(name, attributes=values, start_time=started_ns)
    except Exception:
        _gap(trace.get_current_span())
    phase = Phase(values if record is not None else None, span)
    if input_value is not None:
        phase._body("input", input_value)
    try:
        with trace.use_span(span, record_exception=False, set_status_on_exception=False) if span else nullcontext():
            try:
                yield phase
            except BaseException as error:
                status = "cancelled" if type(error).__name__ in {"CancelledError", "GeneratorExit"} else "failed"
                phase.set_attribute("nexent.business_status", status)
                phase.set_attribute("error.type", type(error).__name__)
                if record is not None:
                    record["status"] = "error"
                if span is not None:
                    _status(span, Status(StatusCode.ERROR, type(error).__name__))
                raise
            else:
                if span is not None:
                    _status(span, Status(StatusCode.OK))
    finally:
        finished_ns = time.time_ns()
        for key, value in duration_attributes(started, time.perf_counter()).items():
            phase.set_attribute(key, value)
        if record is not None:
            record["finished_at_ns"] = max(started_ns, finished_ns)
        if token is not None:
            _parent.reset(token)
        if span is not None:
            try:
                span.end(end_time=max(started_ns, finished_ns))
            except Exception:
                _gap(trace.get_current_span())


def capture_preparation(function):
    """Keep each async run-info preparation isolated, including nested worker contexts."""

    @wraps(function)
    async def captured(*args, **kwargs):
        if _preparing_run.get():
            return await function(*args, **kwargs)
        timing = RunTiming()
        timing.start()
        preparing_token = _preparing_run.set(True)
        records = []
        capture = trace is not None and local_capture_enabled(_manager())
        token = _preparation.set(records if capture else None)
        parent_token = _parent.set(None)
        try:
            with trace_phase("agent.prepare"):
                result = await function(*args, **kwargs)
            result.run_timing = timing
            try:
                if capture:
                    result.preparation_trace = records
            except Exception:
                _gap(trace.get_current_span())
            return result
        except BaseException:
            timing.finish()
            raise
        finally:
            _parent.reset(parent_token)
            _preparation.reset(token)
            _preparing_run.reset(preparing_token)

    return captured


def preparation_start(info):
    records = getattr(info, "preparation_trace", None)
    if trace is not None and local_capture_enabled(_manager()) and isinstance(records, list) and records:
        return min(record["started_at_ns"] for record in records)
    return None


def emit_preparation(info):
    """Export immutable facts once, after the worker has its trusted execution identity."""
    manager = _manager()
    records = getattr(info, "preparation_trace", None)
    if trace is None or not local_capture_enabled(manager) or not isinstance(records, list) or not records:
        return
    info.preparation_trace = []
    root, emitted = trace.get_current_span(), {}
    try:
        records = group_memory_preparation(records)
    except Exception:
        _gap(root)
    try:
        for index, record in enumerate(records):
            parent = emitted.get(record["parent"], root)
            span = manager.tracer.start_span(
                record["name"],
                context=trace.set_span_in_context(parent),
                attributes=record["attributes"],
                start_time=record["started_at_ns"],
            )
            _status(span, Status(StatusCode.ERROR if record["status"] == "error" else StatusCode.OK))
            emitted[index] = span
        # End children first, retaining complete ancestry at the processor boundary.
        for index in reversed(range(len(records))):
            emitted[index].end(end_time=records[index]["finished_at_ns"])
    except Exception:
        _gap(root)
        for span in emitted.values():
            try:
                if span.is_recording():
                    span.end()
            except Exception:
                pass
