import sys
import types
from unittest.mock import MagicMock

import pytest


# Ensure backend imports resolve
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))


# Stub sqlalchemy with minimal API used by conversation_db
sa_mod = types.ModuleType("sqlalchemy")
sa_mod.asc = MagicMock(name="asc")
sa_mod.desc = MagicMock(name="desc")
sa_mod.func = MagicMock(name="func")
sa_mod.insert = MagicMock(name="insert")
sa_mod.select = MagicMock(name="select")
sa_mod.update = MagicMock(name="update")
sys.modules["sqlalchemy"] = sa_mod


# Stub database.client
client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.as_dict = MagicMock(name="as_dict")
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod


# Stub db_models with attributes referenced by the module
db_models_mod = types.ModuleType("database.db_models")

class ConversationRecord:
    conversation_id = MagicMock(name="ConversationRecord.conversation_id")
    conversation_title = MagicMock(name="ConversationRecord.conversation_title")
    create_time = MagicMock(name="ConversationRecord.create_time")
    update_time = MagicMock(name="ConversationRecord.update_time")
    created_by = MagicMock(name="ConversationRecord.created_by")
    delete_flag = MagicMock(name="ConversationRecord.delete_flag")


class ConversationMessage:
    message_id = MagicMock(name="ConversationMessage.message_id")
    message_index = MagicMock(name="ConversationMessage.message_index")
    message_role = MagicMock(name="ConversationMessage.message_role")
    unit_index = MagicMock(name="ConversationMessage.unit_index")
    conversation_id = MagicMock(name="ConversationMessage.conversation_id")
    delete_flag = MagicMock(name="ConversationMessage.delete_flag")


class ConversationMessageUnit:
    unit_id = MagicMock(name="ConversationMessageUnit.unit_id")
    unit_index = MagicMock(name="ConversationMessageUnit.unit_index")
    unit_type = MagicMock(name="ConversationMessageUnit.unit_type")
    unit_content = MagicMock(name="ConversationMessageUnit.unit_content")
    message_id = MagicMock(name="ConversationMessageUnit.message_id")
    conversation_id = MagicMock(name="ConversationMessageUnit.conversation_id")
    delete_flag = MagicMock(name="ConversationMessageUnit.delete_flag")


class ConversationSourceSearch:
    search_id = MagicMock(name="ConversationSourceSearch.search_id")
    conversation_id = MagicMock(name="ConversationSourceSearch.conversation_id")
    delete_flag = MagicMock(name="ConversationSourceSearch.delete_flag")


class ConversationSourceImage:
    image_id = MagicMock(name="ConversationSourceImage.image_id")
    conversation_id = MagicMock(name="ConversationSourceImage.conversation_id")
    message_id = MagicMock(name="ConversationSourceImage.message_id")
    delete_flag = MagicMock(name="ConversationSourceImage.delete_flag")


db_models_mod.ConversationRecord = ConversationRecord
db_models_mod.ConversationMessage = ConversationMessage
db_models_mod.ConversationMessageUnit = ConversationMessageUnit
db_models_mod.ConversationSourceSearch = ConversationSourceSearch
db_models_mod.ConversationSourceImage = ConversationSourceImage

sys.modules["database.db_models"] = db_models_mod
sys.modules["backend.database.db_models"] = db_models_mod


# Import module under test after stubbing
from backend.database.conversation_db import delete_conversation, soft_delete_all_conversations_by_user


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


def test_soft_delete_all_conversations_by_user_none(monkeypatch, mock_session_ctx):
    """Return 0 and do no writes when user has no conversations."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    count = soft_delete_all_conversations_by_user("user-1")

    assert count == 0
    session.scalars.assert_called_once()
    session.execute.assert_not_called()


def test_soft_delete_all_conversations_by_user_some(monkeypatch, mock_session_ctx):
    """Soft-delete across all related tables when conversations exist."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = [101, 102, 103]
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    count = soft_delete_all_conversations_by_user("user-2")

    assert count == 3
    session.scalars.assert_called_once()
    # conversations, messages, units, searches, images
    assert session.execute.call_count == 5


def test_delete_conversation_success(monkeypatch, mock_session_ctx):
    """delete_conversation returns True when conversation rowcount > 0 and cascades updates."""
    session, ctx = mock_session_ctx
    # First execute returns conversation_result with rowcount > 0
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.side_effect = [conversation_result, MagicMock(), MagicMock(), MagicMock(), MagicMock()]

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_conversation(123, user_id="actor")

    assert ok is True
    # 5 executes: conversation, message, unit, search, image
    assert session.execute.call_count == 5


def test_delete_conversation_noop(monkeypatch, mock_session_ctx):
    """delete_conversation returns False when no conversation row affected."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 0
    session.execute.side_effect = [conversation_result, MagicMock(), MagicMock(), MagicMock(), MagicMock()]

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_conversation(999)

    assert ok is False
    assert session.execute.call_count == 5
