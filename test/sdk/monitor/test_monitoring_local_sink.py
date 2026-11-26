# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exporter selection must retain the default remote monitoring contract."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.monitor import monitoring
from sdk.nexent.monitor.monitoring import AgentRunMetadata, MonitoringConfig, MonitoringManager


def test_default_trace_sink_remains_otlp():
    assert MonitoringConfig().provider == "otlp"


@pytest.mark.parametrize("sink, capture_local_traces", [("local_file", False), ("otlp", True)])
def test_enabled_local_sink_requires_injected_processor(sink, capture_local_traces):
    with pytest.raises(ValueError, match="processor"):
        MonitoringConfig(enable_telemetry=True, provider=sink, capture_local_traces=capture_local_traces)


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


@pytest.mark.parametrize("remote_enabled", [False, True], ids=["local-only", "dual-capture"])
def test_local_capture_reuses_an_enabled_provider_and_registers_processor_once(monkeypatch, mocker, remote_enabled):
    monkeypatch.setattr(MonitoringManager, "_instance", None)
    manager = MonitoringManager()
    original_sampler = mocker.Mock()
    provider = SimpleNamespace(sampler=original_sampler, add_span_processor=mocker.Mock())
    provider_factory = mocker.patch.object(monitoring, "TracerProvider", return_value=provider)
    remote_exporter = mocker.patch.object(monitoring, "OTLPSpanExporterHTTP")
    local_sampler = mocker.Mock(get_description=mocker.Mock(return_value="local capture sampler"))
    processor = mocker.Mock(wrap_sampler=mocker.Mock(return_value=local_sampler))
    config = MonitoringConfig(enable_telemetry=remote_enabled, export_traces=remote_enabled, export_metrics=False)
    manager.configure(config)
    sampler = provider.sampler
    local_config = replace(config, enable_telemetry=True, capture_local_traces=True, local_span_processor=processor)

    manager.configure_local_capture(local_config)
    manager.configure_local_capture(replace(local_config))
    with pytest.raises(ValueError, match="different span processor"):
        manager.configure_local_capture(replace(local_config, local_span_processor=mocker.Mock()))

    assert manager.is_enabled
    provider_factory.assert_called_once()
    assert remote_exporter.call_count == int(remote_enabled)
    assert len(provider.add_span_processor.call_args_list) == 1 + int(remote_enabled)
    provider.add_span_processor.assert_called_with(processor)
    processor.wrap_sampler.assert_called_once_with(original_sampler)
    if remote_enabled:
        assert provider.sampler is sampler
    assert provider.sampler.get_description() == "local capture sampler"
    assert "nexent.local.input.value" in manager._trace_payload_attributes("input", "answer")


def test_remote_agent_metadata_omits_local_trajectory_identifiers():
    metadata = AgentRunMetadata(conversation_id=9, extra_metadata={
        "trajectory_id": "private-id",
        "trajectory_turn_no": 2,
        "trajectory_source_message_id": "10",
        "core_type": "jiuwen",
    })

    assert metadata.metadata() == {"conversation_id": 9, "core_type": "jiuwen"}


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
