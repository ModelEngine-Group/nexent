# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit proof of task-before-run locking and owner filters, without a database."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.automation import repository


@pytest.mark.parametrize("task_present,run_id,run_present", [
    (False, 77, False), (True, None, False), (True, 77, False), (True, 77, True),
])
def test_task_run_transaction_locks_owned_rows_in_order(monkeypatch, task_present, run_id, run_present):
    task = {"task_id": 2} if task_present else None
    run = {"run_id": 77} if run_present else None
    session = Mock()
    session.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=row)) for row in [task, run]]
    events = []

    @contextmanager
    def session_scope():
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    monkeypatch.setattr(repository, "get_db_session", session_scope)
    monkeypatch.setattr(repository, "as_dict", lambda row: dict(row))
    with repository.task_run_transaction(2, "tenant", "owner", run_id) as result:
        assert events == ["enter"]
        assert result == (session, task, run if task_present and run_id is not None else None)
    assert events == ["enter", "exit"]
    calls = session.execute.call_args_list
    assert len(calls) == (2 if task_present and run_id is not None else 1)
    for position, call in enumerate(calls):
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.endswith("FOR UPDATE")
        assert compiled.params["tenant_id_1"] == "tenant"
        assert compiled.params["user_id_1"] == "owner"
        assert compiled.params["delete_flag_1"] == "N"
        assert compiled.params["task_id_1"] == 2
        if position == 0:
            assert "FROM nexent.agent_automation_task_t" in sql
        else:
            assert "FROM nexent.agent_automation_run_t" in sql
            assert compiled.params["run_id_1"] == 77
