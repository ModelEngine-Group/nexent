# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run snapshots contain authorized execution values, never connection secrets."""

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, ModelConfig
from nexent.monitor.run_capture import capture_run_input, capture_run_result


def manager(sink="local_file"):
    return SimpleNamespace(
        is_enabled=True, _config=SimpleNamespace(export_traces=True, provider=sink)
    )


def test_root_input_captures_authorized_context_and_detaches_configuration():
    span = Mock()
    agent = AgentConfig(
        name="root",
        description="desc",
        tools=[],
        model_name="model",
        max_steps=3,
        prompt_templates={"system": "完整提示词"},
        agent_id=7,
        version_no=0,
    )
    model = ModelConfig(
        cite_name="model",
        model_name="provider-model",
        api_key="credential",
        url="https://provider.invalid?credential=private",
    )
    capture_run_input(
        manager(),
        span,
        query="question",
        agent_config=agent,
        model_configs=[model],
        history=[{"role": "user", "content": "authorized history"}],
        context_items=[],
        attachments=[],
    )
    values = span.set_attributes.call_args.args[0]
    body = json.loads(values["nexent.local.input.value"])
    assert body["effective_config"]["agent_config"]["max_steps"] == 3
    assert body["effective_config"]["agent_config"]["version_no"] == 0
    assert body["context"]["history"][0]["content"] == "authorized history"
    assert "完整提示词" in values["nexent.local.input.value"]
    assert "credential" not in values["nexent.local.input.value"]
    assert "provider.invalid" not in values["nexent.local.input.value"]
    agent.max_steps = 9
    assert body["effective_config"]["agent_config"]["max_steps"] == 3
    assert len(values["nexent.config_fingerprint"]) == 64


def test_capture_serialization_failure_marks_gap_and_remote_default_is_noop():
    span = Mock()
    capture_run_input(
        manager("otlp"), span, query=object(), agent_config=None, model_configs=[]
    )
    span.set_attributes.assert_not_called()
    capture_run_input(
        manager(), span, query=object(), agent_config=None, model_configs=[]
    )
    assert span.set_attributes.call_args.args[0]["nexent.trajectory.gap"] is True


def test_cancelled_run_has_a_distinct_business_outcome():
    span = Mock()
    capture_run_result(manager(), span, outcome="stopped")
    assert span.set_attributes.call_args.args[0]["nexent.cancelled"] is True
    assert (
        span.set_attributes.call_args.args[0]["nexent.business_status"] == "cancelled"
    )


def test_context_snapshot_keeps_before_after_content_and_estimate_origin():
    from nexent.monitor.run_capture import capture_context_values

    target = Mock()
    capture_context_values(
        manager(),
        target,
        before=[{"text": "original history"}],
        after=[{"role": "user", "content": "summary"}],
        evidence={"raw_token_estimate": 20, "final_token_estimate": 5},
    )
    values = target.set_attributes.call_args.args[0]
    assert "original history" in values["input.value"]
    assert "summary" in values["output.value"]
    assert values["nexent.token_measurement_origin"] == "estimate"


def test_runtime_collaborators_and_profile_provenance_do_not_replace_safe_fields():
    span = Mock()
    capture_run_input(
        manager(),
        span,
        query="question",
        agent_config={
            "tools": [{"name": "lookup", "metadata": {"client": object()}}],
        },
        model_configs=[
            {
                "model_name": "model",
                "resolved_profile": {
                    "parameter_values": {"temperature": 0.2},
                    "provenance": {
                        "overrides": [{"original_value": "private-endpoint?key=secret"}]
                    },
                },
            }
        ],
    )
    body = json.loads(span.set_attributes.call_args.args[0]["nexent.local.input.value"])
    assert body["effective_config"]["model_configs"][0]["resolved_profile"][
        "parameter_values"
    ] == {"temperature": 0.2}
    assert body["effective_config"]["agent_config"]["tools"][0]["name"] == "lookup"
    assert (
        body["availability"]["effective_config.agent_config.tools.0.metadata.client"][
            "status"
        ]
        == "unsupported"
    )
    assert "private-endpoint" not in json.dumps(body)


def test_broken_capture_exporter_does_not_retry_or_fail_context_assembly(monkeypatch):
    from nexent.monitor.run_capture import capture_context_assembly

    configured = manager()
    configured.tracer = Mock()
    configured.tracer.start_span.side_effect = RuntimeError(
        "controlled exporter failure"
    )
    monkeypatch.setattr("nexent.monitor.get_monitoring_manager", lambda: configured)
    method = Mock(return_value="actual result")
    assert capture_context_assembly(method)("request") == "actual result"
    method.assert_called_once_with("request")


@pytest.mark.parametrize("elapsed", [0, 0.25, -1, float("nan"), float("inf")])
@pytest.mark.parametrize("failed", [False, True])
def test_context_duration_keeps_business_result_and_unknown_clock(
    monkeypatch, elapsed, failed
):
    from nexent.monitor.run_capture import capture_context_assembly
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    @dataclass
    class Evidence:
        compression_attempted: bool = False

    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(
        "nexent.monitor.run_capture.time.perf_counter", lambda: clock.value
    )
    provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    configured = manager()
    configured.tracer = provider.get_tracer("duration-test")
    monkeypatch.setattr("nexent.monitor.get_monitoring_manager", lambda: configured)
    result = SimpleNamespace(messages=[], evidence=Evidence())

    def assemble():
        clock.value += elapsed
        if failed:
            raise RuntimeError("controlled assembly error")
        return result

    try:
        if failed:
            with pytest.raises(RuntimeError, match="controlled assembly error"):
                capture_context_assembly(assemble)()
        else:
            assert capture_context_assembly(assemble)() is result
        span = exporter.get_finished_spans()[0]
        if elapsed in (0, 0.25):
            assert span.attributes["nexent.duration_ms"] == elapsed * 1000
        else:
            assert "nexent.duration_ms" not in span.attributes
            assert span.attributes["nexent.availability.duration_ms"] == "not_captured"
        if failed:
            assert span.attributes["nexent.business_status"] == "failed"
    finally:
        provider.shutdown()
