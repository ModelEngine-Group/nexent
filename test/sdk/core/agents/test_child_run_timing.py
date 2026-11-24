# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Child spans and facts share complete per-invocation clocks."""

from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.agents.factory import AgentCoreFactory
from nexent.core.agents.orchestration.children import invoke_child
from nexent.core.agents.resources.subagents import SubAgentToolWrapper
from nexent.monitor import MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import set_fact_sink
from test.sdk.core.agents.test_child_run_facts import child_capture


def unix_ns(value):
    delta = datetime.fromisoformat(value) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000


@contextmanager
def recorded(monkeypatch, enabled=True):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(
        enable_telemetry=enabled, provider="local_file", local_span_processor=processor,
    ))
    monkeypatch.setattr(manager, "_tracer", provider.get_tracer("child-timing"))
    try:
        yield exporter
    finally:
        provider.shutdown()


@pytest.mark.parametrize("failure", [None, "run", "cancel", "prepare", "close"])
@pytest.mark.parametrize("enabled", [True, False])
def test_child_raw_timing_and_fact_agree_after_complete_release(child_capture, monkeypatch, failure, enabled):
    from nexent.monitor.agent_fact import get_child_run_scope

    c = child_capture
    clocks = []

    def observed():
        clocks.append(get_child_run_scope().timing)

    child = c.wrapper(failure=failure, action=observed if failure is None else None)
    with recorded(monkeypatch, enabled) as exporter, agent_monitoring_context(c.metadata):
        if failure:
            with pytest.raises(RunTerminated if failure == "cancel" else RuntimeError):
                child(task="one")
        else:
            child(task="one")
        assert get_child_run_scope() is None
    spans = exporter.get_finished_spans()
    if failure == "prepare":
        assert c.events == []
    else:
        start, end = c.events
        assert start["started_at"] == end["started_at"]
        assert start["execution_started_at"] == end["execution_started_at"]
        assert end["duration_ms"] == 1830
        if clocks:
            result = clocks[0].finish()
            assert result.started_at.isoformat() == start["started_at"]
            assert result.ended_at.isoformat() == end["ended_at"]
        if enabled:
            span, = spans
            assert span.attributes["nexent.duration_ms"] == end["duration_ms"]
            assert span.attributes["nexent.agent_run_id"] == end["agent_run_id"]
            assert span.start_time == unix_ns(start["started_at"])
            assert span.end_time == unix_ns(end["ended_at"])
    if not enabled:
        assert spans == ()


def test_repeated_and_nested_invocations_never_share_clock_objects(child_capture, monkeypatch):
    from nexent.monitor.agent_fact import get_child_run_scope
    from nexent.monitor.run_timing import RunTiming

    c = child_capture
    clocks = []
    parent = RunTiming(run_id="root")
    parent.start()

    def leaf_action():
        clocks.append(get_child_run_scope().timing)

    leaf = c.wrapper(number=23, action=leaf_action)

    def child_action():
        scope = get_child_run_scope()
        clocks.append(scope.timing)
        leaf(task="nested")
        assert get_child_run_scope() is scope

    child = c.wrapper(action=child_action)
    with recorded(monkeypatch), agent_monitoring_context(c.metadata):
        child(task="first")
        child(task="second")
    assert len({id(clock) for clock in clocks}) == len({clock.run_id for clock in clocks}) == 4
    assert all(clock is not parent for clock in clocks)
    assert parent.started_at is not None and get_child_run_scope() is None
    terminals = {event["agent_run_id"]: event for event in c.events if event["record_revision"] == 2}
    for clock in clocks:
        assert terminals[clock.run_id]["duration_ms"] == clock.finish().duration_ms


@pytest.mark.asyncio
async def test_concurrent_calls_bind_separate_info_and_timing(child_capture, monkeypatch):
    from nexent.monitor.agent_fact import get_child_run_scope

    c = child_capture
    barrier = Barrier(2)
    infos = []

    def target(task):
        info = SimpleNamespace(stop_event=Event(), run_result=None, attempt_outcome=None)
        infos.append(info)
        barrier.wait(timeout=5)
        assert invoke_child(info, task) == "answer"
        assert info.run_timing is get_child_run_scope().timing

    monkeypatch.setattr(AgentCoreFactory, "create", lambda _: SimpleNamespace(
        validate=lambda: None, prepare=lambda: None, run=lambda: "answer", close=lambda: None,
    ))
    wrapper = SubAgentToolWrapper(target, Mock(), agent_id=22)
    threads = ThreadManager("child-clock-concurrency", {"calls": LanePolicy("calls", 2, 0)})
    threads.start()
    try:
        with agent_monitoring_context(c.metadata):
            jobs = [threads.submit("calls", ManagedTaskSpec("child", "test"), wrapper, task=task)
                    for task in ("left", "right")]
            for job in jobs:
                job.future.result(timeout=8)
        assert len({id(info.run_timing) for info in infos}) == len({info.run_timing.run_id for info in infos}) == 2
        assert get_child_run_scope() is None
        terminals = {event["agent_run_id"]: event for event in c.events if event["record_revision"] == 2}
        for info in infos:
            assert terminals[info.run_timing.run_id]["duration_ms"] == info.run_timing.finish().duration_ms
    finally:
        await threads.shutdown(timeout=8)
        assert threads.snapshot().active_count == 0


def test_child_sink_failure_does_not_prevent_trace_completion(child_capture, monkeypatch):
    offered = []

    def reject(event):
        offered.append(event)
        raise OSError("unavailable")

    set_fact_sink(reject)
    with recorded(monkeypatch) as exporter, agent_monitoring_context(child_capture.metadata):
        child_capture.wrapper()(task="test")
    span, = exporter.get_finished_spans()
    assert len(offered) == 2 and offered[-1]["duration_ms"] == span.attributes["nexent.duration_ms"]


def test_child_archive_failure_does_not_prevent_terminal_fact(child_capture, monkeypatch):
    from opentelemetry.sdk.trace import SpanProcessor

    class BrokenArchive(SpanProcessor):
        def on_end(self, span):
            raise OSError("unavailable")

    manager = get_monitoring_manager()
    provider = TracerProvider()
    provider.add_span_processor(BrokenArchive())
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=True))
    monkeypatch.setattr(manager, "_tracer", provider.get_tracer("broken"))
    try:
        with agent_monitoring_context(child_capture.metadata):
            child_capture.wrapper()(task="test")
        assert child_capture.events[-1]["outcome"] == "succeeded"
    finally:
        provider.shutdown()


def test_child_full_start_and_actual_date_anchor_remain_distinct(child_capture, monkeypatch):
    from nexent.monitor.run_timing import RunTiming

    c = child_capture
    utc = iter((1793491199900000000, 1793491200100000000, 1793491201800000000))
    monkeypatch.setattr("nexent.core.agents.resources.subagents.RunTiming",
                        lambda **kw: RunTiming(**kw, utc_clock_ns=lambda: next(utc)))
    with recorded(monkeypatch) as exporter, agent_monitoring_context(c.metadata):
        c.wrapper()(task="cross midnight")
    start, terminal = c.events
    assert start["started_at"].startswith("2026-10-31")
    assert start["execution_started_at"].startswith("2026-11-01")
    assert start["execution_started_at"] == terminal["execution_started_at"]
    span, = exporter.get_finished_spans()
    assert span.start_time == unix_ns(start["started_at"]) and span.end_time == unix_ns(terminal["ended_at"])


@pytest.mark.parametrize("stage", ["release", "callback"])
def test_late_wrapper_failure_retains_original_child_result(child_capture, monkeypatch, stage):
    c = child_capture
    child = c.wrapper()
    original = child._invocation_factory

    @contextmanager
    def release_failure():
        with original() as target:
            yield target
        raise RuntimeError("late failure")

    def callback(_):
        raise RuntimeError("late failure")

    if stage == "release":
        child._invocation_factory = release_failure
    else:
        child.set_success_callback(callback)
    with recorded(monkeypatch) as exporter, agent_monitoring_context(c.metadata):
        with pytest.raises(RuntimeError, match="late failure"):
            child(task="test")
    span, = exporter.get_finished_spans()
    assert c.events[-1]["outcome"] == "succeeded"
    assert c.events[-1]["duration_ms"] == span.attributes["nexent.duration_ms"] == 1830
