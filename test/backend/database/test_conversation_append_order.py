"""Database-owned turn indices, independent of frontend message counts."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def store(monkeypatch):
    import database.conversation_db as module
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
