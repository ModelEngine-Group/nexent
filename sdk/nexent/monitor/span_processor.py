# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Filter noisy infrastructure spans at the Nexent telemetry export boundary."""

from __future__ import annotations

from collections.abc import Iterable

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from .span_filter_config import (
    DEFAULT_EXCLUDED_ELASTICSEARCH_OPERATIONS,
    DEFAULT_EXCLUDED_SPAN_NAMES,
    normalize_span_exclusions,
)


class MonitoringSpanProcessor(SpanProcessor):
    """Omit selected noisy operations before queuing spans for export."""

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
        self._delegate.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if span.name in self._excluded_span_names:
            return
        attributes = span.attributes or {}
        if (
            attributes.get("db.system") == "elasticsearch"
            and attributes.get("db.operation") in self._excluded_elasticsearch_operations
        ):
            return
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis=timeout_millis)
