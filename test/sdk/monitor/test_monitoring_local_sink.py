# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exporter selection must retain the default remote monitoring contract."""

import json
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.monitor.monitoring import MonitoringConfig, MonitoringManager


def test_default_trace_sink_remains_otlp():
    assert MonitoringConfig().provider == "otlp"


@pytest.mark.parametrize("sink", ["local_file"])
def test_enabled_local_sink_requires_injected_processor(sink):
    with pytest.raises(ValueError, match="processor"):
        MonitoringConfig(enable_telemetry=True, provider=sink)


@pytest.mark.parametrize("provider", ["invalid", "both", "grafana", "zipkin"])
def test_unknown_or_removed_provider_fails_configuration(provider):
    with pytest.raises(ValueError, match="provider"):
        MonitoringConfig(provider=provider)


def test_metrics_only_configuration_does_not_require_local_trace_processor():
    config = MonitoringConfig(enable_telemetry=True, provider="local_file", export_traces=False)
    assert not config.export_metrics and not config.export_traces
    manager = MonitoringManager()
    with patch.object(manager, "_config", config):
        assert "nexent.local.input.value" not in manager._trace_payload_attributes("input", "value")


@pytest.mark.parametrize("sink,remote_calls", [("otlp", 1), ("local_file", 0), ("phoenix", 1), ("langfuse", 1), ("langsmith", 1)])
def test_local_trace_selection_and_independent_metrics(sink, remote_calls):
    processor = MagicMock()
    config = MonitoringConfig(
        enable_telemetry=True, provider=sink, local_span_processor=processor, export_metrics=True
    )
    manager = MonitoringManager()
    with (patch("sdk.nexent.monitor.monitoring.OTLPSpanExporterHTTP") as remote,
          patch("sdk.nexent.monitor.monitoring.OTLPMetricExporterHTTP") as metric):
        manager.configure(config)
    assert remote.call_count == remote_calls
    assert metric.call_count == remote_calls
    if sink == "local_file":
        manager._tracer_provider.add_span_processor.assert_any_call(processor)


def test_local_payload_copy_retains_full_body_with_original_remote_preview():
    manager = MonitoringManager()
    with patch.object(manager, "_config", MonitoringConfig(provider="local_file", trace_max_chars=3)):
        attrs = manager._trace_payload_attributes("input", "abcdef")
        assert attrs["nexent.local.input.value"] == "abcdef"
        assert manager._trace_payload_preview("abcdef") != "abcdef"


def test_local_content_excludes_credential_fields_and_arbitrary_objects():
    from sdk.nexent.monitor.local_content import safe_local_content

    result = json.loads(
        safe_local_content(
            {"messages": [{"content": "输入"}], "api_key": "secret", "nested": {"Authorization": "Bearer secret"}}
        )
    )
    assert result == {"messages": [{"content": "输入"}], "nested": {}}
    with pytest.raises(ValueError, match="DTO"):
        safe_local_content(object())


@pytest.mark.parametrize("value", [object(), {"value": float("nan")}])
def test_unserializable_local_content_marks_gap_and_preserves_business(value):
    manager = MonitoringManager()
    with patch.object(manager, "_config", MonitoringConfig(provider="local_file")):
        attrs = manager._trace_payload_attributes("output", value)
    assert attrs["nexent.trajectory.gap"] is True
    assert attrs["nexent.availability.output"] == "serialization_failed"
    assert "nexent.local.output.value" not in attrs
