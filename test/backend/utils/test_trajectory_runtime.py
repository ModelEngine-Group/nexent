# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backend configuration, maintenance and trusted authorization boundaries."""

import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_runtime import (
    authorize_capture,
    create_local_processor,
    request_conversation_cleanup,
)
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)


def configuration(root="", **overrides):
    values = {
        "ENABLE_TELEMETRY": False,
        "MONITORING_PROVIDER": "otlp",
        "TRAJECTORY_ROOT_DIR": str(root),
        "TRAJECTORY_READ_ENABLED": bool(root),

        "TRAJECTORY_RETENTION_DAYS": 30,
        "TRAJECTORY_FLUSH_INTERVAL_MS": 200,
        "TRAJECTORY_FLUSH_BYTES": 262144,
        "TRAJECTORY_QUEUE_MAX_BYTES": 268435456,
        "TRAJECTORY_RUN_QUEUE_MAX_BYTES": 16777216,
        "TRAJECTORY_CLEANUP_ENABLED": True,
        "TRAJECTORY_CLEANUP_INTERVAL_SECONDS": 3600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_default_configuration_has_no_filesystem_side_effects():
    assert create_local_processor(configuration(), lambda: None) is None


def test_cleanup_is_independent_of_telemetry_and_active_capture(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    TrajectoryFileStore.provision(tmp_path)
    processor = create_local_processor(configuration(tmp_path), lambda: None)
    maintenance = processor._maintenance_store
    identity = CaptureIdentity("tenant", "owner", "1", "42")
    now = datetime(2026, 11, 1, tzinfo=UTC)
    maintenance.clock = lambda: now
    with maintenance.start(identity, str(uuid4()), str(uuid4()), core_type="jiuwen") as writer:
        writer.finish("completed")
    active = maintenance.start(identity, str(uuid4()), str(uuid4()), core_type="jiuwen")
    maintenance.clock = lambda: now + timedelta(days=30)
    try:
        processor._maintain()
        meta = maintenance.manifest(identity)
        assert meta["runs"][0]["capture_state"] == "expired"
        assert meta["runs"][0]["file_deleted_at"] is not None
        assert meta["runs"][1]["capture_state"] == "writing"
        events = [json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
                  for record in caplog.records if record.getMessage().startswith("trajectory.cleanup ")]
        event, = events
        assert event["source"] == "scheduled" and event["actor_id"] is None
        assert event["tenant_id"] == "tenant" and event["conversation_id"] == "1"
        assert event["before_days"] == 30 and event["cutoff_at"] == "2026-11-01T00:00:00Z"
        assert event["deleted_runs"] == 1 and event["skipped_active"] == 1
        assert event["status"] == "success" and event["counts_complete"]
    finally:
        active.close()


def test_startup_recovery_seals_orphan_even_when_cleanup_disabled(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    processor = create_local_processor(
        configuration(
            tmp_path,
            ENABLE_TELEMETRY=True,
            MONITORING_PROVIDER="local_file",
            TRAJECTORY_CLEANUP_ENABLED=False,
        ),
        lambda: None,
    )
    maintenance = processor._maintenance_store
    identity = CaptureIdentity("tenant", "owner", "1", None)
    writer = maintenance.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents")
    writer.close()
    processor._maintain()
    run = maintenance.manifest(identity)["runs"][0]
    assert run["business_status"] == "interrupted"
    assert run["capture_state"] == "incomplete"
    assert run["file_deleted_at"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"TRAJECTORY_RETENTION_DAYS": 0},
        {"TRAJECTORY_RETENTION_DAYS": 3651},
        {"TRAJECTORY_CLEANUP_INTERVAL_SECONDS": 59},
        {"TRAJECTORY_FLUSH_INTERVAL_MS": 0},
        {"TRAJECTORY_RUN_QUEUE_MAX_BYTES": 300_000_000},
    ],
)
def test_invalid_storage_configuration_fails_before_service_start(tmp_path, overrides):
    TrajectoryFileStore.provision(tmp_path)
    with pytest.raises(ValueError):
        create_local_processor(configuration(tmp_path, **overrides), lambda: None)


def test_read_only_maintenance_initializes_persistent_directory(tmp_path):
    root = tmp_path / "trajectory"
    processor = create_local_processor(configuration(root), lambda: None)
    assert processor.store.root == root
    assert (root / ".storage-root.json").exists()


@pytest.mark.parametrize(
    "member,conversation,allowed",
    [
        ({"delete_flag": "N"}, {"created_by": "owner"}, True),
        (None, {"created_by": "owner"}, False),
        ({"delete_flag": "Y"}, {"created_by": "owner"}, False),
        ({"delete_flag": "N"}, None, False),
        ({"delete_flag": "N"}, {"created_by": "other"}, False),
    ],
)
def test_capture_authorization_requires_active_membership_and_actual_owner(monkeypatch, member, conversation, allowed):
    membership = Mock(return_value=member)
    lookup = Mock(return_value=conversation)
    monkeypatch.setitem(
        sys.modules,
        "management.db.identity.user_tenant",
        SimpleNamespace(get_user_tenant_in_tenant=membership),
    )
    monkeypatch.setitem(
        sys.modules,
        "management.db.conversation.repository",
        SimpleNamespace(get_conversation=lookup),
    )
    identity = CaptureIdentity("tenant", "owner", "123", "42")
    if allowed:
        authorize_capture(identity)
    else:
        with pytest.raises(PermissionError):
            authorize_capture(identity)
    membership.assert_called_once_with("owner", "tenant")
    if member and member.get("delete_flag") == "N":
        lookup.assert_called_once_with(123, user_id="owner", tenant_id="tenant")
    else:
        lookup.assert_not_called()


def test_deleted_conversation_reclamation_uses_confirmed_pg_result(tmp_path, caplog):
    TrajectoryFileStore.provision(tmp_path)
    processor = create_local_processor(configuration(tmp_path), lambda: None)
    maintenance = processor._maintenance_store
    identity = CaptureIdentity("tenant", "owner", "1", "42")
    with maintenance.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")
    processor.deleted_conversation_check = Mock(side_effect=ConnectionError("PG unavailable"))
    with pytest.raises(ConnectionError):
        processor._maintain()
    event, = [json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
              for record in caplog.records if record.getMessage().startswith("trajectory.cleanup ")]
    assert event["source"] == "scheduled" and event["status"] == "failed"
    assert event["error_code"] == "storage_unavailable" and not event["counts_complete"]
    assert "PG unavailable" not in caplog.text
    assert maintenance.manifest(identity)["runs"][0]["cleanup_reason"] is None
    processor._maintenance_iterator = None
    processor.deleted_conversation_check = Mock(return_value=True)
    processor._maintain()
    run = maintenance.manifest(identity)["runs"][0]
    assert run["cleanup_reason"] == "conversation_deleted" and run["file_deleted_at"] is not None


@pytest.mark.parametrize("elapsed", [2.0, 2.1])
def test_scheduled_cleanup_yields_after_work_budget_and_retries_remaining(
    tmp_path, monkeypatch, caplog, elapsed,
):
    caplog.set_level(logging.INFO)
    TrajectoryFileStore.provision(tmp_path)
    processor = create_local_processor(configuration(tmp_path), lambda: None)
    store = processor._maintenance_store
    identity = CaptureIdentity("tenant", "owner", "1", "42")
    now = datetime(2026, 11, 1, tzinfo=UTC)
    store.clock = lambda: now
    expired = []
    for _ in range(3):
        with store.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents") as writer:
            writer.finish("completed")
            expired.append(writer.trajectory_id)
    now += timedelta(days=30)
    with store.start(identity, str(uuid4()), str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")
        fresh = writer.trajectory_id
    directory = tmp_path / "tenant/owner/42/1"
    ticker = [10000.0]
    unlink = os.unlink

    def slow_unlink(path, **kwargs):
        unlink(path, **kwargs)
        if str(path).endswith(".otlp.jsonl"):
            ticker[0] += elapsed

    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.monotonic", lambda: ticker[0])
    monkeypatch.setattr("infrastructure.observability.trajectory_store.os.unlink", slow_unlink)
    processor._maintain()
    assert sum((directory / f"{run}.otlp.jsonl").exists() for run in expired) == 2
    pending = [run for run in store.manifest(identity)["runs"] if run["trajectory_id"] in expired]
    assert all(run["cleanup_reason"] == "retention" for run in pending)
    assert sum(run["file_deleted_at"] is None for run in pending) == 2
    assert (directory / f"{fresh}.otlp.jsonl").exists()
    for _ in range(2):
        processor._maintain()
        ticker[0] += 3601
        processor._maintain()
    assert not any((directory / f"{run}.otlp.jsonl").exists() for run in expired)
    assert (directory / f"{fresh}.otlp.jsonl").exists()
    events = [json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
              for record in caplog.records if record.getMessage().startswith("trajectory.cleanup ")]
    assert [event["deleted_runs"] for event in events] == [1, 1, 1]
    assert [event["pending_runs"] for event in events] == [2, 1, 0]
    assert all(event["failed_runs"] == 0 and event["counts_complete"] for event in events)


def test_local_provider_keeps_deletion_worker_when_capture_reads_and_retention_are_disabled(tmp_path):
    config = configuration(
        tmp_path, MONITORING_PROVIDER="local_file", TRAJECTORY_READ_ENABLED=False,
    )
    assert not config.ENABLE_TELEMETRY
    assert create_local_processor(config, lambda: None) is not None
    config.TRAJECTORY_CLEANUP_ENABLED = False
    assert create_local_processor(config, lambda: None) is not None


@pytest.mark.parametrize("present", [True, False])
def test_deletion_handoff_uses_lifespan_owned_processor(monkeypatch, present):
    from contracts.constants import environment as config

    monkeypatch.setattr(config, "MONITORING_PROVIDER", "local_file")
    processor = SimpleNamespace(request_conversation_cleanup=Mock(return_value=True)) if present else None
    monkeypatch.setitem(sys.modules, "infrastructure.observability.bootstrap", SimpleNamespace(
        local_trajectory_processor=processor,
    ))
    assert request_conversation_cleanup([123], "owner") is present
    if processor:
        processor.request_conversation_cleanup.assert_called_once_with([123], "owner")
