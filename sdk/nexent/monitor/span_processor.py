# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Filter noisy infrastructure spans at the Nexent telemetry export boundary."""

from __future__ import annotations

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor


_EXCLUDED_ELASTICSEARCH_OPERATIONS = frozenset({
    "search",
    "indices.stats",
    "indices.get_settings",
    "indices.get_alias",
})


class MonitoringSpanProcessor(SpanProcessor):
    """Retain business spans while omitting noisy Elasticsearch operations."""

    def __init__(self, delegate: SpanProcessor):
        self._delegate = delegate

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._delegate.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        attributes = span.attributes or {}
        if (
            attributes.get("db.system") == "elasticsearch"
            and attributes.get("db.operation") in _EXCLUDED_ELASTICSEARCH_OPERATIONS
        ):
            return
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis=timeout_millis)
