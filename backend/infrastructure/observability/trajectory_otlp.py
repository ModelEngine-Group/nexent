# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Encode real OpenTelemetry spans using the OTLP JSON mapping."""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping, Sequence

LOCAL_PREFIX = "nexent.local."


def any_value(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"doubleValue": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")}
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, bytes):
        return {"bytesValue": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {"kvlistValue": {"values": attributes(value)}}
    if isinstance(value, Sequence):
        return {"arrayValue": {"values": [any_value(item) for item in value]}}
    raise ValueError("Unsupported OTLP attribute value")


def attributes(values):
    return [{"key": key, "value": any_value(value)} for key, value in sorted(values.items()) if value is not None]


def span_request(span):
    """Retain actual IDs, events, links and dropped counts, never invent metrics."""
    values = dict(span.attributes or {})
    for key in list(values):
        if key.startswith(LOCAL_PREFIX):
            values[key.removeprefix(LOCAL_PREFIX)] = values.pop(key)
    context = span.context
    body = {
        "traceId": f"{context.trace_id:032x}",
        "spanId": f"{context.span_id:016x}",
        "traceState": context.trace_state.to_header(),
        "flags": int(context.trace_flags),
        "name": span.name,
        "kind": span.kind.value + 1,
        "startTimeUnixNano": str(span.start_time),
        "endTimeUnixNano": str(span.end_time),
        "attributes": attributes(values),
        "droppedAttributesCount": span.dropped_attributes,
        "status": {"code": span.status.status_code.value},
        "events": [
            {
                "timeUnixNano": str(event.timestamp),
                "name": event.name,
                "attributes": attributes(event.attributes or {}),
                "droppedAttributesCount": event.dropped_attributes,
            }
            for event in span.events
        ],
        "droppedEventsCount": span.dropped_events,
        "links": [
            {
                "traceId": f"{link.context.trace_id:032x}",
                "spanId": f"{link.context.span_id:016x}",
                "traceState": link.context.trace_state.to_header(),
                "flags": int(link.context.trace_flags),
                "attributes": attributes(link.attributes or {}),
                "droppedAttributesCount": link.dropped_attributes,
            }
            for link in span.links
        ],
        "droppedLinksCount": span.dropped_links,
    }
    if span.parent and span.parent.is_valid:
        body["parentSpanId"] = f"{span.parent.span_id:016x}"
    if span.status.description:
        body["status"]["message"] = span.status.description
    scope = span.instrumentation_scope
    resource = span.resource
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": attributes(resource.attributes)},
                "schemaUrl": resource.schema_url or "",
                "scopeSpans": [
                    {
                        "scope": {
                            "name": scope.name if scope else "nexent.monitor",
                            "version": (scope.version or "") if scope else "",
                            "attributes": attributes((scope.attributes or {}) if scope else {}),
                        },
                        "schemaUrl": (scope.schema_url or "") if scope else "",
                        "spans": [body],
                    }
                ],
            }
        ]
    }
