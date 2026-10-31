# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned conversation locks precede assistant/cascade message writes."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.conversation import repository as db


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()
    value.scalar.return_value = 1
    value.execute.return_value.scalar_one_or_none.return_value = MagicMock(status="streaming", minio_files=None)

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    return value


def finalize():
    return db.persist_assistant_run_batch(
        message_id=10, conversation_id=1, message_content="answer",
        terminal_status="completed", message_units=[], search_records=[],
        image_urls=[], skill_files=[], automation_proposals=[],
        user_id="owner", tenant_id="tenant",
    )


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_finalization_locks_owned_live_conversation_before_message(session):
    finalize()

    calls = session.method_calls
    assert calls[0][0] == "scalar"
    conversation = sql(calls[0].args[0])
    assert "conversation_record_t" in conversation and "FOR UPDATE" in conversation
    assert "conversation_id = 1" in conversation
    assert "created_by = 'owner'" in conversation and "delete_flag = 'N'" in conversation
    message = sql(session.execute.call_args_list[0].args[0])
    assert "conversation_message_t" in message and "FOR UPDATE" in message
    assert "message_id = 10" in message and "conversation_id = 1" in message
    assert "UPDATE nexent.conversation_record_t" in sql(session.execute.call_args_list[-1].args[0])


def test_finalization_rejects_inaccessible_conversation_before_any_message_write(session):
    session.scalar.return_value = None

    with pytest.raises(ValueError, match="Conversation does not exist or is not accessible"):
        finalize()

    session.execute.assert_not_called()


def test_batch_delete_locks_owned_live_conversations_in_id_order_before_updates(session):
    session.execute.return_value.all.return_value = [(1,), (2,)]

    assert db.delete_conversations_batch([2, 1, 2, 999], "owner") == [1, 2]

    statements = [call.args[0] for call in session.execute.call_args_list]
    locked = sql(statements[0])
    assert "ORDER BY nexent.conversation_record_t.conversation_id ASC FOR UPDATE" in locked
    assert "created_by = 'owner'" in locked and "delete_flag = 'N'" in locked
    assert "UPDATE nexent.conversation_record_t" in sql(statements[1])
    assert "UPDATE nexent.conversation_message_t" in sql(statements[2])
    assert len(statements) == 6
