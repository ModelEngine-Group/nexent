# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Child execution facts reuse invocation identity and the actual adapter boundary."""

from contextlib import contextmanager
from dataclasses import replace
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.contracts.output import RunResult
from nexent.core.agents.factory import AgentCoreFactory
from nexent.core.agents.orchestration.children import invoke_child
from nexent.core.agents.resources.subagents import SubAgentDefinition, SubAgentToolWrapper
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor import (
    AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_agent_monitoring_context, get_monitoring_manager,
)
from nexent.monitor.agent_fact import AgentRunObservation
from nexent.monitor.facts import get_fact_sink, set_fact_sink
from nexent.monitor.local_content import local_capture_enabled
from nexent.monitor.run_timing import RunTiming


@pytest.fixture
def child_capture(monkeypatch):
    events, phases = [], []
    clock = SimpleNamespace(ns=0)
    metadata = AgentRunMetadata(tenant_id="tenant", agent_id=21, is_debug=False, monitoring_group_ids=(12, 13),
                                monitoring_run_id="root", monitoring_root_run_id="root")

    def advance(phase, ms):
        phases.append(phase)
        clock.ns += ms * 1_000_000

    def sink(event):
        events.append(event)
        advance(event["outcome"], 100)

    monkeypatch.setattr("nexent.monitor.agent_fact.monotonic_ns", lambda: clock.ns)
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=False, provider="local_file"))
    assert not manager.is_enabled and not local_capture_enabled(manager)
    monkeypatch.setattr("nexent.core.agents.resources.subagents.RunTiming",
                        lambda **kw: RunTiming(**kw, utc_clock_ns=lambda: 1793491199900000000 + clock.ns,
                                                monotonic_clock_ns=lambda: clock.ns), raising=False)
    previous = get_fact_sink()
    set_fact_sink(sink)

    def wrapper(*, number=22, failure=None, status="completed", action=None, pre_cancel=False):
        observer = Mock()

        @contextmanager
        def invocation():
            advance("allocate", 20)
            info = SimpleNamespace(stop_event=Event(), run_result=None, attempt_outcome=None)
            if pre_cancel:
                info.stop_event.set()

            def run():
                advance("run", 350)
                if action:
                    return action()
                if failure == "run":
                    raise RuntimeError("run failure")
                if failure == "cancel":
                    raise RunTerminated("cancelled")
                info.run_result = RunResult(turn_id="result-turn", status=status, end_reason="controlled")
                return "child-result"

            def phase(name, ms):
                advance(name, ms)
                if failure == name:
                    raise RuntimeError(f"{name} failure")

            adapter = SimpleNamespace(validate=lambda: phase("validate", 10), prepare=lambda: phase("prepare", 50),
                                      run=run, close=lambda: phase("close", 600))
            monkeypatch.setattr(AgentCoreFactory, "create", lambda _: adapter)
            try:
                yield lambda task, **_: invoke_child(info, task)
            finally:
                advance("release", 700)

        return SubAgentToolWrapper(SubAgentDefinition("child", "Controlled child"), observer, agent_id=number,
                                   runtime_identity={"version_no": 4}, invocation_factory=invocation)

    try:
        yield SimpleNamespace(events=events, phases=phases, metadata=metadata, wrapper=wrapper)
    finally:
        set_fact_sink(previous)


@pytest.mark.parametrize("entry", ["__call__", "forward"])
@pytest.mark.parametrize("status,outcome", [
    ("completed", "succeeded"), ("failed", "failed"), ("stopped", "cancelled"),
])
def test_child_facts_reuse_observer_id_and_typed_result_after_cleanup(child_capture, entry, status, outcome):
    fixture = child_capture
    child = fixture.wrapper(status=status)
    with agent_monitoring_context(fixture.metadata):
        assert getattr(child, entry)(task="private task") == "child-result"
        assert get_agent_monitoring_context() is fixture.metadata
    start, terminal = fixture.events
    observer_id = child._observer.add_subagent_start.call_args.kwargs["invocation_id"]
    assert start["fact_id"] == terminal["fact_id"] == observer_id
    assert start["agent_run_id"] == start["fact_id"] != "root"
    assert start["root_run_id"] == start["parent_run_id"] == "root" and not start["is_root"]
    assert start["agent_id"] == 22 and start["agent_version_no"] == 4
    assert start["tenant_id"] == "tenant" and start["initiator_group_ids"] == (12, 13)
    assert start["record_revision"] == 1 and "duration_ms" not in start
    assert terminal["record_revision"] == 2 and terminal["outcome"] == outcome
    assert terminal["duration_ms"] == 1830 and terminal["started_at"] == start["started_at"]
    assert terminal["ended_at"] >= start["started_at"]
    assert fixture.phases == ["allocate", "validate", "prepare", "started", "run", "close", "release", outcome]
    assert "private task" not in str(fixture.events)


@pytest.mark.parametrize("failure", ["validate", "prepare", "run", "close", "cancel"])
def test_child_failures_preserve_exception_and_only_measure_started_runs(child_capture, failure):
    fixture = child_capture
    child = fixture.wrapper(failure=failure)
    with agent_monitoring_context(fixture.metadata), pytest.raises(
        RunTerminated if failure == "cancel" else RuntimeError,
    ):
        child(task="test")
    if failure in {"validate", "prepare"}:
        assert fixture.events == []
    else:
        assert len(fixture.events) == 2
        assert fixture.events[1]["outcome"] == ("cancelled" if failure == "cancel" else "failed")
        assert fixture.events[1]["duration_ms"] == 1830
    assert "release" in fixture.phases and "close" in fixture.phases
    if fixture.events:
        assert fixture.phases.index("release") < len(fixture.phases) - 1
    assert child._observer.add_subagent_end.call_count == 1


@pytest.mark.parametrize("excluded", ["cancel", "debug", "tenant", "root"])
def test_child_without_formal_execution_or_trusted_context_emits_nothing(child_capture, excluded):
    fixture = child_capture
    metadata = replace(fixture.metadata)
    if excluded == "debug":
        metadata.is_debug = True
    elif excluded == "tenant":
        metadata.tenant_id = None
    elif excluded == "root":
        metadata.monitoring_root_run_id = None
    child = fixture.wrapper(pre_cancel=excluded == "cancel")
    with agent_monitoring_context(metadata):
        child(task="test")
    assert fixture.events == []


def test_repeated_and_nested_calls_have_independent_ids_and_immediate_parents(child_capture):
    fixture = child_capture
    leaf = fixture.wrapper(number=23)
    child = fixture.wrapper(action=lambda: leaf(task="nested"))
    with agent_monitoring_context(fixture.metadata):
        child(task="first")
        child(task="second")
    starts = [event for event in fixture.events if event["outcome"] == "started"]
    assert len(starts) == len({event["fact_id"] for event in starts}) == 4
    for parent, nested in zip(starts[::2], starts[1::2]):
        assert parent["parent_run_id"] == "root" and nested["parent_run_id"] == parent["fact_id"]
        assert parent["agent_id"] == 22 and nested["agent_id"] == 23
        assert parent["root_run_id"] == nested["root_run_id"] == "root"
    for start in starts:
        terminal, = [event for event in fixture.events
                     if event["record_revision"] == 2 and event["fact_id"] == start["fact_id"]]
        assert terminal["parent_run_id"] == start["parent_run_id"]


@pytest.mark.asyncio
async def test_concurrent_wrappers_keep_separate_child_contexts(child_capture):
    fixture = child_capture
    barrier = Barrier(2)
    seen = []

    def inner(task):
        barrier.wait(timeout=5)
        seen.append(get_agent_monitoring_context())
        return task

    wrapper = SubAgentToolWrapper(inner, Mock(), agent_id=22)
    threads = ThreadManager("child-fact-context", {"calls": LanePolicy("calls", 2, 0)})
    threads.start()
    try:
        with agent_monitoring_context(fixture.metadata):
            work = [threads.submit("calls", ManagedTaskSpec("child", "test"), wrapper, task=task)
                    for task in ("left", "right")]
            assert [item.future.result(timeout=8) for item in work] == ["left", "right"]
        assert len({context.monitoring_run_id for context in seen}) == 2
        assert all(context.monitoring_parent_run_id == context.monitoring_root_run_id == "root" for context in seen)
    finally:
        await threads.shutdown(timeout=8)


@pytest.mark.parametrize("run,root,parent", [("child", "root", None), ("child", "root", "child"),
                                             ("root", "root", "other"), ("child", None, "parent")])
def test_incomplete_or_colliding_ancestry_is_excluded(child_capture, run, root, parent):
    metadata = replace(child_capture.metadata, monitoring_run_id=run, monitoring_root_run_id=root,
                       monitoring_parent_run_id=parent)
    assert AgentRunObservation.from_context(metadata) is None
