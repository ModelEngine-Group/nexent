# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Main facts and real Agent spans consume one complete lifecycle measurement."""

from contextlib import contextmanager

import pytest
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexent.core.agents.orchestration import entry
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor import MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import set_fact_sink
from test.sdk.core.agents.test_agent_run_facts import worker


@contextmanager
def recorded(worker, monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(
        enable_telemetry=True, provider="local_file", local_span_processor=SimpleSpanProcessor(exporter),
    ))
    monkeypatch.setattr(manager, "_tracer", provider.get_tracer("main-timing-test"))
    try:
        yield provider, exporter
    finally:
        provider.shutdown()


@pytest.mark.parametrize("failure", [None, "run", "cancel", "prepare"])
def test_main_span_and_fact_use_identical_complete_measurement(worker, monkeypatch, failure):
    def run():
        worker.advance("run", 350)
        if failure == "run":
            raise RuntimeError("controlled")
        if failure == "cancel":
            raise RunTerminated("cancelled")

    worker.adapter.run = run
    if failure == "prepare":
        worker.adapter.prepare = lambda: (_ for _ in ()).throw(RuntimeError("controlled"))
    with recorded(worker, monkeypatch) as (_, exporter), agent_monitoring_context(worker.metadata):
        if failure in {"run", "prepare"}:
            with pytest.raises(ValueError, match="controlled"):
                entry.agent_run_thread(worker.info)
        else:
            entry.agent_run_thread(worker.info)
    root, = [span for span in exporter.get_finished_spans() if span.name == "agent.run"]
    result = worker.info.run_timing.finish()
    assert root.start_time == result.started_at_ns
    assert root.end_time == result.ended_at_ns
    assert root.attributes["nexent.duration_ms"] == result.duration_ms
    assert root.attributes["nexent.agent_run_id"] == result.run_id
    if failure == "prepare":
        assert worker.events == [] and result.execution_started_at is None
    else:
        start, end = worker.events
        assert end["duration_ms"] == result.duration_ms
        assert start["started_at"] == end["started_at"] == result.started_at.isoformat()
        assert end["ended_at"] == result.ended_at.isoformat()
        assert start["execution_started_at"] == end["execution_started_at"] == result.execution_started_at.isoformat()


def test_archive_consumer_failure_cannot_prevent_main_terminal_fact(worker, monkeypatch):
    class BrokenArchive(SpanProcessor):
        def on_end(self, span):
            raise OSError("archive unavailable")

    worker.adapter.run = lambda: worker.advance("run", 350)
    with recorded(worker, monkeypatch) as (provider, _):
        provider.add_span_processor(BrokenArchive())
        with agent_monitoring_context(worker.metadata):
            entry.agent_run_thread(worker.info)
    assert len(worker.events) == 2 and worker.events[-1]["outcome"] == "succeeded"
    assert worker.events[-1]["duration_ms"] == worker.info.run_timing.finish().duration_ms


def test_monitor_consumer_failure_cannot_prevent_main_trace_completion(worker, monkeypatch):
    offered = []

    def rejected(event):
        offered.append(event)
        raise OSError("monitor writer unavailable")

    worker.adapter.run = lambda: worker.advance("run", 350)
    set_fact_sink(rejected)
    with recorded(worker, monkeypatch) as (_, exporter), agent_monitoring_context(worker.metadata):
        entry.agent_run_thread(worker.info)
    root, = [span for span in exporter.get_finished_spans() if span.name == "agent.run"]
    assert len(offered) == 2
    assert root.attributes["nexent.duration_ms"] == worker.info.run_timing.finish().duration_ms


@pytest.mark.asyncio
async def test_preparation_is_included_even_with_trajectory_disabled(worker, monkeypatch):
    from nexent.monitor import phase_capture

    monkeypatch.setattr(phase_capture, "RunTiming", lambda: worker.info.run_timing)

    @phase_capture.capture_preparation
    async def prepare():
        worker.advance("request_preparation", 120)
        return worker.info

    info = await prepare()
    assert getattr(info, "preparation_trace", []) == []
    worker.adapter.run = lambda: worker.advance("run", 350)
    with agent_monitoring_context(worker.metadata):
        entry.agent_run_thread(info)
    assert worker.events[-1]["duration_ms"] == 1940
    assert info.run_timing.finish().started_at < info.run_timing.finish().execution_started_at


def test_main_observation_rejects_unshared_or_mismatched_clock(worker):
    from dataclasses import replace
    from threading import Event

    from nexent.monitor.agent_fact import AgentRunObservation
    from nexent.monitor.run_timing import RunTiming

    observation = AgentRunObservation(replace(worker.metadata, monitoring_root_run_id="run"), "run")
    for timing in (None, RunTiming(run_id="other")):
        with pytest.raises(ValueError, match="shared run timing"):
            with observation.measure(Event(), run_timing=timing):
                pytest.fail("Invalid identity must not start execution")
    assert worker.events == []
