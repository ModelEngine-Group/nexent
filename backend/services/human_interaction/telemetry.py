"""Carry only W3C trace identity across the durable run boundary."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from opentelemetry import context as otel_context
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )
except ImportError:  # pragma: no cover - optional monitoring dependency
    otel_context = None
    _propagator = None
else:
    _propagator = TraceContextTextMapPropagator()


def capture_trace_context() -> dict[str, str]:
    """Serialize the current parent without persisting baggage or credentials."""
    carrier: dict[str, str] = {}
    if _propagator is not None:
        try:
            _propagator.inject(carrier)
        except Exception:
            logger.debug("Unable to capture HITL trace context", exc_info=True)
    return carrier


@contextmanager
def restore_trace_context(carrier: object) -> Iterator[None]:
    """Isolate an attempt from scheduler context, including for legacy runs."""
    if otel_context is None or _propagator is None:
        yield
        return

    parent = otel_context.Context()
    if isinstance(carrier, dict):
        headers = {
            key: value for key, value in carrier.items()
            if key in {"traceparent", "tracestate"} and isinstance(value, str)
        }
        try:
            parent = _propagator.extract(headers, context=parent)
        except Exception:
            logger.debug("Unable to restore HITL trace context", exc_info=True)
    token = otel_context.attach(parent)
    try:
        yield
    finally:
        otel_context.detach(token)
