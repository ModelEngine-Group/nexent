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


def _manager(telemetry=None):
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


@pytest.fixture(scope="module")
def snapshot_tracing():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trace, "_TRACER_PROVIDER", provider)
        try:
            yield provider.get_tracer(__name__), exporter
        finally:
            provider.shutdown()


@pytest.mark.parametrize("dedicated", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_ut_sdk_trace_008_default_manager_does_not_export_snapshot_spans(
    snapshot_tracing, dedicated, fail,
):
    tracer, exporter = snapshot_tracing
    exporter.clear()
    manager = _manager()

    def work(*_args):
        with tracer.start_as_current_span("tool.work"):
            if fail:
                raise ValueError("task failed")
            return "done"

    try:
        with tracer.start_as_current_span("agent.run") as parent:
            if dedicated:
                execution = manager.register_service(
                    ManagedThreadSpec(task_name="work", owner="test"), work,
                )
                manager.start_service(execution.execution_id)
            else:
                execution = manager.submit(
                    "agent-run", ManagedTaskSpec(task_name="work", owner="test"), work,
                )
            if fail:
                with pytest.raises(ValueError, match="task failed"):
                    execution.future.result(timeout=2)
            else:
                assert execution.future.result(timeout=2) == "done"
        asyncio.run(manager.shutdown(timeout=2))

        spans = exporter.get_finished_spans()
        assert sorted(span.name for span in spans) == ["agent.run", "tool.work"]
        child = next(span for span in spans if span.name == "tool.work")
        assert child.parent.span_id == parent.get_span_context().span_id
        assert child.context.trace_id == parent.get_span_context().trace_id
        metrics, = manager.metrics_snapshot()
        assert metrics.completed_count == 1
        assert metrics.failed_count == int(fail)
    finally:
        asyncio.run(manager.shutdown(timeout=2))


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
