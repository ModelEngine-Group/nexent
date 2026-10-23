# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Configurable exclusions at the real telemetry export boundary."""

import builtins
import importlib.util
import sys
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexent.monitor import monitoring
from nexent.monitor.span_processor import MonitoringSpanProcessor


DEFAULT_OPERATIONS = [
    "search", "indices.stats", "indices.get_settings", "indices.get_alias",
    "bulk", "indices.exists", "indices.delete",
]
DEFAULT_NAMES = ["knowledge.process.submit", "knowledge.upload.batch"]


def test_defaults_are_independent_and_sdk_ignores_environment(monkeypatch):
    monkeypatch.setenv("MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS", "indices.refresh")
    monkeypatch.setenv("MONITORING_EXCLUDED_SPAN_NAMES", "custom.step")
    first = monitoring.MonitoringConfig()
    second = monitoring.MonitoringConfig()
    assert first.excluded_elasticsearch_operations == second.excluded_elasticsearch_operations == DEFAULT_OPERATIONS
    assert first.excluded_span_names == second.excluded_span_names == DEFAULT_NAMES
    first.excluded_elasticsearch_operations.clear()
    first.excluded_span_names.append("custom.step")
    assert second.excluded_elasticsearch_operations == DEFAULT_OPERATIONS
    assert second.excluded_span_names == DEFAULT_NAMES


@pytest.mark.parametrize("field", ["excluded_elasticsearch_operations", "excluded_span_names"])
@pytest.mark.parametrize("value,expected", [
    (" search , ,search, indices.refresh, ", ["search", "indices.refresh"]),
    ([" search ", "", "search", "indices.refresh"], ["search", "indices.refresh"]),
    ("", []),
    (" , , ", []),
    ([], []),
])
def test_config_normalizes_explicit_lists(field, value, expected):
    config = monitoring.MonitoringConfig(**{field: value})
    assert getattr(config, field) == expected


@pytest.mark.parametrize("field", ["excluded_elasticsearch_operations", "excluded_span_names"])
@pytest.mark.parametrize("value", [None, 42, ["search", None], ["search", 42]])
def test_invalid_sdk_list_types_fail_configuration(field, value):
    with pytest.raises(TypeError):
        monitoring.MonitoringConfig(**{field: value})


def test_config_remains_available_without_optional_opentelemetry(monkeypatch):
    original_import = builtins.__import__

    def without_opentelemetry(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("OpenTelemetry is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_opentelemetry)
    spec = importlib.util.spec_from_file_location("nexent.monitor._without_otel", monitoring.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    config = module.MonitoringConfig(enable_telemetry=True, excluded_span_names=" custom.step,custom.step ")
    assert module.OPENTELEMETRY_AVAILABLE is False
    assert config.enable_telemetry is False
    assert config.excluded_span_names == ["custom.step"]
    assert config.excluded_elasticsearch_operations == DEFAULT_OPERATIONS


@pytest.fixture
def export_manager(mocker):
    exporter = InMemorySpanExporter()
    mocker.patch.object(monitoring, "OTLPSpanExporterHTTP", return_value=exporter)
    mocker.patch.object(monitoring.trace, "set_tracer_provider")
    mocker.patch.object(monitoring.metrics, "set_meter_provider")
    manager = object.__new__(monitoring.MonitoringManager)
    manager.__init__()
    yield SimpleNamespace(manager=manager, exporter=exporter)
    if manager._tracer_provider is not None:
        manager._tracer_provider.shutdown()
    if manager._meter_provider is not None:
        manager._meter_provider.shutdown()


@pytest.mark.parametrize("overrides,omitted", [
    ({}, {"search", "knowledge.upload.batch"}),
    ({"excluded_elasticsearch_operations": " indices.refresh,indices.refresh ,",
      "excluded_span_names": " custom.step , custom.step,"}, {"indices.refresh", "custom.step"}),
    ({"excluded_elasticsearch_operations": "", "excluded_span_names": ""}, set()),
    ({"excluded_elasticsearch_operations": ""}, {"knowledge.upload.batch"}),
    ({"excluded_span_names": []}, {"search"}),
    ({"excluded_elasticsearch_operations": "indices.*", "excluded_span_names": "custom.*"}, set()),
])
@pytest.mark.parametrize("fails", [False, True])
def test_manager_applies_replacement_empty_and_default_lists(export_manager, overrides, omitted, fails):
    export_manager.manager.configure(monitoring.MonitoringConfig(
        enable_telemetry=True, export_metrics=False, **overrides,
    ))
    provider = export_manager.manager._tracer_provider
    tracer = provider.get_tracer("exclusions-test")
    operations = {
        "search": {"db.system": "elasticsearch", "db.operation": "search"},
        "indices.refresh": {"db.system": "elasticsearch", "db.operation": "indices.refresh"},
        "postgres.refresh": {"db.system": "postgresql", "db.operation": "indices.refresh"},
        "unattributed.refresh": {"db.operation": "indices.refresh"},
        "tool.search": {},
        "knowledge.upload.batch": {},
        "custom.step": {},
        "custom.step.extra": {},
        "CUSTOM.STEP": {},
    }
    with tracer.start_as_current_span("agent.run"):
        for name, attributes in operations.items():
            if fails:
                with pytest.raises(RuntimeError, match="operation failed"):
                    with tracer.start_as_current_span(name, attributes=attributes):
                        raise RuntimeError("operation failed")
            else:
                with tracer.start_as_current_span(name, attributes=attributes):
                    pass
    assert provider.force_flush(timeout_millis=1000)
    spans = {span.name: span for span in export_manager.exporter.get_finished_spans()}
    assert set(spans) == {"agent.run"} | (operations.keys() - omitted)
    for name in operations.keys() - omitted:
        assert spans[name].parent.span_id == spans["agent.run"].context.span_id


def test_processors_snapshot_lists_without_cross_instance_changes():
    names = ["custom.step"]
    exporters = [InMemorySpanExporter(), InMemorySpanExporter()]
    providers = [TracerProvider(), TracerProvider()]
    providers[0].add_span_processor(MonitoringSpanProcessor(
        SimpleSpanProcessor(exporters[0]), excluded_elasticsearch_operations=[], excluded_span_names=names,
    ))
    providers[1].add_span_processor(MonitoringSpanProcessor(
        SimpleSpanProcessor(exporters[1]), excluded_elasticsearch_operations=[], excluded_span_names=[],
    ))
    names.clear()
    try:
        for provider in providers:
            with provider.get_tracer("isolation-test").start_as_current_span("custom.step"):
                pass
        assert exporters[0].get_finished_spans() == ()
        assert [span.name for span in exporters[1].get_finished_spans()] == ["custom.step"]
    finally:
        for provider in providers:
            provider.shutdown()
