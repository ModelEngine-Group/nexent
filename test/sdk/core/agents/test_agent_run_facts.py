# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Root Agent facts follow the adapter run even with telemetry disabled."""

from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest

from nexent.core.agents.contracts.output import RunResult
from nexent.core.agents.factory import AgentCoreFactory
from nexent.core.agents.orchestration import entry
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import get_fact_sink, set_fact_sink
from nexent.monitor.local_content import local_capture_enabled
from nexent.monitor.run_timing import RunTiming


@pytest.fixture
def worker(monkeypatch):
    phases = []
    events = []
    clock = SimpleNamespace(ns=0)
    info = SimpleNamespace(
        agent_config=SimpleNamespace(name="root", version_no=3), query="private prompt",
        workspace_run_id="root-run", stop_event=Event(), mcp_host=None,
        observer=MessageObserver(), attempt_outcome=None, run_result=None,
        model_config_list=[], history=[], minio_files=[],
    )
    info.run_timing = RunTiming(utc_clock_ns=lambda: 1_795_132_799_000_000_000 + clock.ns,
                               monotonic_clock_ns=lambda: clock.ns)
    info.cancellation_scope = RunCancellationScope(info.stop_event)
    metadata = AgentRunMetadata(
        tenant_id="tenant", agent_id=21, is_debug=False, monitoring_group_ids=(13, 12),
    )

    def advance(phase, ms):
        phases.append(phase)
        clock.ns += ms * 1_000_000

    def sink(event):
        events.append(event)
        advance(event["outcome"], 100)

    adapter = SimpleNamespace(
        validate=lambda: advance("validate", 20),
        prepare=lambda: advance("prepare", 50),
        close=lambda: advance("adapter cleanup", 600),
    )
    monkeypatch.setattr(AgentCoreFactory, "create", lambda _: adapter)
    monkeypatch.setattr(entry, "cleanup_run_workspace", lambda *_: advance("workspace cleanup", 700))
    monkeypatch.setattr("nexent.monitor.agent_fact.monotonic_ns", lambda: clock.ns)
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=False, provider="local_file"))
    assert not local_capture_enabled(manager)
    previous_sink = get_fact_sink()
    set_fact_sink(sink)
    try:
        yield SimpleNamespace(
            info=info, metadata=metadata, adapter=adapter, events=events, phases=phases, advance=advance,
        )
    finally:
        set_fact_sink(previous_sink)


@pytest.mark.parametrize(
    ("attempt_outcome", "event_outcome", "failure"),
    [
        ("completed", "succeeded", None),
        ("failed", "failed", RuntimeError),
        ("stopped", "cancelled", RunTerminated),
    ],
)
def test_root_fact_uses_complete_shared_timing_and_reports_after_cleanup(worker, attempt_outcome, event_outcome, failure):
    def run():
        worker.advance("run", 350)
        if failure:
            raise failure("controlled")
        worker.info.run_result = RunResult(turn_id="other-turn", status="completed", end_reason="final_answer")

    worker.adapter.run = run
    with agent_monitoring_context(worker.metadata):
        if failure is RuntimeError:
            with pytest.raises(ValueError, match="controlled"):
                entry.agent_run_thread(worker.info)
        else:
            entry.agent_run_thread(worker.info)

    assert worker.info.attempt_outcome == attempt_outcome
    assert worker.phases == ["validate", "prepare", "started", "run", "adapter cleanup",
                             "workspace cleanup", event_outcome]
    start, finish = worker.events
    assert start["record_revision"] == 1 and "duration_ms" not in start
    assert finish["record_revision"] == 2 and finish["duration_ms"] == 1820
    result = worker.info.run_timing.finish()
    assert start["started_at"] == result.started_at.isoformat()
    assert finish["ended_at"] == result.ended_at.isoformat()
    assert start["execution_started_at"] == result.execution_started_at.isoformat()
    assert finish["outcome"] == event_outcome and finish["ended_at"] >= start["started_at"]
    assert {key: finish[key] for key in start if key not in {"outcome", "record_revision"}} == {
        key: value for key, value in start.items() if key not in {"outcome", "record_revision"}
    }
    assert set(start) == {
        "tenant_id", "fact_kind", "fact_id", "call_context_id", "agent_run_id", "root_run_id",
        "agent_id", "agent_version_no", "is_root", "initiator_group_ids",
        "started_at", "execution_started_at", "record_revision", "outcome",
    }
    assert start["fact_id"] == start["agent_run_id"] == start["root_run_id"] == "root-run"
    assert start["agent_version_no"] == 3 and start["initiator_group_ids"] == (13, 12)


@pytest.mark.parametrize("before_start", ["deferred", "prepare", "cancel", "debug", "missing_identity"])
def test_runs_outside_the_formal_execution_boundary_do_not_emit(worker, before_start):
    worker.adapter.run = lambda: worker.advance("run", 10)
    if before_start == "deferred":
        deferred = entry.DeferredAgentRun()
        deferred.bind(worker.info)
        deferred.cancel()
        with agent_monitoring_context(worker.metadata):
            deferred.run(Event())
        assert worker.phases == []
    else:
        if before_start == "prepare":
            def fail_prepare():
                raise RuntimeError("prepare failed")
            worker.adapter.prepare = fail_prepare
        elif before_start == "cancel":
            worker.info.stop_event.set()
        elif before_start == "debug":
            worker.metadata.is_debug = True
        else:
            worker.metadata.tenant_id = None
        with agent_monitoring_context(worker.metadata):
            if before_start == "prepare":
                with pytest.raises(ValueError, match="prepare failed"):
                    entry.agent_run_thread(worker.info)
                assert "run" not in worker.phases
            else:
                entry.agent_run_thread(worker.info)
        assert "workspace cleanup" in worker.phases
    assert not worker.events


def test_root_fact_reuses_fallback_id_and_preserves_known_empty_groups(worker):
    worker.adapter.run = lambda: worker.advance("run", 1)
    worker.info.workspace_run_id = None
    worker.metadata.monitoring_group_ids = ()
    with agent_monitoring_context(worker.metadata):
        entry.agent_run_thread(worker.info)
    start, finish = worker.events
    assert str(UUID(start["fact_id"])) == start["fact_id"] == finish["fact_id"]
    assert start["initiator_group_ids"] == finish["initiator_group_ids"] == ()
