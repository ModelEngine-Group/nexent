# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant cleanup settings validation, authorization and persistence boundaries."""

import pytest
from contracts.trajectory import CleanupScheduleRequest
from ops.services.trajectory import cleanup_schedule as schedule
from ops.services.trajectory.access import Actor
from ops.services.trajectory.primitives import QueryError
from pydantic import ValidationError


@pytest.fixture
def repository(mocker):
    catalog = mocker.patch.object(schedule, "TrajectoryCatalog").return_value
    catalog.actor_active.return_value = True
    catalog.tenants.side_effect = lambda actor: (
        ["tenant", "other"] if actor.role == "SU" else [actor.tenant_id]
    )
    return mocker.patch.object(schedule, "CleanupScheduleRepository").return_value


@pytest.mark.parametrize("value", [60, 3600, 31536000])
def test_schedule_accepts_seconds_and_persists_actual_actor(repository, value):
    actor = Actor("operator", "tenant", "SU")
    request = CleanupScheduleRequest(interval_seconds=value)
    result = schedule.save_schedule(actor, request.interval_seconds)
    repository.save.assert_called_once_with("tenant", value, "operator")
    assert result["interval_seconds"] == value


@pytest.mark.parametrize("value", [59, 0, -1, 31536001, 60.5, "60", True, None])
def test_schedule_rejects_non_integer_and_out_of_bounds_values(value):
    with pytest.raises(ValidationError):
        CleanupScheduleRequest(interval_seconds=value)


def test_schedule_forbids_scope_or_policy_injection():
    with pytest.raises(ValidationError):
        CleanupScheduleRequest(interval_seconds=60, enabled=True)


@pytest.mark.parametrize("role", ["USER", "DEV", "SPEED"])
def test_only_administrators_can_read_or_write_schedule(repository, role):
    actor = Actor("actor", "tenant", role)
    for operation in [
        lambda: schedule.read_schedule(actor),
        lambda: schedule.save_schedule(actor, 60),
    ]:
        with pytest.raises(QueryError) as raised:
            operation()
        assert raised.value.status == 403
    repository.read.assert_not_called()
    repository.save.assert_not_called()


def test_revoked_su_cannot_change_schedule(repository):
    schedule.TrajectoryCatalog.return_value.actor_active.return_value = False
    with pytest.raises(QueryError) as raised:
        schedule.save_schedule(Actor("operator", "tenant", "SU"), 60)
    assert raised.value.status == 403
    repository.save.assert_not_called()


def test_schedule_reads_default_and_reports_deployment_policy(repository, mocker):
    mocker.patch.object(schedule.config, "TRAJECTORY_CLEANUP_INTERVAL_SECONDS", 7200)
    mocker.patch.object(schedule.config, "TRAJECTORY_CLEANUP_ENABLED", False)
    mocker.patch.object(schedule.config, "TRAJECTORY_RETENTION_DAYS", 30)
    repository.read.return_value = None
    assert schedule.read_schedule(Actor("operator", "tenant", "SU")) == {
        "tenant_id": "tenant",
        "interval_seconds": 7200,
        "enabled": False,
        "retention_days": 30,
    }
    repository.read.return_value = 120
    assert (
        schedule.read_schedule(Actor("operator", "tenant", "SU"))["interval_seconds"]
        == 120
    )


def test_schedule_storage_failure_is_not_reported_as_success(repository):
    repository.save.side_effect = ConnectionError("unavailable")
    with pytest.raises(ConnectionError):
        schedule.save_schedule(Actor("operator", "tenant", "SU"), 60)


def test_invalid_stored_policy_is_unavailable_instead_of_a_bad_request(repository):
    repository.read.side_effect = ValueError("bad stored policy")
    with pytest.raises(QueryError) as raised:
        schedule.read_schedule(Actor("admin", "tenant", "ADMIN"))
    assert raised.value.status == 503


def test_dynamic_interval_reader_batches_all_tenants(repository):
    repository.read_all.return_value = {"tenant": 60, "other": 120}
    assert schedule.read_intervals() == {"tenant": 60, "other": 120}
    repository.read_all.assert_called_once_with()
    repository.read.assert_not_called()
    repository.read_all.side_effect = ConnectionError("unavailable")
    with pytest.raises(ConnectionError):
        schedule.read_intervals()


def test_admin_updates_own_tenant_and_cannot_override_scope(repository):
    actor = Actor("admin", "tenant", "ADMIN")
    assert schedule.save_schedule(actor, 120)["tenant_id"] == "tenant"
    repository.save.assert_called_once_with("tenant", 120, "admin")
    for operation in [
        lambda: schedule.read_schedule(actor, "other"),
        lambda: schedule.save_schedule(actor, 60, "other"),
    ]:
        with pytest.raises(QueryError) as raised:
            operation()
        assert raised.value.status == 404
    assert repository.save.call_count == 1


def test_su_can_configure_only_authorized_tenants(repository):
    actor = Actor("operator", "tenant", "SU")
    assert schedule.save_schedule(actor, 120, "other")["tenant_id"] == "other"
    repository.save.assert_called_once_with("other", 120, "operator")
    with pytest.raises(QueryError) as raised:
        schedule.read_schedule(actor, "unknown")
    assert raised.value.status == 404
