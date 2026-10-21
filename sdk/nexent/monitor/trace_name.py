# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Propagate the main Agent's name without coupling it to child Agent metadata."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from weakref import ReferenceType, ref

TRACE_NAME_ATTRIBUTE = "langfuse.trace.name"
_agent_trace_name: ContextVar[tuple[int, str] | None] = ContextVar("_agent_trace_name", default=None)
_server_spans: ContextVar[tuple[ReferenceType[Any], ...]] = ContextVar("_nexent_server_spans", default=())


def _live_server_spans() -> tuple[Any, ...]:
    spans = tuple(reference() for reference in _server_spans.get())
    return tuple(span for span in spans if span is not None and span.is_recording())


def remember_server_span(span: Any) -> None:
    """Keep weak request-local ancestors across managed worker context copies."""
    _server_spans.set(tuple(ref(server) for server in (*_live_server_spans(), span)))


def forget_server_span(span_id: int) -> None:
    """Release a completed server span without retaining request objects."""
    _server_spans.set(tuple(
        ref(server) for server in _live_server_spans() if server.get_span_context().span_id != span_id
    ))


def inherited_trace_name(trace_id: int, parent: Any) -> str | None:
    """Prefer the main binding; allow named parents to cover request cleanup spans."""
    binding = _agent_trace_name.get()
    if binding is not None and binding[0] == trace_id:
        return binding[1]
    if parent is not None and parent.get_span_context().trace_id == trace_id:
        return (getattr(parent, "attributes", None) or {}).get(TRACE_NAME_ATTRIBUTE)
    return None


@contextmanager
def agent_trace_name_scope(span: Any, name: str, parent: Any) -> Iterator[None]:
    """Bind a name to this trace and update recording request ancestors only."""
    if span is None or not name or not span.is_recording():
        yield
        return
    inherited_name = (getattr(span, "attributes", None) or {}).get(TRACE_NAME_ATTRIBUTE)
    if isinstance(inherited_name, str) and inherited_name:
        name = inherited_name
    trace_id = span.get_span_context().trace_id
    token = _agent_trace_name.set((trace_id, name))
    try:
        ancestors = [parent, *_live_server_spans()]
        for ancestor in ancestors:
            if (
                ancestor is not None and ancestor.is_recording()
                and ancestor.get_span_context().trace_id == trace_id
            ):
                ancestor.set_attribute(TRACE_NAME_ATTRIBUTE, name)
        yield
    finally:
        _agent_trace_name.reset(token)
