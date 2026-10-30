# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Database-owned turn indices, independent of frontend message counts."""
from contextlib import contextmanager
from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest


@pytest.fixture
def store(monkeypatch):
    import management.db.conversation.repository as module
    session = MagicMock()
    @contextmanager
    def current():
        yield session
    monkeypatch.setattr(module, "get_db_session", current)
    lock, create = MagicMock(), MagicMock(return_value=401)
    monkeypatch.setattr(module, "_lock_conversation_limit_scope", lock)
    monkeypatch.setattr(module, "create_conversation_message", create)
    return module, session, lock, create


@pytest.mark.parametrize("latest,expected", [(None, 0), (0, 2), (1, 2), (5, 6), (8, 10)])
def test_append_reserves_the_adjacent_assistant_index(store, latest, expected):
    module, session, lock, create = store
    session.scalar.side_effect = [7, latest]
    assert module.append_conversation_user_message(7, "Current", [], "owner") == (401, expected)
    lock.assert_called_once_with(session, "conversation-turn-limit:7")
    args, kwargs = create.call_args
    assert args[0]["message_idx"] == expected and args[0]["role"] == "user"
    assert args[1] == "owner" and kwargs["_session"] is session


def test_unowned_conversation_never_inserts(store):
    module, session, _lock, create = store
    session.scalar.return_value = None
    with pytest.raises(module.ConversationNotFoundError):
        module.append_conversation_user_message(7, "Current", [], "other")
    create.assert_not_called()


def test_retry_reuses_original_user_and_verifies_scoped_queries(store):
    module, session, lock, create = store
    session.scalar.side_effect = [7, SimpleNamespace(message_id=20, message_index=4,
        message_content="Same", minio_files='[{"object_name":"owned.png","url":"old"}]'), 21]
    assert module.resolve_conversation_retry_user(7, "owner", 20, 4, "Same",
        [{"object_name": "owned.png", "url": "new"}]) == (20, 4)
    create.assert_not_called()
    lock.assert_called_once_with(session, "conversation-turn-limit:7")
    target_sql = str(session.scalar.call_args_list[1].args[0])
    for field in ["conversation_id", "message_id", "created_by", "message_role", "delete_flag"]:
        assert field in target_sql


@pytest.mark.parametrize("failure", ["owner", "target", "index", "query", "attachments", "answer"])
def test_invalid_retry_never_inserts_or_falls_back_to_new_turn(store, failure):
    module, session, _lock, create = store
    target = SimpleNamespace(message_id=20, message_index=4, message_content="Same", minio_files=[])
    if failure == "index":
        target.message_index = 6
    if failure == "query":
        target.message_content = "Another question"
    if failure == "attachments":
        target.minio_files = [{"object_name": "other.png"}]
    session.scalar.side_effect = [None if failure == "owner" else 7,
                                 None if failure == "target" else target,
                                 None if failure == "answer" else 21]
    with pytest.raises((module.ConversationNotFoundError, module.AppException)):
        module.resolve_conversation_retry_user(7, "owner", 20, 4, "Same", [])
    create.assert_not_called()
