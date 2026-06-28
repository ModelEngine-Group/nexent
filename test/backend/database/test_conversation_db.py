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

# Add db_client with clean_string_values method to the stub
client_mod.db_client = MagicMock(name="db_client")
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
    message_content = MagicMock(name="ConversationMessage.message_content")
    unit_index = MagicMock(name="ConversationMessage.unit_index")
    conversation_id = MagicMock(name="ConversationMessage.conversation_id")
    delete_flag = MagicMock(name="ConversationMessage.delete_flag")
    status = MagicMock(name="ConversationMessage.status")


class ConversationMessageUnit:
    unit_id = MagicMock(name="ConversationMessageUnit.unit_id")
    unit_index = MagicMock(name="ConversationMessageUnit.unit_index")
    unit_type = MagicMock(name="ConversationMessageUnit.unit_type")
    unit_content = MagicMock(name="ConversationMessageUnit.unit_content")
    message_id = MagicMock(name="ConversationMessageUnit.message_id")
    conversation_id = MagicMock(name="ConversationMessageUnit.conversation_id")
    delete_flag = MagicMock(name="ConversationMessageUnit.delete_flag")
    unit_status = MagicMock(name="ConversationMessageUnit.unit_status")


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


# Stub database.utils with the tracking helpers used by conversation_db
utils_mod = types.ModuleType("database.utils")


def _add_creation_tracking(data, user_id):
    data_copy = dict(data)
    data_copy["created_by"] = user_id
    data_copy["updated_by"] = user_id
    return data_copy


def _add_update_tracking(data, user_id):
    data_copy = dict(data)
    data_copy["updated_by"] = user_id
    return data_copy


utils_mod.add_creation_tracking = _add_creation_tracking
utils_mod.add_update_tracking = _add_update_tracking
sys.modules["database.utils"] = utils_mod
sys.modules["backend.database.utils"] = utils_mod


# Import module under test after stubbing
from backend.database.conversation_db import (
    create_conversation_message,
    create_message_unit,
    delete_conversation,
    rename_conversation,
    soft_delete_all_conversations_by_user,
    update_conversation_message_content,
    update_conversation_message_status,
    update_message_unit_status,
)


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


# Tests for rename_conversation


def test_rename_conversation_success_ascii(monkeypatch, mock_session_ctx):
    """rename_conversation returns True when conversation rowcount > 0 with ASCII title."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(123, "New Title", user_id="actor")

    assert ok is True
    session.execute.assert_called_once()
    # Verify clean_string_values was called
    test_db_client.clean_string_values.assert_called_once()


def test_rename_conversation_success_chinese(monkeypatch, mock_session_ctx):
    """rename_conversation returns True when conversation rowcount > 0 with Chinese title."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(456, "测试会话标题", user_id="user-1")

    assert ok is True
    session.execute.assert_called_once()
    test_db_client.clean_string_values.assert_called_once()


def test_rename_conversation_success_mixed(monkeypatch, mock_session_ctx):
    """rename_conversation returns True with mixed ASCII and Chinese characters."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(789, "Project 项目 Alpha", user_id="developer")

    assert ok is True
    session.execute.assert_called_once()


def test_rename_conversation_not_found(monkeypatch, mock_session_ctx):
    """rename_conversation returns False when no conversation row affected."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 0
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(999, "Nonexistent Title")

    assert ok is False
    session.execute.assert_called_once()


def test_rename_conversation_without_user_id(monkeypatch, mock_session_ctx):
    """rename_conversation works without user_id parameter."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(123, "Title Only")

    assert ok is True
    session.execute.assert_called_once()


def test_rename_conversation_conversation_id_as_string(monkeypatch, mock_session_ctx):
    """rename_conversation handles conversation_id passed as string."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation("456", "String ID Title")

    assert ok is True
    session.execute.assert_called_once()


def test_rename_conversation_with_emoji(monkeypatch, mock_session_ctx):
    """rename_conversation handles emoji characters."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    # Create fresh mock for this test
    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(123, "Hello World 🌍", user_id="user-1")

    assert ok is True
    session.execute.assert_called_once()
    test_db_client.clean_string_values.assert_called_once()


# Tests for the new incremental-persistence helpers
# (create_message_unit, update_conversation_message_status,
#  update_message_unit_status, update_conversation_message_content,
#  and the status parameter on create_conversation_message).


def _patch_session(monkeypatch, session):
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    return session


def test_create_conversation_message_forwards_status(monkeypatch):
    """create_conversation_message must persist the status column with the supplied value."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 7
    _patch_session(monkeypatch, session)

    message_id = create_conversation_message(
        {
            "conversation_id": 1,
            "message_idx": 0,
            "role": "user",
            "content": "hi",
            "minio_files": None,
        },
        user_id="actor",
        status="streaming",
    )

    assert message_id == 7
    # Status kwarg is forwarded into the insert values
    values = session.execute.call_args[0][0]
    compiled_values = values.compile().params
    assert compiled_values["status"] == "streaming"


def test_create_message_unit_inserts_single_row(monkeypatch):
    """create_message_unit inserts one ConversationMessageUnit row and returns its id."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 99
    _patch_session(monkeypatch, session)

    unit_id = create_message_unit(
        message_id=1,
        conversation_id=2,
        unit_index=3,
        unit_type="model_output_code",
        unit_content="print('x')",
        user_id="actor",
        unit_status="streaming",
    )

    assert unit_id == 99
    values = session.execute.call_args[0][0]
    compiled = values.compile().params
    assert compiled["message_id"] == 1
    assert compiled["conversation_id"] == 2
    assert compiled["unit_index"] == 3
    assert compiled["unit_type"] == "model_output_code"
    assert compiled["unit_content"] == "print('x')"
    assert compiled["unit_status"] == "streaming"
    assert compiled["created_by"] == "actor"
    assert compiled["updated_by"] == "actor"


def test_update_conversation_message_status(monkeypatch):
    """update_conversation_message_status runs an UPDATE with the new status."""
    session = MagicMock()
    _patch_session(monkeypatch, session)

    update_conversation_message_status(7, "completed", user_id="actor")

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    compiled = stmt.compile().params
    assert compiled["status"] == "completed"
    assert compiled["updated_by"] == "actor"


def test_update_message_unit_status(monkeypatch):
    """update_message_unit_status runs an UPDATE with the new unit_status."""
    session = MagicMock()
    _patch_session(monkeypatch, session)

    update_message_unit_status(42, "completed", user_id="actor")

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    compiled = stmt.compile().params
    assert compiled["unit_status"] == "completed"
    assert compiled["updated_by"] == "actor"


def test_update_conversation_message_content(monkeypatch):
    """update_conversation_message_content runs an UPDATE with new message_content."""
    session = MagicMock()
    _patch_session(monkeypatch, session)

    update_conversation_message_content(7, "new text", user_id="actor")

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    compiled = stmt.compile().params
    assert compiled["message_content"] == "new text"
    assert compiled["updated_by"] == "actor"
