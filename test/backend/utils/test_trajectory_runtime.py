# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backend configuration, maintenance and trusted authorization boundaries."""

import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_runtime import (
    authorize_capture,
    create_local_processor,
)
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)


def configuration(root="", root_id="", **overrides):
    values = {
        "ENABLE_TELEMETRY": False,
        "MONITORING_TRACE_SINK": "otlp",
        "TRAJECTORY_ROOT_DIR": str(root),
        "TRAJECTORY_STORAGE_ROOT_ID": root_id,
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


def test_cleanup_is_independent_of_telemetry_and_active_capture(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    processor = create_local_processor(configuration(tmp_path, root_id), lambda: None)
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
    finally:
        active.close()


def test_startup_recovery_seals_orphan_even_when_cleanup_disabled(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    processor = create_local_processor(
        configuration(
            tmp_path,
            root_id,
            ENABLE_TELEMETRY=True,
            MONITORING_TRACE_SINK="local_file",
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
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    with pytest.raises(ValueError):
        create_local_processor(configuration(tmp_path, root_id, **overrides), lambda: None)


def test_provisioned_mount_is_required(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_local_processor(configuration(tmp_path, str(uuid4())), lambda: None)


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
        sys.modules, "management.db.identity.user_tenant", SimpleNamespace(get_user_tenant_in_tenant=membership)
    )
    monkeypatch.setitem(sys.modules, "management.db.conversation.repository", SimpleNamespace(get_conversation=lookup))
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
