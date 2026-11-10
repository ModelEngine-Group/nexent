# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Apply trace naming and noise filters at the Nexent telemetry export boundary."""

from __future__ import annotations

from collections.abc import Iterable

from opentelemetry import trace
from opentelemetry.attributes import BoundedAttributes
from opentelemetry.context import Context
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import Link, SpanKind

from .span_filter_config import (
    DEFAULT_EXCLUDED_ELASTICSEARCH_OPERATIONS,
    DEFAULT_EXCLUDED_SPAN_NAMES,
    normalize_span_exclusions,
)
from .trace_name import (
    TRACE_NAME_ATTRIBUTE,
    forget_server_span,
    inherited_trace_name,
    remember_server_span,
)


class MonitoringSpanProcessor(SpanProcessor):
    """Propagate main Agent names and omit noisy operations before export."""

    def __init__(
        self,
        delegate: SpanProcessor,
        excluded_elasticsearch_operations: str | Iterable[str] = DEFAULT_EXCLUDED_ELASTICSEARCH_OPERATIONS,
        excluded_span_names: str | Iterable[str] = DEFAULT_EXCLUDED_SPAN_NAMES,
    ):
        self._delegate = delegate
        self._excluded_elasticsearch_operations = frozenset(
            normalize_span_exclusions(excluded_elasticsearch_operations)
        )
        self._excluded_span_names = frozenset(normalize_span_exclusions(excluded_span_names))

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        if span.kind == SpanKind.SERVER:
            remember_server_span(span)
        name = inherited_trace_name(span.get_span_context().trace_id, trace.get_current_span(parent_context))
        if name:
            span.set_attribute(TRACE_NAME_ATTRIBUTE, name)
        self._delegate.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if span.kind == SpanKind.SERVER:
            forget_server_span(span.context.span_id)
        if span.name in self._excluded_span_names:
            return
        attributes = span.attributes or {}
        if (
            attributes.get("db.system") == "elasticsearch"
            and attributes.get("db.operation") in self._excluded_elasticsearch_operations
        ):
            return

        def private(key):
            return key.startswith("nexent.local.")

        def public_attributes(values, dropped):
            public = BoundedAttributes(
                attributes={key: value for key, value in (values or {}).items() if not private(key)}
            )
            public.dropped = dropped
            return public

        if (
            any(private(key) for key in attributes)
            or any(private(key) for event in span.events for key in (event.attributes or {}))
            or any(private(key) for link in span.links for key in (link.attributes or {}))
        ):
            events = BoundedList.from_seq(
                None,
                [
                    Event(
                        event.name,
                        attributes=public_attributes(event.attributes, event.dropped_attributes),
                        timestamp=event.timestamp,
                    )
                    for event in span.events
                ],
            )
            events.dropped = span.dropped_events
            links = BoundedList.from_seq(
                None,
                [
                    Link(
                        link.context,
                        attributes=public_attributes(link.attributes, link.dropped_attributes),
                    )
                    for link in span.links
                ],
            )
            links.dropped = span.dropped_links
            span = ReadableSpan(
                name=span.name,
                context=span.context,
                parent=span.parent,
                resource=span.resource,
                attributes=public_attributes(attributes, span.dropped_attributes),
                events=events,
                links=links,
                kind=span.kind,
                status=span.status,
                start_time=span.start_time,
                end_time=span.end_time,
                instrumentation_scope=span.instrumentation_scope,
            )
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis=timeout_millis)
