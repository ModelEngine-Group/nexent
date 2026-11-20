# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep projection receipts tied to the original conversation, run, and message."""

import pytest

from contracts.conversation import MessageSource
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from management.db.conversation import repository
from test.backend.database.test_prepared_saved_user import database
from test.backend.database.test_prepared_turn_resume import add_assistant, add_receipt, receipt_table

RUN_ID = "a" * 32
SCOPE = {
    "projection_run_id": RUN_ID, "conversation_id": 42, "message_index": 1,
    "message_source": MessageSource.CHAT, "user_id": "actor", "tenant_id": "tenant",
}


@pytest.fixture
def projection(database, receipt_table, mocker):
    with database.sessions() as session:
        add_assistant(session, owner="management")
        add_receipt(session, RUN_ID)
    mocker.patch.object(repository, "get_db_session", database.sessions)
    membership = mocker.patch(
        "infrastructure.rdb.conversation_state.tenant_membership_matches",
        side_effect=lambda session, user_id, tenant_id: (user_id, tenant_id) == ("actor", "tenant"),
    )
    lock = mocker.patch.object(repository, "_lock_projection_conversation")
    save = mocker.patch.object(repository, "persist_assistant_run_batch")
    return database.sessions, membership, lock, save


@pytest.mark.parametrize("change", [
    {}, {"tenant_id": "other"}, {"user_id": "other"}, {"conversation_id": 43},
    {"message_index": 3}, {"message_source": MessageSource.AUTOMATION},
])
def test_receipt_lookup_requires_the_exact_scoped_assistant(projection, change):
    assert repository.get_prepared_projection_receipt(**{**SCOPE, **change}) == (
        None if change else (61, "completed")
    )


@pytest.mark.parametrize("change,reason", [
    ({"projection_run_id": "invalid"}, "Invalid assistant projection run ID"),
    ({"tenant_id": "other"}, "not accessible"),
    ({"conversation_id": 43}, "not accessible"),
    ({"message_index": 3}, "original message index or source"),
    ({"assistant_message_id": 62}, "does not match the reserved message"),
    ({"projection_run_id": "b" * 32, "assistant_message_id": 62}, "does not match the reserved message"),
])
def test_projection_replay_cannot_replace_the_original_receipt(projection, change, reason):
    _, _, _, save = projection
    with pytest.raises(ValueError, match=reason):
        repository.persist_prepared_assistant_projection(**{**SCOPE, **change})
    save.assert_not_called()


def test_matching_projection_reuses_the_existing_assistant_transactionally(projection):
    _, _, lock, save = projection
    result = repository.persist_prepared_assistant_projection(
        **SCOPE, assistant_message_id=61, terminal_status="completed", message_content="answer",
    )
    assert result == 61
    assert lock.call_args.args[1:] == (42, "actor")
    assert save.call_args.args == (61, 42)
    assert save.call_args.kwargs["db_session"] is lock.call_args.args[0]


def test_deleted_conversation_cannot_replay_its_retained_receipt(projection):
    sessions, _, _, _ = projection
    with sessions() as session:
        session.get(ConversationRecord, 42).delete_flag = "Y"
        assert session.get(ConversationMessage, 61).delete_flag == "N"
    assert repository.get_prepared_projection_receipt(**SCOPE) is None
