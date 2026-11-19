# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""First-answer timing follows actual public output and execution identity."""

from contextlib import contextmanager
from contextvars import copy_context
from threading import Barrier, Event
from time import monotonic_ns
from types import SimpleNamespace

import pytest

from nexent.core.utils.observer import MessageObserver, ProcessType
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from nexent.monitor.agent_fact import AgentRunObservation
from nexent.monitor.facts import get_fact_sink, set_fact_sink


@pytest.fixture
def capture(monkeypatch):
    clock = SimpleNamespace(ms=0)
    events = []
    observer = MessageObserver()
    monkeypatch.setattr("nexent.monitor.agent_fact.monotonic_ns", lambda: clock.ms * 1_000_000)
    previous = get_fact_sink()
    set_fact_sink(events.append)

    @contextmanager
    def run(run_id="root", number=21):
        metadata = AgentRunMetadata(tenant_id="t", agent_id=number, monitoring_run_id=run_id,
                                    monitoring_root_run_id="root",
                                    monitoring_parent_run_id=None if run_id == "root" else "root")
        with agent_monitoring_context(metadata):
            observation = AgentRunObservation.from_context(metadata)
            with observation.measure(Event()):
                yield observation
            observation.report_terminal("completed")

    try:
        yield SimpleNamespace(clock=clock, events=events, observer=observer, run=run)
    finally:
        set_fact_sink(previous)


@pytest.mark.parametrize("kind", [ProcessType.FINAL_ANSWER, ProcessType.MODEL_OUTPUT])
def test_first_effective_answer_is_measured_once_after_ignored_output(capture, kind):
    c = capture
    with c.run():
        c.clock.ms = 40
        for excluded in (ProcessType.TOOL, ProcessType.TOOL_RESULT, ProcessType.MODEL_OUTPUT_CODE,
                         ProcessType.MODEL_OUTPUT_THINKING, ProcessType.MODEL_OUTPUT_DEEP_THINKING,
                         ProcessType.HUMAN_INTERACTION):
            c.observer.add_message("root", excluded, "private intermediate")
        c.clock.ms = 80
        c.observer.add_message("root", kind, " \n")
        c.clock.ms = 150
        c.observer.add_message("root", kind, "first answer")
        c.clock.ms = 250
        c.observer.add_message("root", kind, "later answer")
        c.clock.ms = 400
    start, terminal = c.events
    assert "ttft_ms" not in start
    assert terminal["ttft_ms"] == 150 and terminal["duration_ms"] == 400
    assert "first answer" not in str(c.events)


@pytest.mark.parametrize("mode", ["missing", "fallback", "zero", "reclassified"])
def test_missing_zero_and_complete_answer_boundaries(capture, mode):
    c = capture
    with c.run():
        if mode == "zero":
            c.observer.add_message("root", ProcessType.FINAL_ANSWER, "answer")
        else:
            c.clock.ms = 70
            c.observer.add_message("root", ProcessType.MODEL_OUTPUT_THINKING, "thinking")
            if mode == "fallback":
                c.observer.mark_answer_fallback()
                c.observer.complete_final_answer("root", "No valid answer was generated.")
            elif mode == "reclassified":
                c.observer.mark_direct_final_answer()
                c.observer.complete_final_answer("root", "thinking")
        c.clock.ms = 200
    terminal = c.events[-1]
    if mode in {"zero", "reclassified"}:
        assert terminal["ttft_ms"] == (0 if mode == "zero" else 70)
    else:
        assert "ttft_ms" not in terminal


def test_child_answers_do_not_trigger_parent_and_cleanup_or_replay_cannot_change_timing(capture):
    c = capture
    with c.run() as parent:
        copied = copy_context()
        c.clock.ms = 10
        c.observer.add_subagent_start(22, "child", invocation_id="child")
        with c.run("child", 22):
            c.clock.ms = 30
            c.observer.add_message("child", ProcessType.FINAL_ANSWER, "child answer")
            c.clock.ms = 40
        c.observer.add_subagent_end(22, "child", invocation_id="child")
        c.clock.ms = 100
        c.observer.add_message("root", ProcessType.FINAL_ANSWER, "root answer")
        c.clock.ms = 150
    child, root = [event for event in c.events if event["record_revision"] == 2]
    assert (child["ttft_ms"], root["ttft_ms"]) == (20, 100)
    snapshot = dict(root)
    c.clock.ms = 900
    c.observer.add_message("root", ProcessType.FINAL_ANSWER, "late cleanup")
    copied.run(c.observer.add_message, "root", ProcessType.FINAL_ANSWER, "late copied context")
    c.observer.get_final_answer()
    parent.report_terminal("completed")
    assert c.events[-1] == snapshot


def test_answer_from_an_unmeasured_child_does_not_leak_to_parent(capture):
    c = capture
    with c.run():
        with agent_monitoring_context(AgentRunMetadata(
            tenant_id="t", agent_id=22, monitoring_run_id="unmeasured", monitoring_root_run_id="root",
            monitoring_parent_run_id="root",
        )):
            c.clock.ms = 80
            c.observer.add_message("child", ProcessType.FINAL_ANSWER, "child")
        c.clock.ms = 100
    assert "ttft_ms" not in c.events[-1]


def test_native_answer_events_reuse_the_same_output_boundary(capture):
    from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter

    c = capture
    native = JiuwenEventAdapter(c.observer, "root")
    with c.run():
        c.clock.ms = 20
        native.output(ProcessType.MODEL_OUTPUT_DEEP_THINKING, "thinking")
        c.clock.ms = 50
        native.output(ProcessType.MODEL_OUTPUT, "native answer")
        c.clock.ms = 100
    assert c.events[-1]["ttft_ms"] == 50


@pytest.mark.asyncio
async def test_parallel_child_answers_keep_independent_timing_and_parent_unmeasured(capture, monkeypatch):
    c = capture
    monkeypatch.setattr("nexent.monitor.agent_fact.monotonic_ns", monotonic_ns)
    barrier = Barrier(2)
    threads = ThreadManager("agent-ttft", {"calls": LanePolicy("calls", 2, 0)})

    def child(run_id):
        c.observer.add_subagent_start(22, "child", invocation_id=run_id)
        try:
            with c.run(run_id, 22):
                barrier.wait(timeout=5)
                c.observer.add_message("child", ProcessType.MODEL_OUTPUT, "answer")
        finally:
            c.observer.add_subagent_end(22, "child", invocation_id=run_id)

    threads.start()
    try:
        with c.run():
            jobs = [threads.submit("calls", ManagedTaskSpec("answer", "test"), child, name)
                    for name in ("left", "right")]
            for job in jobs:
                job.future.result(timeout=8)
        terminals = {event["fact_id"]: event for event in c.events if event["record_revision"] == 2}
        assert set(terminals) == {"left", "right", "root"}
        assert "ttft_ms" not in terminals["root"]
        assert all(0 <= terminals[name]["ttft_ms"] <= terminals[name]["duration_ms"] for name in ("left", "right"))
    finally:
        await threads.shutdown(timeout=8)
