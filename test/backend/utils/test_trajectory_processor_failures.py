# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Processor faults remain isolated and release queued bytes and span references."""

import queue
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import CaptureIdentity
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, Decision


@pytest.fixture
def processor():
    metadata = SimpleNamespace(
        tenant_id="t", user_id="u", conversation_id=1, agent_id=7, extra_metadata={}
    )
    store = Mock()
    store._run.return_value = {"confirmed_bytes": 12}
    worker = LocalTrajectoryProcessor(store, lambda: metadata)
    worker._accepting = True
    return worker


def request(*attrs):
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "attributes": [
                                    {"key": key, "value": {"boolValue": value}}
                                    for key, value in attrs
                                ],
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "1100000000",
                                "events": [],
                            }
                        ]
                    }
                ]
            }
        ]
    }


def test_start_failure_stops_accepting_and_duplicate_start_is_rejected(processor):
    manager = Mock()
    manager.start_service.side_effect = RuntimeError("start failed")
    with pytest.raises(RuntimeError, match="start failed"):
        processor.start(manager, "spec")
    assert not processor._accepting
    with pytest.raises(RuntimeError, match="already started"):
        processor.start(manager, "spec")


def test_wrapped_sampler_preserves_sampled_decision_and_description():
    sampler = LocalTrajectoryProcessor.wrap_sampler(ALWAYS_ON)
    assert (
        sampler.should_sample(None, 1, "agent.run").decision
        == Decision.RECORD_AND_SAMPLE
    )
    assert "AlwaysOnSampler" in sampler.get_description()


def test_enqueue_full_and_per_run_budget_record_gaps_without_retaining_bytes(processor):
    processor._queue = queue.Queue(maxsize=1)
    assert processor._enqueue("run", "span", {}, 5)
    assert not processor._enqueue("second", "span", {}, 5)
    assert processor._bytes == 5 and processor._run_bytes == {"run": 5}
    assert "second" in processor._gaps
    processor._queue.get_nowait()
    processor.run_queue_max_bytes = 5
    assert not processor._enqueue("run", "span", {}, 1)
    assert "run" in processor._gaps


def test_end_serialization_failure_keeps_terminal_outcome_and_releases_active_span(
    processor, mocker
):
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    mocker.patch(
        "infrastructure.observability.trajectory_processor.span_request",
        side_effect=ValueError("encoding"),
    )
    try:
        with provider.get_tracer("test").start_as_current_span(
            "agent.run", attributes={"nexent.cancelled": True}
        ) as span:
            run_id = span.attributes["nexent.trajectory_id"]
        assert processor._terminal[run_id][0] == "cancelled"
        assert not processor._active and not processor._started
        assert run_id in processor._gaps
    finally:
        provider.shutdown()


def test_start_failure_and_capacity_limit_do_not_escape_to_agent(
    processor, mocker, caplog
):
    span = Mock(name="span")
    span.name = "agent.run"
    processor.metadata_provider = Mock(side_effect=RuntimeError("metadata unavailable"))
    processor.on_start(span)
    span.set_attributes.assert_not_called()
    assert "trajectory.capture_start_failed" in caplog.text
    processor.metadata_provider.return_value = None
    processor.metadata_provider.side_effect = None
    processor.on_start(span)
    span.set_attributes.assert_not_called()
    mocker.patch(
        "infrastructure.observability.trajectory_processor.trace.get_current_span",
        return_value=SimpleNamespace(attributes={"nexent.trajectory_id": "run"}),
    )
    processor._active = dict.fromkeys(range(10000))
    processor.on_start(span)
    assert "run" in processor._gaps and len(processor._active) == 10000


def test_append_retries_same_batch_and_marks_all_capture_gaps(processor):
    writer = processor._writers["run"] = Mock()
    writer.append.side_effect = [OSError("temporary"), {"confirmed_bytes": 24}]
    processor._gaps.add("run")
    payload = request(("nexent.trajectory.gap", True))
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["droppedEventsCount"] = 1
    processor._append("run", [payload])
    assert processor._offsets["run"] == 24
    assert writer.append.call_count == 2
    assert writer.append.call_args_list[0] == writer.append.call_args_list[1]
    assert {c.args[0] for c in writer.mark_incomplete.call_args_list} == {
        "capture_gap",
        "serialization_failed",
        "otel_dropped_data",
    }
    writer.append.side_effect = OSError("persistent")
    with pytest.raises(OSError, match="persistent"):
        processor._append("run", [payload])
    assert writer.append.call_count == 4


@pytest.mark.parametrize(
    "error", [PermissionError("revoked"), ValueError("bad payload")]
)
def test_flush_failure_releases_bytes_and_revocation_closes_writer(processor, error):
    writer = processor._writers["run"] = Mock()
    writer.append.side_effect = error
    processor._pending = {"run": [request()]}
    processor._pending_bytes = {"run": 10}
    processor._bytes = 12
    processor._run_bytes = {"run": 12}
    processor._flush_pending()
    assert processor._bytes == 2 and processor._run_bytes == {"run": 2}
    assert not processor._pending and not processor._pending_bytes
    assert "run" in processor._gaps
    if isinstance(error, PermissionError):
        writer.close.assert_called_once()
        processor.store.recover.assert_called_once_with(writer.identity, "run")
        assert "run" not in processor._writers
    else:
        writer.close.assert_not_called()


@pytest.mark.parametrize("failure", ["large", "revoked"])
def test_active_snapshot_failure_cannot_retain_or_publish_generated_body(
    processor, mocker, failure
):
    writer = processor._writers["run"] = Mock()
    processor._active = {
        1: SimpleNamespace(
            attributes={"nexent.trajectory_id": "run"},
            context=SimpleNamespace(span_id=1),
        )
    }
    payload = request(("output.value", True))
    mocker.patch(
        "infrastructure.observability.trajectory_processor.span_request",
        return_value=payload,
    )
    if failure == "large":
        processor.run_queue_max_bytes = 1
    else:
        writer.append.side_effect = PermissionError("revoked")
    processor._snapshot_active()
    assert processor._last_snapshot == {}
    if failure == "large":
        writer.mark_incomplete.assert_called_once_with("capture_gap")
        writer.append.assert_not_called()
    else:
        writer.close.assert_called_once()


def test_terminal_revocation_releases_writer_and_all_run_state(processor):
    writer = processor._writers["run"] = Mock()
    writer.finish.side_effect = PermissionError("revoked")
    processor.store.recover.side_effect = RuntimeError("defer recovery")
    processor._terminal["run"] = ("completed", datetime.now(UTC))
    processor._offsets["run"] = 12
    processor._last_snapshot[("run", 1)] = "fingerprint"
    processor._publish_completed()
    writer.close.assert_called_once()
    assert not processor._writers and not processor._terminal and not processor._offsets
    assert not processor._last_snapshot


def test_worker_flush_and_shutdown_failures_still_release_all_resources(
    processor, mocker, caplog
):
    processor._writers["run"] = writer = Mock()
    writer.trajectory_id = "run"
    processor.store.start.side_effect = RuntimeError("registration failed")
    processor.store.recover.side_effect = RuntimeError("recover failed")
    mocker.patch.object(
        processor, "_flush_pending", side_effect=RuntimeError("disk offline")
    )
    processor._maintenance_iterator = iterator = Mock()
    processor._enqueue(
        "run", "start", ("owner", "turn", "smolagents", None, None, None)
    )
    processor.request_stop()
    processor._work(threading.Event())
    assert processor._queue.unfinished_tasks == 0 and processor._bytes == 0
    assert (
        not processor._writers
        and not processor._active
        and not processor._last_snapshot
    )
    writer.close.assert_called_once()
    iterator.close.assert_called_once()
    for event in (
        "storage_failed",
        "storage_flush_failed",
        "final_archive_failed",
        "interrupted_archive_failed",
    ):
        assert f"trajectory.{event}" in caplog.text


def test_worker_recovery_scan_resumes_at_bounded_turn_without_rechecking_old_runs(
    processor, mocker
):
    store = processor._maintenance_store = Mock(retention_days=30)
    store.clock.return_value = datetime.now(UTC)
    owner = CaptureIdentity("t", "u", "1", "7")
    store.identities.return_value = iter([owner])
    store.manifest.return_value = {
        "runs": [
            {"turn_no": i, "trajectory_id": str(i), "capture_state": "writing"}
            for i in range(1, 1002)
        ]
    }
    store.recover.side_effect = RuntimeError("active elsewhere")
    mocker.patch(
        "infrastructure.observability.trajectory_processor.time.monotonic",
        return_value=100,
    )
    mocker.patch.object(processor._queue, "empty", side_effect=[True, False])
    processor._maintain()
    assert processor._maintenance_pending == (owner, 1000)
    assert store.recover.call_count == 1000
    mocker.patch.object(processor._queue, "empty", return_value=True)
    processor._maintain()
    assert store.recover.call_count == 1001
    assert (
        processor._maintenance_pending is None
        and processor._maintenance_iterator is None
    )
