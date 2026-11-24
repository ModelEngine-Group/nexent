# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""File retention preserves the independently persisted execution facts."""

import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([("expired", 100)], 100),
        ([("success", 20), ("expired", 100)], 120),
        ([("expired", 0)], 0),
        ([("success", 20), ("expired", None)], None),
        ([("expired", 100), ("partial", None)], None),
        ([("unarchived", None), ("expired", 100)], 100),
        ([("not_captured", None)], None),
        ([], None),
    ],
)
@pytest.mark.parametrize(
    "column", ["duration_ms", "input_tokens", "output_tokens", "total_tokens"]
)
def test_strict_aggregate_keeps_cleaned_metrics_and_actual_unknowns(
    rows, expected, column
):
    from ops.db.trajectory.queries import strict_sum

    # SQLite executes the shared SQL aggregate without a live PostgreSQL dependency.
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE facts (status TEXT, {column} REAL)")
        connection.executemany("INSERT INTO facts VALUES (?, ?)", rows)
        result = connection.execute(
            f"SELECT {strict_sum(column)} FROM facts"
        ).fetchone()[0]
        assert result == expected
    finally:
        connection.close()


def test_expiry_compensation_keeps_existing_metrics_and_metadata(mocker):
    from infrastructure.rdb.trajectory.repository import ExecutionRepository

    row = SimpleNamespace(
        trajectory_id="run",
        conversation_id=123,
        created_by="u",
        delete_flag="N",
        turn_no=2,
        status="success",
        duration_ms=1234,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        models=["model"],
        agent_version_no=2,
    )
    session = Mock()
    session.get.return_value = row
    mocker.patch(
        "infrastructure.rdb.trajectory.repository.get_db_session",
        side_effect=lambda: nullcontext(session),
    )
    mocker.patch.object(ExecutionRepository, "_owner", return_value=object())
    mocker.patch("infrastructure.rdb.trajectory.repository.dirty")
    ExecutionRepository().sync(
        SimpleNamespace(conversation_id="123", owner_user_id="u", tenant_id="t"),
        {
            "trajectory_id": "run",
            "status": "expired",
            "turn_no": 2,
            "duration_ms": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "models": [],
            "agent_version_no": None,
        },
    )
    params = session.execute.call_args_list[0].args[0].compile().params
    assert params["status"] == "expired"
    assert not set(params).intersection(
        {
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "models",
            "agent_version_no",
        }
    )
    session.add.assert_not_called()


def test_expire_only_updates_availability_and_audit_fields(mocker):
    from infrastructure.rdb.trajectory.repository import ExecutionRepository

    session = Mock()
    session.execute.return_value.rowcount = 1
    mocker.patch(
        "infrastructure.rdb.trajectory.repository.get_db_session",
        side_effect=lambda: nullcontext(session),
    )
    dirty = mocker.patch("infrastructure.rdb.trajectory.repository.dirty")
    owner = SimpleNamespace(conversation_id="123", owner_user_id="u", tenant_id="t")
    ExecutionRepository().expire(owner, ["run"])
    params = session.execute.call_args.args[0].compile().params
    assert params["status"] == "expired" and "delete_flag" not in params
    assert not set(params).intersection(
        {"duration_ms", "input_tokens", "output_tokens", "total_tokens"}
    )
    dirty.assert_called_once_with(session, "t")


def test_compaction_only_reclaims_soft_deleted_rows(mocker):
    from infrastructure.rdb.trajectory.repository import ExecutionRepository

    session = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    mocker.patch(
        "infrastructure.rdb.trajectory.repository.get_db_session",
        side_effect=lambda: nullcontext(session),
    )
    assert ExecutionRepository().compact() == 0
    sql = str(session.execute.call_args.args[0])
    assert "e.delete_flag='Y'" in sql
    assert "e.status='expired'" not in sql
    assert "LIMIT :limit" in sql
