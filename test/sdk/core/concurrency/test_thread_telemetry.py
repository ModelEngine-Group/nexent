import asyncio
import json
import sys
import threading
import types
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder

_SDK_PACKAGE = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
if "nexent" not in sys.modules:
    nexent_package = types.ModuleType("nexent")
    nexent_package.__path__ = [str(_SDK_PACKAGE)]
    sys.modules["nexent"] = nexent_package
if "nexent.core" not in sys.modules:
    core_package = types.ModuleType("nexent.core")
    core_package.__path__ = [str(_SDK_PACKAGE / "core")]
    sys.modules["nexent.core"] = core_package

from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    ManagedThreadSpec,
    ThreadCapacityExceeded,
    ThreadManager,
)
from nexent.core.concurrency import telemetry as telemetry_module


class RecordingTelemetry:
    def __init__(self):
        self.snapshots = []

    def record_snapshot(
        self,
        service_name,
        event,
        execution,
        counts,
        *,
        dedicated,
        **fields,
    ):
        self.snapshots.append(
            (service_name, event, execution, counts, dedicated, fields)
        )


class RecordingSpan:
    def __init__(self):
        self.attributes = {}
        self.events = []
        self.statuses = []
        self.ended = 0

    def set_attributes(self, attributes):
        self.attributes.update(attributes)

    def add_event(self, name, attributes=None):
        self.events.append((name, attributes or {}))

    def set_status(self, status):
        self.statuses.append(status)

    def end(self):
        self.ended += 1


class RecordingTracer:
    def __init__(self):
        self.calls = []
        self.spans = []

    def start_span(self, name, *, kind, attributes):
        span = RecordingSpan()
        self.calls.append((name, kind, attributes))
        self.spans.append(span)
        span.attributes.update(attributes)
        return span


def _manager(telemetry):
    manager = ThreadManager(
        service_name="test-runtime",
        lane_policies={
            "agent-run": LanePolicy(
                name="agent-run",
                max_workers=1,
                max_queue_size=1,
                cancel_grace_seconds=0.1,
                shutdown_grace_seconds=0.2,
            ),
            "background-service": LanePolicy(
                name="background-service",
                max_workers=1,
                max_queue_size=0,
                cancel_grace_seconds=0.1,
                shutdown_grace_seconds=0.2,
            ),
        },
        telemetry=telemetry,
    )
    manager.start()
    return manager


def test_tc_tlm_017_emits_current_statistics_for_each_state_change():
    telemetry = RecordingTelemetry()
    manager = _manager(telemetry)

    execution = manager.submit(
        "agent-run",
        ManagedTaskSpec(task_name="agent-run", owner="sdk-agent", run_id="run-1"),
        lambda: "done",
    )
    assert execution.future.result(timeout=1) == "done"

    assert [item[1] for item in telemetry.snapshots] == [
        "thread.queued",
        "thread.started",
        "thread.finished",
    ]
    assert telemetry.snapshots[0][3] == (1, 1, 0, 0)
    assert telemetry.snapshots[1][3] == (1, 0, 1, 0)
    assert telemetry.snapshots[2][3] == (0, 0, 0, 0)
    assert telemetry.snapshots[2][5]["result"] == "succeeded"

    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_017_otel_snapshot_span_is_immediate_and_uses_current_counts(
    monkeypatch,
):
    tracer = RecordingTracer()
    monkeypatch.setattr(telemetry_module, "OTEL_AVAILABLE", True)
    monkeypatch.setattr(telemetry_module.trace, "get_tracer", lambda _name: tracer)
    telemetry = telemetry_module.OpenTelemetryThreadTelemetry()
    execution = types.SimpleNamespace(
        execution_id="execution-1",
        lane="agent-run",
        state=types.SimpleNamespace(value="queued"),
        spec=types.SimpleNamespace(
            task_name="agent-run",
            owner="sdk-agent",
            run_id="run-1",
            attempt_id="attempt-1",
        ),
        created_at_monotonic=10.0,
        started_at_monotonic=11.0,
        finished_at_monotonic=13.0,
    )

    telemetry.record_snapshot(
        "runtime",
        "thread.started",
        execution,
        (3, 0, 3, 0),
        dedicated=False,
    )
    execution.state = types.SimpleNamespace(value="succeeded")
    telemetry.record_snapshot(
        "runtime",
        "thread.finished",
        execution,
        (0, 0, 0, 0),
        dedicated=False,
        result="succeeded",
    )

    name, kind, initial_attributes = tracer.calls[0]
    assert name == "thread.manager.snapshot"
    assert kind is telemetry_module.SpanKind.INTERNAL
    assert initial_attributes["openinference.span.kind"] == "CHAIN"
    assert initial_attributes["nexent.span.kind"] == "thread"
    assert initial_attributes["thread.event"] == "thread.started"
    assert initial_attributes["thread.execution.id"] == "execution-1"
    assert initial_attributes["thread.counts.managed_active"] == 3
    assert initial_attributes["thread.counts.queued"] == 0
    assert initial_attributes["thread.counts.running"] == 3
    assert not any(key.endswith(".start") for key in initial_attributes)
    assert not any(key.endswith(".end") for key in initial_attributes)
    assert len(tracer.spans) == 2
    assert all(span.ended == 1 for span in tracer.spans)
    assert tracer.calls[1][2]["thread.counts.managed_active"] == 0
    assert tracer.calls[1][2]["thread.result"] == "succeeded"


def test_tc_tlm_021_snapshot_lists_task_composition_without_telemetry_side_effects():
    telemetry = RecordingTelemetry()
    manager = _manager(telemetry)
    release = threading.Event()
    started = threading.Event()
    service_started = threading.Event()

    task = manager.submit(
        "agent-run",
        ManagedTaskSpec(task_name="agent-run", owner="sdk-agent"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    service = manager.register_service(
        ManagedThreadSpec(
            task_name="monitoring-buffer-flush",
            owner="nexent.monitor.monitoring",
        ),
        lambda cancel_event: (service_started.set(), cancel_event.wait(1)),
    )
    manager.start_service(service.execution_id)
    assert service_started.wait(1)

    telemetry_calls_before_snapshot = len(telemetry.snapshots)
    snapshot = manager.snapshot()
    assert telemetry_calls_before_snapshot == len(telemetry.snapshots)

    composition = {item.task_name: item for item in snapshot.executions}
    assert set(composition) == {"agent-run", "monitoring-buffer-flush"}
    assert composition["agent-run"].lane == "agent-run"
    assert composition["agent-run"].owner == "sdk-agent"
    assert composition["agent-run"].dedicated is False
    assert composition["agent-run"].thread_alive is True
    assert composition["monitoring-buffer-flush"].lane == "background-service"
    assert composition["monitoring-buffer-flush"].dedicated is True
    assert composition["monitoring-buffer-flush"].thread_name.startswith(
        "nexent-test-runtime-monitoring-buffer-flush"
    )
    assert composition["monitoring-buffer-flush"].thread_alive is True

    release.set()
    task.future.result(timeout=1)
    manager.cancel(service.execution_id, reason="test cleanup")
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_021_snapshot_is_json_serializable_for_internal_endpoint():
    telemetry = RecordingTelemetry()
    manager = _manager(telemetry)
    service = manager.register_service(
        ManagedThreadSpec(
            task_name="monitoring-buffer-flush",
            owner="nexent.monitor.monitoring",
        ),
        lambda cancel_event: cancel_event.wait(1),
    )

    payload = jsonable_encoder(manager.snapshot())

    assert payload["state"] == "running"
    assert payload["python_active_thread_count"] >= 1
    assert payload["executions"] == [
        {
            "execution_id": service.execution_id,
            "lane": "background-service",
            "task_name": "monitoring-buffer-flush",
            "owner": "nexent.monitor.monitoring",
            "state": "registered",
            "run_id": None,
            "attempt_id": None,
            "dedicated": True,
            "thread_name": None,
            "thread_alive": False,
            "age_seconds": payload["executions"][0]["age_seconds"],
        }
    ]

    manager.cancel(service.execution_id, reason="test cleanup")
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_017_capacity_rejection_emits_snapshot_and_logs_one_warning(caplog):
    telemetry = RecordingTelemetry()
    manager = _manager(telemetry)
    release = threading.Event()
    started = threading.Event()
    first = manager.submit(
        "agent-run",
        ManagedTaskSpec(task_name="first", owner="test"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)
    second = manager.submit(
        "agent-run",
        ManagedTaskSpec(task_name="second", owner="test"),
        lambda: None,
    )

    with (
        caplog.at_level("INFO", logger="thread_manager"),
        pytest.raises(ThreadCapacityExceeded),
    ):
        manager.submit(
            "agent-run",
            ManagedTaskSpec(task_name="rejected", owner="test"),
            lambda: None,
        )

    rejected_snapshots = [
        item for item in telemetry.snapshots if item[1] == "thread.rejected"
    ]
    assert len(rejected_snapshots) == 1
    assert rejected_snapshots[0][5]["result"] == "rejected"
    records = [record for record in caplog.records if record.name == "thread_manager"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["event"] == "thread_task_rejected"
    assert payload["execution"]["task_name"] == "rejected"

    release.set()
    first.future.result(timeout=1)
    second.future.result(timeout=1)
    asyncio.run(manager.shutdown(timeout=1))


def test_tc_tlm_017_stuck_and_worker_exit_emit_separate_current_snapshots():
    telemetry = RecordingTelemetry()
    manager = _manager(telemetry)
    release = threading.Event()
    started = threading.Event()
    execution = manager.submit(
        "agent-run",
        ManagedTaskSpec(task_name="stuck", owner="test"),
        lambda: (started.set(), release.wait(1)),
    )
    assert started.wait(1)

    result = manager.cancel(execution.execution_id, reason="test", wait_timeout=0)
    assert result.stuck is True
    assert [item[1] for item in telemetry.snapshots][-2:] == [
        "thread.cancel_requested",
        "thread.stuck",
    ]

    release.set()
    execution.future.result(timeout=1)
    finishes = [
        item
        for item in telemetry.snapshots
        if item[1] == "thread.finished"
        and item[2].execution_id == execution.execution_id
    ]
    assert len(finishes) == 1
    assert finishes[0][5]["result"] == "cancelled"
    asyncio.run(manager.shutdown(timeout=1))
