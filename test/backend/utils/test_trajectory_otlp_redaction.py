# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Every local OTLP text field uses the same URL credential policy."""

import json

from google.protobuf.json_format import ParseDict
from infrastructure.observability.trajectory_otlp import span_request
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanContext, Status, StatusCode


def test_local_otlp_redacts_urls_in_previews_events_links_resource_scope_and_status():
    url = "https://storage.example/report?sig=synthetic-secret&version=7"
    resource = Resource({"resource.location": url}, schema_url=url)
    provider = TracerProvider(resource=resource, shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        tracer = provider.get_tracer("test", schema_url=url, attributes={"scope.location": url})
        link = Link(SpanContext(trace_id=1, span_id=2, is_remote=False), {"link.location": url})
        with tracer.start_as_current_span(url, links=[link]) as span:
            span.set_attributes({"input.preview": url, "output.value": url})
            span.add_event(url, {"event.location": url})
            span.set_status(Status(StatusCode.ERROR, url))
        exported = exporter.get_finished_spans()[0]
        result = span_request(exported)
        serialized = json.dumps(result)
        assert "synthetic-secret" not in serialized
        assert "REDACTED_CREDENTIAL" in serialized and "version=7" in serialized
        assert exported.name == url and exported.attributes["input.preview"] == url
        assert exported.events[0].attributes["event.location"] == url
        assert exported.status.description == url and resource.schema_url == url
        ParseDict(result, ExportTraceServiceRequest())
    finally:
        provider.shutdown()
