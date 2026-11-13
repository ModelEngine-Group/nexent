# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Existing tenant configuration rows are saved under a transaction-scoped lock."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.db.trajectory import cleanup_schedule as database


@pytest.fixture
def session(mocker):
    session = Mock()
    session.scalars.return_value.first.return_value = None
    mocker.patch.object(
        database, "get_db_session", side_effect=lambda: nullcontext(session)
    )
    return session


def test_first_save_locks_tenant_key_before_insert_and_stamps_actor(session):
    database.CleanupScheduleRepository().save("tenant", 120, "admin")
    assert (
        str(session.execute.call_args_list[0].args[0])
        == "SET LOCAL statement_timeout = '2000ms'"
    )
    lock = session.execute.call_args_list[1]
    assert "pg_advisory_xact_lock" in str(lock.args[0])
    assert lock.args[1] == {"key": f"{database.SCHEDULE_KEY}:tenant"}
    assert [call[0] for call in session.mock_calls].index("execute") < [
        call[0] for call in session.mock_calls
    ].index("add")
    row = session.add.call_args.args[0]
    assert row.tenant_id == "tenant" and row.config_key == database.SCHEDULE_KEY
    assert (
        row.config_value == "120"
        and row.created_by == row.updated_by == row.user_id == "admin"
    )
    assert row.value_type == "single" and row.delete_flag == "N"
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_repeat_save_updates_same_row_and_preserves_creator(session):
    row = SimpleNamespace(created_by="creator", config_value="60")
    session.scalars.return_value.first.return_value = row
    database.CleanupScheduleRepository().save("tenant", 3600, "admin")
    assert row.created_by == "creator" and row.updated_by == row.user_id == "admin"
    assert row.config_value == "3600" and row.update_time is not None
    session.add.assert_not_called()
    statement = session.scalars.call_args.args[0]
    assert "tenant" in statement.compile().params.values()
    assert "N" in statement.compile().params.values()


def test_missing_read_returns_none_and_active_tenant_filter_is_applied(session):
    assert database.CleanupScheduleRepository().read("tenant") is None
    statement = session.scalars.call_args.args[0]
    assert {"tenant", database.SCHEDULE_KEY, "N"}.issubset(
        set(statement.compile().params.values())
    )


def test_batch_read_preserves_each_tenant_and_rejects_invalid_values(session):
    rows = [
        SimpleNamespace(tenant_id="t1", config_value="60"),
        SimpleNamespace(tenant_id="t2", config_value="7200"),
    ]
    session.scalars.return_value.all.return_value = rows
    assert database.CleanupScheduleRepository().read_all() == {"t1": 60, "t2": 7200}
    rows[1].config_value = "bad"
    with pytest.raises(ValueError):
        database.CleanupScheduleRepository().read_all()


def test_db_failure_is_propagated_without_manual_transaction_management(session):
    session.execute.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError):
        database.CleanupScheduleRepository().save("tenant", 60, "admin")
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
