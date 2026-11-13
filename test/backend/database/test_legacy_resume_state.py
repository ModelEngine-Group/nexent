# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from infrastructure.rdb import conversation_state


@pytest.fixture
def resume_db(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
        for ddl in (
            "CREATE TABLE nexent.user_account_t (user_id TEXT, user_role TEXT, delete_flag TEXT)",
            "CREATE TABLE nexent.user_tenant_t (user_id TEXT, tenant_id TEXT, delete_flag TEXT)",
            "CREATE TABLE nexent.conversation_record_t "
            "(conversation_id INTEGER, created_by TEXT, delete_flag TEXT, workbench_config TEXT)",
            "CREATE TABLE nexent.conversation_message_t "
            "(message_id INTEGER, conversation_id INTEGER, message_index INTEGER, message_role TEXT, status TEXT, delete_flag TEXT)",
            "CREATE TABLE nexent.conversation_message_unit_t "
            "(message_id INTEGER, unit_index INTEGER, delete_flag TEXT)",
        ):
            connection.exec_driver_sql(ddl)
        connection.exec_driver_sql("INSERT INTO nexent.user_tenant_t VALUES ('owner', 'tenant', 'N'), ('other', 'tenant', 'N')")
        connection.exec_driver_sql("INSERT INTO nexent.conversation_record_t VALUES (42, 'owner', 'N', NULL)")
        connection.exec_driver_sql(
            "INSERT INTO nexent.conversation_message_t VALUES "
            "(1, 42, 1, 'assistant', 'completed', 'N'), (2, 42, 2, 'assistant', 'streaming', 'N'), "
            "(3, 42, 3, 'assistant', 'failed', 'Y'), (4, 42, 4, 'user', 'completed', 'N')"
        )
        connection.exec_driver_sql(
            "INSERT INTO nexent.conversation_message_unit_t VALUES (1, 99, 'N'), (2, 4, 'N'), (2, 9, 'Y')"
        )

    @contextmanager
    def session():
        with Session(engine) as current:
            yield current

    monkeypatch.setattr(conversation_state, "get_db_session", session)
    yield
    engine.dispose()


def test_legacy_resume_state_reads_latest_live_assistant_and_unit(resume_db):
    assert conversation_state.read_legacy_resume_state(42, "owner", "tenant") == (False, ("streaming", 4))


@pytest.mark.parametrize("user,tenant", [("owner", "foreign"), ("other", "tenant")])
def test_legacy_resume_state_rejects_wrong_user_or_tenant(resume_db, user, tenant):
    with pytest.raises(PermissionError):
        conversation_state.read_legacy_resume_state(42, user, tenant)
