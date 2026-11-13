# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Dynamic scheduling preserves maintenance work and the last valid configuration."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)


@pytest.fixture
def processor(mocker):
    clock = [100.0]
    mocker.patch(
        "infrastructure.observability.trajectory_processor.time.monotonic",
        side_effect=lambda: clock[0],
    )
    store = Mock()
    store.identities.side_effect = lambda **_: iter([])
    provider = Mock(return_value={"tenant": 3600})
    worker = LocalTrajectoryProcessor(
        Mock(),
        lambda: None,
        maintenance_store=store,
        cleanup_interval_provider=provider,
        cleanup_enabled=True,
    )
    return worker, provider, store, clock


def test_interval_is_polled_every_30_seconds_and_startup_still_scans(processor):
    worker, provider, store, clock = processor
    worker._maintain()
    assert provider.call_count == 1 and store.identities.call_count == 1
    assert worker._next_maintenance == 3700
    clock[0] = 129
    worker._maintain()
    assert provider.call_count == 1
    clock[0] = 130
    worker._maintain()
    assert provider.call_count == 2 and store.identities.call_count == 1


def test_shorter_interval_can_make_next_scan_due_immediately(processor):
    worker, provider, store, clock = processor
    worker._maintain()
    provider.return_value = {"tenant": 60}
    clock[0] = 200
    worker._maintain()
    assert store.identities.call_count == 2
    assert worker._cleanup_intervals["tenant"] == 60 and worker._next_maintenance == 260


def test_longer_interval_reschedules_from_last_finished_scan(processor):
    worker, provider, store, clock = processor
    worker._maintain()
    provider.return_value = {"tenant": 7200}
    clock[0] = 3700
    worker._maintain()
    assert worker._tenant_last_maintenance["tenant"] == 100
    assert worker._next_maintenance == 7300
    assert store.identities.call_count == 2


@pytest.mark.parametrize("invalid", [59, 31536001, True, "60", None])
def test_bad_configuration_keeps_previous_interval_and_retries(processor, invalid):
    worker, provider, _, clock = processor
    worker._maintain()
    provider.return_value = {"tenant": invalid}
    clock[0] = 130
    worker._maintain()
    assert worker._cleanup_interval == 3600
    assert worker._cleanup_intervals == {"tenant": 3600}
    provider.return_value = {"tenant": 120}
    clock[0] = 160
    worker._maintain()
    assert (
        worker._cleanup_intervals["tenant"] == 120 and worker._next_maintenance == 220
    )


def test_failed_config_refresh_does_not_skip_maintenance_or_disclose_error(
    processor, caplog
):
    worker, provider, store, clock = processor
    provider.side_effect = ConnectionError("private connection string")
    worker._maintain()
    assert store.identities.call_count == 1 and worker._cleanup_interval == 3600
    assert "private connection" not in caplog.text
    provider.side_effect = None
    provider.return_value = {"tenant": 60}
    clock[0] = 130
    worker._maintain()
    assert worker._next_maintenance == 190


def test_change_does_not_abandon_an_in_progress_scan(processor):
    worker, provider, store, clock = processor
    worker._maintain()
    pending = iter([])
    worker._maintenance_iterator = pending
    worker._queue.put("occupied")
    provider.return_value = {"tenant": 120}
    clock[0] = 130
    worker._maintain()
    assert worker._maintenance_iterator is pending
    worker._queue.get_nowait()
    worker._maintain()
    assert worker._next_maintenance == 250 and store.identities.call_count == 1


def test_refresh_failure_preserves_previously_saved_tenant_intervals(processor):
    worker, provider, store, clock = processor
    provider.return_value = {"tenant": 60}
    worker._maintain()
    provider.side_effect = ConnectionError("offline")
    clock[0] = 160
    worker._maintain()
    assert worker._cleanup_intervals == {"tenant": 60}
    assert worker._next_maintenance == 220
    store.identities.assert_called_with(tenant_ids={"tenant"})


def test_tenants_use_independent_deadlines_and_scans(processor):
    worker, provider, store, clock = processor
    provider.return_value = {"tenant": 60, "other": 7200}
    worker._maintain()
    assert worker._tenant_last_maintenance == {"tenant": 100, "other": 100}
    clock[0] = 160
    worker._maintain()
    store.identities.assert_called_with(tenant_ids={"tenant"})
    assert worker._tenant_last_maintenance == {"tenant": 160, "other": 100}
    # The periodic full scan does not move a tenant's later retention deadline.
    clock[0] = 3700
    worker._maintain()
    assert worker._tenant_last_maintenance == {"tenant": 3700, "other": 100}
    clock[0] = 7300
    worker._maintain()
    assert worker._tenant_last_maintenance["other"] == 7300


def test_disabled_retention_keeps_default_maintenance_schedule(processor):
    worker, provider, store, clock = processor
    worker._cleanup_enabled = False
    provider.return_value = {"tenant": 60}
    worker._maintain()
    clock[0] = 200
    worker._maintain()
    assert store.identities.call_count == 1 and worker._next_maintenance == 3700


def test_due_tenant_cleanup_leaves_other_tenant_files_untouched(tmp_path, mocker):
    ticker = [100.0]
    clock = [datetime(2026, 11, 1, tzinfo=UTC)]
    mocker.patch(
        "infrastructure.observability.trajectory_processor.time.monotonic",
        side_effect=lambda: ticker[0],
    )
    store = TrajectoryFileStore(
        tmp_path, authorize=lambda _: None, clock=lambda: clock[0]
    )
    owners = [
        CaptureIdentity(tenant, "owner", str(123 + index), "7")
        for index, tenant in enumerate(["fast", "slow"])
    ]
    for identity in owners:
        with store.start(
            identity, str(uuid4()), str(uuid4()), core_type="smolagents"
        ) as writer:
            writer.finish("completed")
    worker = LocalTrajectoryProcessor(
        store,
        lambda: None,
        maintenance_store=store,
        cleanup_enabled=True,
        cleanup_interval_provider=lambda: {"fast": 60, "slow": 7200},
    )
    worker._maintain()
    clock[0] += timedelta(days=31)
    ticker[0] = 160
    worker._maintain()
    assert store.manifest(owners[0])["runs"][0]["file_deleted_at"] is not None
    assert store.manifest(owners[1])["runs"][0]["file_deleted_at"] is None
    # A default full maintenance scan must also respect the slow tenant's deadline.
    ticker[0] = 3700
    worker._maintain()
    assert store.manifest(owners[1])["runs"][0]["file_deleted_at"] is None
    ticker[0] = 7300
    worker._maintain()
    assert store.manifest(owners[1])["runs"][0]["file_deleted_at"] is not None


def test_tenant_directory_filter_avoids_opening_other_tenants(tmp_path, mocker):
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    for index, tenant in enumerate(["selected", "other"]):
        with store.start(
            CaptureIdentity(tenant, "owner", str(123 + index), "7"),
            str(uuid4()),
            str(uuid4()),
            core_type="smolagents",
        ) as writer:
            writer.finish("completed")
    validate = mocker.patch.object(
        store, "_validate_manifest", wraps=store._validate_manifest
    )
    assert [
        i.tenant_id for i in store.identities(tenant_ids={"selected", "missing"})
    ] == ["selected"]
    assert validate.call_count == 1
