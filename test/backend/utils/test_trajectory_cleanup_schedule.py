# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Daily tenant retention uses Beijing midnight without interrupting maintenance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.trace.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)


@pytest.fixture
def processor(mocker):
    ticker = [100.0]
    wall = [datetime(2026, 11, 1, 15, 59, 59, tzinfo=UTC)]
    mocker.patch(
        "infrastructure.trace.trajectory_processor.time.monotonic",
        side_effect=lambda: ticker[0],
    )
    identity = CaptureIdentity("tenant", "owner", "123", "7")
    store = Mock(retention_days=30)
    store.clock.side_effect = lambda: wall[0]
    store.identities.side_effect = lambda **_: iter([identity])
    store.manifest.return_value = {"runs": []}
    store.cleanup.return_value = {"next_turn": None}
    provider = Mock(return_value={"tenant": {"enabled": True, "retention_days": 7}})
    worker = LocalTrajectoryProcessor(
        Mock(),
        lambda: None,
        maintenance_store=store,
        cleanup_policy_provider=provider,
        cleanup_enabled=False,
    )
    return worker, provider, store, ticker, wall


def test_startup_maintains_and_waits_for_beijing_midnight(processor):
    worker, provider, store, _ticker, wall = processor
    worker._maintain()
    store.reconcile.assert_called_once()
    store.cleanup.assert_not_called()
    assert worker._next_cleanup_at == datetime(2026, 11, 1, 16, tzinfo=UTC)
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    call = store.cleanup.call_args.kwargs
    assert call["before_days"] == 7 and call["scheduled"] is True
    assert call["cutoff_at"] == datetime(2026, 10, 25, 16, tzinfo=UTC)
    assert worker._next_cleanup_at == datetime(2026, 11, 2, 16, tzinfo=UTC)
    worker._maintain()
    assert store.cleanup.call_count == 1
    assert provider.call_count == 1


def test_policy_refreshes_every_30_seconds_and_disable_stops_next_delete(processor):
    worker, provider, store, ticker, wall = processor
    worker._maintain()
    provider.return_value = {"tenant": {"enabled": False, "retention_days": 1}}
    ticker[0] = 129
    worker._maintain()
    assert provider.call_count == 1
    ticker[0] = 130
    worker._maintain()
    assert provider.call_count == 2
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    store.cleanup.assert_not_called()
    assert store.reconcile.call_count == 2


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {"enabled": 1, "retention_days": 7},
        {"enabled": True, "retention_days": 31},
        {"enabled": True, "retention_days": 0},
        {"enabled": True, "retention_days": "7"},
    ],
)
def test_invalid_refresh_retains_last_successful_policy(processor, invalid):
    worker, provider, store, ticker, wall = processor
    worker._maintain()
    provider.return_value = {"tenant": invalid}
    ticker[0] = 130
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    assert store.cleanup.call_args.kwargs["before_days"] == 7


def test_failed_first_refresh_only_maintains_and_does_not_use_default(
    processor, caplog
):
    worker, provider, store, ticker, wall = processor
    worker._cleanup_enabled = True
    provider.side_effect = ConnectionError("private connection string")
    worker._maintain()
    wall[0] += timedelta(seconds=1)
    ticker[0] = 130
    worker._maintain()
    store.cleanup.assert_not_called()
    assert "private connection" not in caplog.text
    provider.side_effect = None
    ticker[0] = 160
    worker._maintain()
    assert worker._next_cleanup_at == datetime(2026, 11, 2, 16, tzinfo=UTC)
    store.cleanup.assert_not_called()


def test_disabled_tenant_still_cleans_deleted_conversations(processor):
    worker, provider, store, _, _ = processor
    provider.return_value = {"tenant": {"enabled": False, "retention_days": 1}}
    worker.deleted_conversation_check = lambda _: True
    worker._maintain()
    assert store.cleanup.call_args.kwargs["force_reason"] == "conversation_deleted"


def test_batch_scan_freezes_cutoff_and_retention_days(processor):
    worker, provider, store, ticker, wall = processor
    worker._maintain()
    identities = [
        CaptureIdentity("tenant", "owner", str(1000 + n), "7") for n in range(21)
    ]
    store.identities.side_effect = lambda **_: iter(identities)
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    assert store.cleanup.call_count == 20
    provider.return_value = {"tenant": {"enabled": True, "retention_days": 1}}
    ticker[0] = 130
    wall[0] += timedelta(hours=1)
    worker._maintain()
    assert store.cleanup.call_count == 21
    assert {c.kwargs["before_days"] for c in store.cleanup.call_args_list} == {7}
    assert len({c.kwargs["cutoff_at"] for c in store.cleanup.call_args_list}) == 1


def test_disable_during_batch_stops_remaining_deletions(processor):
    worker, provider, store, ticker, wall = processor
    worker._maintain()
    store.identities.side_effect = lambda **_: iter(
        [CaptureIdentity("tenant", "owner", str(1000 + n), "7") for n in range(21)]
    )
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    provider.return_value = {"tenant": {"enabled": False, "retention_days": 7}}
    ticker[0] = 130
    worker._maintain()
    assert store.cleanup.call_count == 20
    assert worker._maintenance_iterator is None


def test_next_day_uses_updated_policy_without_immediate_rescan(processor):
    worker, provider, store, ticker, wall = processor
    worker._maintain()
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    provider.return_value = {"tenant": {"enabled": True, "retention_days": 1}}
    ticker[0] = 130
    worker._maintain()
    assert store.cleanup.call_count == 1
    wall[0] += timedelta(days=1)
    worker._maintain()
    assert store.cleanup.call_count == 2
    assert store.cleanup.call_args.kwargs["before_days"] == 1


def test_real_files_use_independent_tenant_days_and_retention_reason(tmp_path):
    wall = [datetime(2026, 10, 20, 16, tzinfo=UTC)]
    store = TrajectoryFileStore(
        tmp_path, authorize=lambda _: None, clock=lambda: wall[0]
    )
    owners = [
        CaptureIdentity(tenant, "owner", str(100 + i), "7")
        for i, tenant in enumerate(["fast", "slow", "off"])
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
        cleanup_policy_provider=lambda: {
            "fast": {"enabled": True, "retention_days": 7},
            "slow": {"enabled": True, "retention_days": 30},
            "off": {"enabled": False, "retention_days": 1},
        },
    )
    wall[0] = datetime(2026, 11, 1, 15, 59, 59, tzinfo=UTC)
    worker._maintain()
    assert all(store.manifest(i)["runs"][0]["file_deleted_at"] is None for i in owners)
    wall[0] += timedelta(seconds=1)
    worker._maintain()
    meta = store.manifest(owners[0])
    assert meta["runs"][0]["file_deleted_at"] is not None
    assert meta["runs"][0]["cleanup_reason"] == "retention"
    assert not meta["had_manual_cleanup"]
    assert all(
        store.manifest(i)["runs"][0]["file_deleted_at"] is None for i in owners[1:]
    )


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


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 11, 1, 16, tzinfo=UTC), datetime(2026, 11, 2, 16, tzinfo=UTC)),
        (
            datetime(2026, 12, 31, 15, 59, 59, tzinfo=UTC),
            datetime(2026, 12, 31, 16, tzinfo=UTC),
        ),
        (datetime(2026, 12, 31, 16, tzinfo=UTC), datetime(2027, 1, 1, 16, tzinfo=UTC)),
    ],
)
def test_next_midnight_uses_beijing_day_and_handles_year_boundary(now, expected):
    assert LocalTrajectoryProcessor._next_midnight(now) == expected
