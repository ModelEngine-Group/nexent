# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Transaction ownership and notification ordering with controlled DB boundaries."""

import asyncio
import sys
from contextlib import contextmanager
from types import ModuleType

import pytest

from management.db import repository_transactions as transactions


@pytest.fixture
def database_owner(monkeypatch):
    events = []
    sessions = []

    @contextmanager
    def get_db_session():
        session = object()
        sessions.append(session)
        events.append("begin")
        try:
            yield session
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    module = ModuleType("management.db.client")
    module.get_db_session = get_db_session
    monkeypatch.setitem(sys.modules, "management.db.client", module)
    return events, sessions


def test_nested_scope_reuses_owner_and_delivers_only_after_commit(database_owner):
    events, sessions = database_owner

    @transactions.after_repository_commit
    def notify(value):
        assert transactions.current_repository_session() is None
        events.append(value)

    with transactions.repository_unit_of_work() as first:
        assert transactions.current_repository_session() is first
        with transactions.repository_unit_of_work() as nested:
            assert nested is first
            notify("notification")
        assert events == ["begin"]
    assert len(sessions) == 1
    assert events == ["begin", "commit", "notification"]


def test_failure_discards_notifications_and_clears_scope(database_owner):
    events, _ = database_owner

    @transactions.after_repository_commit
    def notify():
        events.append("notification")

    with pytest.raises(ValueError):
        with transactions.repository_unit_of_work():
            notify()
            raise ValueError("failed write")
    assert events == ["begin", "rollback"]
    assert transactions.current_repository_session() is None


def test_transport_failure_does_not_rollback_committed_write(database_owner):
    events, _ = database_owner

    @transactions.after_repository_commit
    def notify():
        raise OSError("transport unavailable")

    @transactions.repository_transaction
    def write():
        events.append("write")
        notify()
        return "done"

    assert write() == "done"
    assert events == ["begin", "write", "commit"]


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_share_session(database_owner):
    _, sessions = database_owner

    @transactions.repository_transaction
    async def operation():
        first = transactions.current_repository_session()
        await asyncio.sleep(0)
        assert transactions.current_repository_session() is first
        return first

    first, second = await asyncio.gather(operation(), operation())
    assert first is not second
    assert len(sessions) == 2
    assert transactions.current_repository_session() is None
