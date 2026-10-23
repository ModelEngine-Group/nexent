"""Use a real local tracer and bounded workers without external exporters."""

import asyncio
from types import SimpleNamespace

import pytest
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.monitor import MonitoringConfig, get_monitoring_manager
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pytest_mock import MockerFixture


@pytest.fixture
def mocker(pytestconfig):
    """Override the root suite's minimal mocker with pytest-mock here."""
    fixture = MockerFixture(pytestconfig)
    yield fixture
    fixture.stopall()


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("nexent-test")
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=True))
    monkeypatch.setattr(manager, "_tracer", tracer)
    yield SimpleNamespace(manager=manager, tracer=tracer, exporter=exporter)
    provider.shutdown()


@pytest.fixture
def threads():
    manager = ThreadManager(
        "span-tests",
        {name: LanePolicy(name, 8, 8) for name in ("agent-run", "model-tool-io", "sandbox", "mcp-session")},
    )
    manager.start()
    yield manager
    asyncio.run(manager.shutdown(timeout=2))


def assert_child(child, parent):
    assert child.context.trace_id == parent.context.trace_id
    assert child.parent.span_id == parent.context.span_id


def by_name(spans):
    return {span.name: span for span in spans.exporter.get_finished_spans()}
