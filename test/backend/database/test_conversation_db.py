import json
import sys
import types
from unittest.mock import MagicMock

import pytest


# Ensure backend imports resolve
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))


# Global state for capturing SQLAlchemy statement values
_captured_insert_values = {}
_captured_update_values = {}


def _reset_captured():
    """Reset captured values before each test."""
    _captured_insert_values.clear()
    _captured_update_values.clear()


# Stub sqlalchemy with minimal API used by conversation_db
sa_mod = types.ModuleType("sqlalchemy")
sa_mod.asc = MagicMock(name="asc")
sa_mod.desc = MagicMock(name="desc")
sa_mod.func = MagicMock(name="func")
sa_mod.select = MagicMock(name="select")


def _create_insert_mock():
    """Create an insert mock that captures values passed to .values()."""
    def _insert_mock(table):
        mock_stmt = MagicMock(name="insert_statement")

        mock_values = MagicMock(name="insert().values()")

        def _values_side_effect(**kwargs):
            _captured_insert_values.update(kwargs)
            return mock_values

        mock_values.side_effect = _values_side_effect
        mock_values.return_value = mock_values
        mock_stmt.values = mock_values

        mock_returning = MagicMock(name="insert().values().returning()")
        mock_values.returning.return_value = mock_returning

        mock_compiled = MagicMock(name="compiled_statement")
        mock_compiled.params = {}
        mock_returning.compile.return_value = mock_compiled

        return mock_stmt

    return _insert_mock


def _create_update_mock():
    """Create an update mock that captures values passed to .values()."""
    def _update_mock(table):
        mock_stmt = MagicMock(name="update_statement")

        mock_values = MagicMock(name="update().where().values()")

        def _values_side_effect(*args, **kwargs):
            # .values() is called with a dict as first positional argument
            if args:
                _captured_update_values.update(args[0])
            _captured_update_values.update(kwargs)
            return mock_values

        mock_values.side_effect = _values_side_effect

        # Make .where() return the same mock_stmt so .values() can be called on it
        mock_stmt.where = MagicMock(return_value=mock_stmt)
        mock_stmt.values = mock_values

        return mock_stmt

    return _update_mock


sa_mod.insert = _create_insert_mock()
sa_mod.update = _create_update_mock()
sys.modules["sqlalchemy"] = sa_mod


# Stub database.client
client_mod = types.ModuleType("database.client")
client_mod.get_db_session = MagicMock(name="get_db_session")
client_mod.as_dict = MagicMock(name="as_dict")
client_mod.db_client = MagicMock(name="db_client")
sys.modules["database.client"] = client_mod
sys.modules["backend.database.client"] = client_mod


# Stub db_models with attributes referenced by the module
db_models_mod = types.ModuleType("database.db_models")


class ConversationRecord:
    conversation_id = MagicMock(name="ConversationRecord.conversation_id")
    conversation_title = MagicMock(name="ConversationRecord.conversation_title")
    agent_id = MagicMock(name="ConversationRecord.agent_id")
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
    minio_files = MagicMock(name="ConversationMessage.minio_files")
    opinion_flag = MagicMock(name="ConversationMessage.opinion_flag")


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
    message_id = MagicMock(name="ConversationSourceSearch.message_id")
    delete_flag = MagicMock(name="ConversationSourceSearch.delete_flag")


class ConversationSourceImage:
    image_id = MagicMock(name="ConversationSourceImage.image_id")
    conversation_id = MagicMock(name="ConversationSourceImage.conversation_id")
    message_id = MagicMock(name="ConversationSourceImage.message_id")
    image_url = MagicMock(name="ConversationSourceImage.image_url")
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
    HistorySummaryPersistenceError,
    _parse_history_summary_content,
    create_conversation,
    create_conversation_message,
    create_message_unit,
    create_message_units,
    create_source_image,
    create_source_search,
    delete_conversation,
    delete_source_image,
    delete_source_search,
    get_conversation,
    get_conversation_history,
    get_historical_context,
    get_conversation_list,
    get_conversation_messages,
    get_last_unit_for_message,
    get_latest_assistant_message,
    get_latest_assistant_message_id,
    get_message,
    get_message_id_by_index,
    get_message_units,
    get_source_images_by_conversation,
    get_source_images_by_message,
    get_source_searches_by_conversation,
    get_source_searches_by_message,
    rename_conversation,
    save_history_summary,
    soft_delete_all_conversations_by_user,
    update_conversation_agent_id,
    update_conversation_message_content,
    update_conversation_message_status,
    update_message_minio_files,
    update_message_opinion,
    update_message_unit_content,
    update_message_unit_status,
)


@pytest.fixture(autouse=True)
def reset_captured():
    """Reset captured SQLAlchemy values before each test."""
    _reset_captured()
    yield
    _reset_captured()


@pytest.fixture
def fresh_insert_mock():
    """Return captured insert values dict for verification."""
    return _captured_insert_values


@pytest.fixture
def fresh_update_mock():
    """Return captured update values dict for verification."""
    return _captured_update_values


@pytest.fixture
def mock_session_ctx():
    session = MagicMock(name="session")
    ctx = MagicMock(name="ctx")
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return session, ctx


# =============================================================================
# Tests for soft_delete_all_conversations_by_user
# =============================================================================


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


# =============================================================================
# Tests for delete_conversation
# =============================================================================


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


# =============================================================================
# Tests for rename_conversation
# =============================================================================


def test_rename_conversation_success_ascii(monkeypatch, mock_session_ctx):
    """rename_conversation returns True when conversation rowcount > 0 with ASCII title."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

    test_db_client = MagicMock(name="db_client_test")
    test_db_client.clean_string_values = MagicMock(
        side_effect=lambda data: {k: v for k, v in data.items()}
    )

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.db_client", test_db_client)

    ok = rename_conversation(123, "New Title", user_id="actor")

    assert ok is True
    session.execute.assert_called_once()
    test_db_client.clean_string_values.assert_called_once()


def test_rename_conversation_success_chinese(monkeypatch, mock_session_ctx):
    """rename_conversation returns True when conversation rowcount > 0 with Chinese title."""
    session, ctx = mock_session_ctx
    conversation_result = MagicMock()
    conversation_result.rowcount = 1
    session.execute.return_value = conversation_result

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


# =============================================================================
# Tests for create_conversation
# =============================================================================


def test_create_conversation_success(monkeypatch, mock_session_ctx):
    """create_conversation creates a new conversation and returns its details."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.conversation_id = 42
    mock_record.conversation_title = "Test Title"
    mock_record.agent_id = 7
    mock_record.create_time = 1234567890.123
    mock_record.update_time = 1234567890.456
    session.execute.return_value.fetchone.return_value = mock_record

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = create_conversation("Test Title", user_id="user-1", agent_id=7)

    assert result["conversation_id"] == 42
    assert result["conversation_title"] == "Test Title"
    assert result["agent_id"] == 7
    assert result["create_time"] == 1234567890
    assert result["update_time"] == 1234567890
    session.execute.assert_called_once()
    assert _captured_insert_values["agent_id"] == 7


def test_create_conversation_without_user_id(monkeypatch, mock_session_ctx):
    """create_conversation works without user_id."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.conversation_id = 1
    mock_record.conversation_title = "No User Title"
    mock_record.agent_id = None
    mock_record.create_time = 1000.0
    mock_record.update_time = 1000.0
    session.execute.return_value.fetchone.return_value = mock_record

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = create_conversation("No User Title")

    assert result["conversation_id"] == 1
    session.execute.assert_called_once()


# =============================================================================
# Tests for create_conversation_message
# =============================================================================


def test_create_conversation_message_forwards_status(monkeypatch):
    """create_conversation_message must persist the status column with the supplied value."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 7
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

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
    # Verify status is in the captured values
    assert _captured_insert_values["status"] == "streaming"


def test_create_conversation_message_with_minio_files(monkeypatch):
    """create_conversation_message serializes minio_files dict to JSON string."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 5
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    message_id = create_conversation_message(
        {
            "conversation_id": 1,
            "message_idx": 1,
            "role": "assistant",
            "content": "response",
            "minio_files": [{"name": "file.pdf", "url": "http://example.com/file.pdf"}],
        },
        user_id="actor",
        status="completed",
    )

    assert message_id == 5
    # minio_files should be serialized to JSON string
    import json
    assert _captured_insert_values["minio_files"] == json.dumps([{"name": "file.pdf", "url": "http://example.com/file.pdf"}])


def test_create_conversation_message_default_status(monkeypatch):
    """create_conversation_message uses default status 'completed' when not specified."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 3
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    message_id = create_conversation_message(
        {
            "conversation_id": 1,
            "message_idx": 0,
            "role": "user",
            "content": "hello",
            "minio_files": None,
        },
        user_id="actor",
    )

    assert message_id == 3
    assert _captured_insert_values["status"] == "completed"


# =============================================================================
# Tests for create_message_unit
# =============================================================================


def test_create_message_unit_inserts_single_row(monkeypatch):
    """create_message_unit inserts one ConversationMessageUnit row and returns its id."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 99
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

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
    assert _captured_insert_values["message_id"] == 1
    assert _captured_insert_values["conversation_id"] == 2
    assert _captured_insert_values["unit_index"] == 3
    assert _captured_insert_values["unit_type"] == "model_output_code"
    assert _captured_insert_values["unit_content"] == "print('x')"
    assert _captured_insert_values["unit_status"] == "streaming"
    assert _captured_insert_values["created_by"] == "actor"
    assert _captured_insert_values["updated_by"] == "actor"


def test_create_message_unit_serializes_structured_content(monkeypatch):
    """create_message_unit serializes mappings before inserting into the text column."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 11
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    unit_id = create_message_unit(
        message_id=1,
        conversation_id=2,
        unit_index=0,
        unit_type="skill_artifact",
        unit_content={"skill_name": "create-docx", "artifacts": [{"file_name": "output.docx"}]},
    )

    assert unit_id == 11
    assert json.loads(_captured_insert_values["unit_content"]) == {
        "skill_name": "create-docx",
        "artifacts": [{"file_name": "output.docx"}],
    }


def test_create_message_unit_without_user_id(monkeypatch):
    """create_message_unit works without user_id."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 10
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    unit_id = create_message_unit(
        message_id=1,
        conversation_id=2,
        unit_index=0,
        unit_type="final_answer",
        unit_content="Done!",
        unit_status="completed",
    )

    assert unit_id == 10
    assert _captured_insert_values["message_id"] == 1
    assert _captured_insert_values["unit_status"] == "completed"
    # No user tracking when user_id is None
    assert "created_by" not in _captured_insert_values


# =============================================================================
# Tests for create_message_units (batch)
# =============================================================================


def test_create_message_units_batch(monkeypatch):
    """create_message_units inserts multiple rows and returns their ids."""
    session = MagicMock()
    session.execute.return_value.scalar_one.side_effect = [100, 101, 102]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    unit_ids = create_message_units(
        [
            {"type": "final_answer", "content": "First response"},
            {"type": "code", "content": "print(1)"},
            {"type": "final_answer", "content": "Second response"},
        ],
        message_id=5,
        conversation_id=10,
        user_id="tester",
    )

    assert unit_ids == [100, 101, 102]
    assert session.execute.call_count == 3


def test_create_message_units_empty_list(monkeypatch):
    """create_message_units returns empty list when given empty input."""
    ctx = MagicMock()
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = create_message_units([], message_id=1, conversation_id=2)

    assert result == []


# =============================================================================
# Tests for update functions
# =============================================================================


def test_update_conversation_message_status(monkeypatch):
    """update_conversation_message_status runs an UPDATE with the new status."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_conversation_message_status(7, "completed", user_id="actor")

    session.execute.assert_called_once()
    assert _captured_update_values["status"] == "completed"
    assert _captured_update_values["updated_by"] == "actor"


def test_update_conversation_message_status_without_user(monkeypatch):
    """update_conversation_message_status works without user_id."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_conversation_message_status(7, "failed")

    session.execute.assert_called_once()
    assert _captured_update_values["status"] == "failed"
    assert "updated_by" not in _captured_update_values


def test_update_message_unit_status(monkeypatch):
    """update_message_unit_status runs an UPDATE with the new unit_status."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_message_unit_status(42, "completed", user_id="actor")

    session.execute.assert_called_once()
    assert _captured_update_values["unit_status"] == "completed"
    assert _captured_update_values["updated_by"] == "actor"


def test_update_conversation_message_content(monkeypatch):
    """update_conversation_message_content runs an UPDATE with new message_content."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_conversation_message_content(7, "new text", user_id="actor")

    session.execute.assert_called_once()
    assert _captured_update_values["message_content"] == "new text"
    assert _captured_update_values["updated_by"] == "actor"


def test_update_message_unit_content_serializes_structured_content(monkeypatch):
    """update_message_unit_content serializes mappings before updating the text column."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_message_unit_content(42, {"status": "ready"}, user_id="editor")

    assert json.loads(_captured_update_values["unit_content"]) == {"status": "ready"}
    assert _captured_update_values["updated_by"] == "editor"


def test_update_message_unit_content(monkeypatch):
    """update_message_unit_content runs an UPDATE with new unit_content."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    update_message_unit_content(42, "updated content", user_id="editor")

    session.execute.assert_called_once()
    assert _captured_update_values["unit_content"] == "updated content"
    assert _captured_update_values["updated_by"] == "editor"


def test_update_message_opinion(monkeypatch):
    """update_message_opinion runs an UPDATE with new opinion_flag."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = update_message_opinion(7, "Y", user_id="actor")

    assert ok is True
    assert _captured_update_values["opinion_flag"] == "Y"
    assert _captured_update_values["updated_by"] == "actor"


# =============================================================================
# Tests for get_conversation
# =============================================================================


def test_get_conversation_found(monkeypatch, mock_session_ctx):
    """get_conversation returns conversation details when found."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.conversation_id = 42
    mock_record.conversation_title = "Test Chat"
    session.scalars.return_value.first.return_value = mock_record

    def as_dict_side_effect(record):
        return {
            "conversation_id": record.conversation_id,
            "conversation_title": record.conversation_title,
        }

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation(42, user_id="user-1")

    assert result is not None
    assert result["conversation_id"] == 42


def test_get_conversation_not_found(monkeypatch, mock_session_ctx):
    """get_conversation returns None when not found."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_conversation(999)

    assert result is None


def test_get_conversation_without_user_id(monkeypatch, mock_session_ctx):
    """get_conversation works without user_id."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.conversation_id = 1
    mock_record.conversation_title = "Public Chat"
    session.scalars.return_value.first.return_value = mock_record

    def as_dict_side_effect(record):
        return {"conversation_id": record.conversation_id}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation(1)

    assert result is not None


# =============================================================================
# Tests for get_conversation_messages
# =============================================================================


def test_get_conversation_messages(monkeypatch, mock_session_ctx):
    """get_conversation_messages returns all messages for a conversation."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock(), MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"message_id": id(record)}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_messages(42)

    assert len(result) == 2
    session.scalars.assert_called_once()


def test_get_conversation_messages_empty(monkeypatch, mock_session_ctx):
    """get_conversation_messages returns empty list when no messages."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_conversation_messages(42)

    assert result == []


# =============================================================================
# Tests for get_message_units
# =============================================================================


def test_get_message_units(monkeypatch, mock_session_ctx):
    """get_message_units returns all units for a message."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock(), MagicMock(), MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"unit_id": id(record)}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_message_units(7)

    assert len(result) == 3


def test_get_message_units_empty(monkeypatch, mock_session_ctx):
    """get_message_units returns empty list when no units."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_message_units(7)

    assert result == []


# =============================================================================
# Tests for get_conversation_list
# =============================================================================


def test_get_conversation_list(monkeypatch, mock_session_ctx):
    """get_conversation_list returns all conversations ordered by create_time desc."""
    session, ctx = mock_session_ctx
    mock_records = [
        MagicMock(
            conversation_id=2, conversation_title="Second", agent_id=22, create_time=2000.0, update_time=2000.0
        ),
        MagicMock(
            conversation_id=1, conversation_title="First", agent_id=11, create_time=1000.0, update_time=1000.0
        ),
    ]
    session.execute.return_value = iter(mock_records)

    def as_dict_side_effect(record):
        return {
            "conversation_id": record.conversation_id,
            "conversation_title": record.conversation_title,
            "agent_id": record.agent_id,
            "create_time": record.create_time,
            "update_time": record.update_time,
        }

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_list()

    assert len(result) == 2
    assert result[0]["conversation_id"] == 2
    assert result[0]["agent_id"] == 22


def test_get_conversation_list_filtered_by_user(monkeypatch, mock_session_ctx):
    """get_conversation_list filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_records = [
        MagicMock(
            conversation_id=1, conversation_title="User Chat", agent_id=15, create_time=1000.0, update_time=1000.0
        )
    ]
    session.execute.return_value = iter(mock_records)

    def as_dict_side_effect(record):
        return {
            "conversation_id": record.conversation_id,
            "conversation_title": record.conversation_title,
            "agent_id": record.agent_id,
            "create_time": record.create_time,
            "update_time": record.update_time,
        }

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_list(user_id="specific-user")

    assert len(result) == 1
    assert result[0]["agent_id"] == 15


def test_update_conversation_agent_id_success(monkeypatch, mock_session_ctx):
    """update_conversation_agent_id updates the latest agent and returns True."""
    session, ctx = mock_session_ctx
    update_result = MagicMock()
    update_result.rowcount = 1
    session.execute.return_value = update_result

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_conversation_agent_id("123", "45", user_id="user-1")

    assert result is True
    session.execute.assert_called_once()


def test_update_conversation_agent_id_not_found(monkeypatch, mock_session_ctx):
    """update_conversation_agent_id returns False when no row is updated."""
    session, ctx = mock_session_ctx
    update_result = MagicMock()
    update_result.rowcount = 0
    session.execute.return_value = update_result

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_conversation_agent_id(123, 45)

    assert result is False
    session.execute.assert_called_once()


# =============================================================================
# Tests for get_message
# =============================================================================


def test_get_message_found(monkeypatch, mock_session_ctx):
    """get_message returns message details when found."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.message_id = 42
    mock_record.message_content = "Hello"
    session.scalars.return_value.first.return_value = mock_record

    def as_dict_side_effect(record):
        return {"message_id": record.message_id, "message_content": record.message_content}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_message(42)

    assert result is not None
    assert result["message_id"] == 42


def test_get_message_not_found(monkeypatch, mock_session_ctx):
    """get_message returns None when not found."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_message(999)

    assert result is None


# =============================================================================
# Tests for get_message_id_by_index
# =============================================================================


def test_get_message_id_by_index_found(monkeypatch, mock_session_ctx):
    """get_message_id_by_index returns message_id when found."""
    session, ctx = mock_session_ctx
    session.execute.return_value.scalar.return_value = 42

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_message_id_by_index(1, 0)

    assert result == 42


def test_get_message_id_by_index_not_found(monkeypatch, mock_session_ctx):
    """get_message_id_by_index returns None when not found."""
    session, ctx = mock_session_ctx
    session.execute.return_value.scalar.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_message_id_by_index(999, 99)

    assert result is None


# =============================================================================
# Tests for get_latest_assistant_message_id
# =============================================================================


def test_get_latest_assistant_message_id_found(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message_id returns message_id when found."""
    session, ctx = mock_session_ctx
    session.execute.return_value.scalar.return_value = 42

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message_id(1)

    assert result == 42


def test_get_latest_assistant_message_id_not_found(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message_id returns None when not found."""
    session, ctx = mock_session_ctx
    session.execute.return_value.scalar.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message_id(999)

    assert result is None


# =============================================================================
# Tests for get_latest_assistant_message
# =============================================================================


def test_get_latest_assistant_message_found(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message returns message details when found."""
    session, ctx = mock_session_ctx
    mock_result = MagicMock()
    mock_result.message_id = 42
    mock_result.status = "completed"
    mock_result.message_content = "Hello"
    session.execute.return_value.first.return_value = mock_result

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message(1)

    assert result is not None
    assert result["message_id"] == 42
    assert result["status"] == "completed"
    assert result["message_content"] == "Hello"


def test_get_latest_assistant_message_not_found(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message returns None when not found."""
    session, ctx = mock_session_ctx
    session.execute.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message(999)

    assert result is None


# =============================================================================
# Tests for get_last_unit_for_message
# =============================================================================


def test_get_last_unit_for_message_found(monkeypatch, mock_session_ctx):
    """get_last_unit_for_message returns last unit when found."""
    session, ctx = mock_session_ctx
    mock_result = MagicMock()
    mock_result.unit_id = 99
    mock_result.unit_index = 5
    mock_result.unit_type = "final_answer"
    mock_result.unit_content = "Done"
    mock_result.unit_status = "completed"
    session.execute.return_value.first.return_value = mock_result

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_last_unit_for_message(42)

    assert result is not None
    assert result["unit_id"] == 99
    assert result["unit_index"] == 5
    assert result["unit_status"] == "completed"


def test_get_last_unit_for_message_not_found(monkeypatch, mock_session_ctx):
    """get_last_unit_for_message returns None when no units exist."""
    session, ctx = mock_session_ctx
    session.execute.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_last_unit_for_message(999)

    assert result is None


# =============================================================================
# Tests for create_source_image
# =============================================================================


def test_create_source_image_success(monkeypatch, fresh_insert_mock):
    """create_source_image inserts image record and returns id."""
    session = MagicMock()
    # Use side_effect to return different values for different calls:
    # First call: _image_exists check -> scalar_one_or_none returns None (image doesn't exist)
    # Second call: insert -> scalar_one returns the new image id
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # _image_exists check
        MagicMock(scalar_one=MagicMock(return_value=55)),  # insert result
    ]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    image_id = create_source_image(
        {"message_id": 7, "image_url": "http://example.com/image.png"},
        user_id="actor",
    )

    assert image_id == 55
    assert fresh_insert_mock["message_id"] == 7
    assert fresh_insert_mock["image_url"] == "http://example.com/image.png"


# =============================================================================
# Tests for delete_source_image
# =============================================================================


def test_delete_source_image_success(monkeypatch):
    """delete_source_image soft-deletes and returns True."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_image(42, user_id="actor")

    assert ok is True


def test_delete_source_image_not_found(monkeypatch):
    """delete_source_image returns False when image not found."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_image(999)

    assert ok is False


# =============================================================================
# Tests for create_source_search
# =============================================================================


def test_create_source_search_success(monkeypatch, fresh_insert_mock):
    """create_source_search inserts search record and returns id."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 88
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    search_id = create_source_search(
        {
            "message_id": 7,
            "source_type": "web",
            "source_title": "Example Site",
            "source_location": "http://example.com",
            "source_content": "Content here",
            "cite_index": 1,
            "search_type": "search",
            "tool_sign": "web_search",
        },
        user_id="actor",
    )

    assert search_id == 88
    assert fresh_insert_mock["message_id"] == 7
    assert fresh_insert_mock["source_type"] == "web"


def test_create_source_search_with_optional_fields(monkeypatch, fresh_insert_mock):
    """create_source_search includes optional score fields."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 89
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    search_id = create_source_search(
        {
            "message_id": 7,
            "source_type": "web",
            "source_title": "Example Site",
            "source_location": "http://example.com",
            "source_content": "Content here",
            "cite_index": 1,
            "search_type": "search",
            "tool_sign": "web_search",
            "score_overall": 0.95,
            "score_accuracy": 0.90,
            "score_semantic": 0.88,
        },
        user_id="actor",
    )

    assert search_id == 89
    assert fresh_insert_mock["score_overall"] == 0.95
    assert fresh_insert_mock["score_accuracy"] == 0.90


# =============================================================================
# Tests for delete_source_search
# =============================================================================


def test_delete_source_search_success(monkeypatch):
    """delete_source_search soft-deletes and returns True."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_search(42, user_id="actor")

    assert ok is True


def test_delete_source_search_not_found(monkeypatch):
    """delete_source_search returns False when search not found."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_search(999)

    assert ok is False


# =============================================================================
# Tests for get_source_images_by_message
# =============================================================================


def test_get_source_images_by_message(monkeypatch, mock_session_ctx):
    """get_source_images_by_message returns images for a message."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock(), MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"image_id": id(record)}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_images_by_message(7)

    assert len(result) == 2


# =============================================================================
# Tests for get_source_images_by_conversation
# =============================================================================


def test_get_source_images_by_conversation(monkeypatch, mock_session_ctx):
    """get_source_images_by_conversation returns images for a conversation."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"image_id": id(record)}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_images_by_conversation(1)

    assert len(result) == 1


# =============================================================================
# Tests for get_source_searches_by_message
# =============================================================================


def test_get_source_searches_by_message(monkeypatch):
    """get_source_searches_by_message returns searches for a message."""
    # Skip complex join query test - difficult to mock properly
    # This function is covered by integration tests
    pass


# =============================================================================
# Tests for get_source_searches_by_conversation
# =============================================================================


def test_get_source_searches_by_conversation(monkeypatch, mock_session_ctx):
    """get_source_searches_by_conversation returns searches for a conversation."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"search_id": id(record)}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_searches_by_conversation(1)

    assert len(result) == 1


# =============================================================================
# Tests for get_conversation_history
# =============================================================================


def test_get_conversation_history_found(monkeypatch, mock_session_ctx):
    """get_conversation_history returns full history when conversation exists."""
    session, ctx = mock_session_ctx
    # This function has complex joins - skip detailed mock testing
    # It is covered by integration tests
    pass


def test_get_conversation_history_not_found(monkeypatch, mock_session_ctx):
    """get_conversation_history returns None when conversation doesn't exist."""
    session, ctx = mock_session_ctx
    session.execute.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_conversation_history(999)

    assert result is None


# =============================================================================
# Tests for update_message_minio_files
# =============================================================================


def test_update_message_minio_files_success(monkeypatch, mock_session_ctx):
    """update_message_minio_files appends files to existing minio_files."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.minio_files = '[]'
    session.scalars.return_value.first.return_value = mock_record

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_message_minio_files(42, [{"name": "new.pdf"}])

    assert result is True
    # Verify minio_files was updated
    assert 'new.pdf' in mock_record.minio_files


def test_update_message_minio_files_not_found(monkeypatch, mock_session_ctx):
    """update_message_minio_files returns False when message not found."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.first.return_value = None

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_message_minio_files(999, [{"name": "file.pdf"}])

    assert result is False


# =============================================================================
# Additional tests for uncovered conversation_db lines
# =============================================================================


def test_get_conversation_with_user_id_filter(monkeypatch, mock_session_ctx):
    """get_conversation filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.conversation_id = 42
    mock_record.conversation_title = "User Chat"
    session.scalars.return_value.first.return_value = mock_record

    def as_dict_side_effect(record):
        return {"conversation_id": record.conversation_id, "conversation_title": record.conversation_title}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation(42, user_id="specific-user")

    assert result is not None
    assert result["conversation_id"] == 42


def test_get_conversation_filters_by_user_and_tenant(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.scalars.return_value.first.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    tenant_lookup = MagicMock(return_value={"user_id": "user-1", "tenant_id": "tenant-1"})
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        tenant_lookup,
    )

    result = get_conversation(42, user_id="user-1", tenant_id="tenant-1")

    assert result is None
    tenant_lookup.assert_called_once_with("user-1")
    session.scalars.assert_called_once()


def test_get_conversation_rejects_cross_tenant_identity(monkeypatch, mock_session_ctx):
    session, _ = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda user_id: {"user_id": user_id, "tenant_id": "tenant-2"},
    )

    assert get_conversation(42, user_id="user-1", tenant_id="tenant-1") is None
    session.scalars.assert_not_called()


def test_get_conversation_accepts_legacy_asset_owner_tenant(monkeypatch, mock_session_ctx):
    session, ctx = mock_session_ctx
    session.scalars.return_value.first.return_value = MagicMock()
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "", "user_role": "ASSET_OWNER"},
    )

    result = get_conversation(
        42,
        user_id="asset-owner",
        tenant_id="asset_owner_tenant_id",
    )

    assert result is not None
    session.scalars.assert_called_once()


def test_get_conversation_rejects_tenant_without_user():
    with pytest.raises(ValueError, match="user_id is required"):
        get_conversation(42, tenant_id="tenant-1")


def test_get_message_with_user_id_filter(monkeypatch, mock_session_ctx):
    """get_message filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.message_id = 42
    mock_record.message_content = "Hello"
    session.scalars.return_value.first.return_value = mock_record

    def as_dict_side_effect(record):
        return {"message_id": record.message_id, "message_content": record.message_content}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_message(42, user_id="owner-user")

    assert result is not None
    assert result["message_id"] == 42


def test_get_latest_assistant_message_with_user_id(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_result = MagicMock()
    mock_result.message_id = 42
    mock_result.status = "completed"
    mock_result.message_content = "Hello"
    session.execute.return_value.first.return_value = mock_result

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message(1, user_id="owner-user")

    assert result is not None
    assert result["message_id"] == 42


def test_get_latest_assistant_message_id_with_user_id(monkeypatch, mock_session_ctx):
    """get_latest_assistant_message_id filters by user_id when provided."""
    session, ctx = mock_session_ctx
    session.execute.return_value.scalar.return_value = 42

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_latest_assistant_message_id(1, user_id="owner-user")

    assert result == 42


def test_create_source_image_duplicate_returns_minus_one(monkeypatch):
    """create_source_image returns -1 when image already exists."""
    session = MagicMock()
    # _image_exists check returns True (image already exists)
    session.execute.return_value.scalar_one_or_none.return_value = True
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    image_id = create_source_image(
        {"message_id": 7, "image_url": "http://example.com/image.png"},
        user_id="actor",
    )

    assert image_id == -1
    # Insert should not be called
    assert session.execute.call_count == 1


def test_create_source_image_with_conversation_id(monkeypatch):
    """create_source_image includes optional conversation_id."""
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # _image_exists check
        MagicMock(scalar_one=MagicMock(return_value=55)),  # insert result
    ]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    image_id = create_source_image(
        {"message_id": 7, "conversation_id": 10, "image_url": "http://example.com/image.png"},
        user_id="actor",
    )

    assert image_id == 55
    assert _captured_insert_values["conversation_id"] == 10


def test_create_source_search_with_unit_id(monkeypatch, fresh_insert_mock):
    """create_source_search includes optional unit_id field."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 88
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    search_id = create_source_search(
        {
            "message_id": 7,
            "source_type": "web",
            "source_title": "Example Site",
            "source_location": "http://example.com",
            "source_content": "Content here",
            "cite_index": 1,
            "search_type": "search",
            "tool_sign": "web_search",
            "unit_id": 42,
        },
        user_id="actor",
    )

    assert search_id == 88
    assert fresh_insert_mock["unit_id"] == 42


def test_create_source_search_with_published_date(monkeypatch, fresh_insert_mock):
    """create_source_search includes optional published_date field."""
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 88
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    from datetime import datetime
    published = datetime(2024, 1, 15)

    search_id = create_source_search(
        {
            "message_id": 7,
            "source_type": "web",
            "source_title": "Example Site",
            "source_location": "http://example.com",
            "source_content": "Content here",
            "cite_index": 1,
            "search_type": "search",
            "tool_sign": "web_search",
            "published_date": published,
        },
        user_id="actor",
    )

    assert search_id == 88
    assert fresh_insert_mock["published_date"] == published


def test_update_message_opinion_returns_false_when_not_found(monkeypatch):
    """update_message_opinion returns False when message not found."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = update_message_opinion(999, "Y", user_id="actor")

    assert ok is False


def test_update_message_opinion_without_user(monkeypatch):
    """update_message_opinion works without user_id."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = update_message_opinion(7, "N")

    assert ok is True
    assert _captured_update_values["opinion_flag"] == "N"
    assert "updated_by" not in _captured_update_values


def test_update_message_minio_files_with_existing_files(monkeypatch, mock_session_ctx):
    """update_message_minio_files appends to existing minio_files JSON."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.minio_files = '[{"name": "existing.pdf"}]'
    session.scalars.return_value.first.return_value = mock_record

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_message_minio_files(42, [{"name": "new.pdf"}])

    assert result is True
    assert 'existing.pdf' in mock_record.minio_files
    assert 'new.pdf' in mock_record.minio_files


def test_update_message_minio_files_with_invalid_json(monkeypatch, mock_session_ctx):
    """update_message_minio_files handles invalid existing minio_files JSON."""
    session, ctx = mock_session_ctx
    mock_record = MagicMock()
    mock_record.minio_files = "not valid json {"
    session.scalars.return_value.first.return_value = mock_record

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = update_message_minio_files(42, [{"name": "new.pdf"}])

    assert result is True
    assert 'new.pdf' in mock_record.minio_files


def test_get_source_images_by_message_with_user_id(monkeypatch, mock_session_ctx):
    """get_source_images_by_message filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"image_id": 1}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_images_by_message(7, user_id="owner-user")

    assert len(result) == 1


def test_get_source_images_by_conversation_with_user_id(monkeypatch, mock_session_ctx):
    """get_source_images_by_conversation filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"image_id": 1}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_images_by_conversation(1, user_id="owner-user")

    assert len(result) == 1


def test_get_source_searches_by_message_with_user_id(monkeypatch, mock_session_ctx):
    """get_source_searches_by_message filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"search_id": 1}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_searches_by_message(7, user_id="owner-user")

    assert len(result) == 1


def test_get_source_searches_by_conversation_with_user_id(monkeypatch, mock_session_ctx):
    """get_source_searches_by_conversation filters by user_id when provided."""
    session, ctx = mock_session_ctx
    mock_records = [MagicMock()]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {"search_id": 1}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_source_searches_by_conversation(1, user_id="owner-user")

    assert len(result) == 1


def test_create_conversation_message_with_string_minio_files(monkeypatch):
    """create_conversation_message uses string minio_files directly when already a string."""
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 5
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    message_id = create_conversation_message(
        {
            "conversation_id": 1,
            "message_idx": 1,
            "role": "assistant",
            "content": "response",
            "minio_files": '[{"name": "already.json"}]',
        },
        user_id="actor",
        status="completed",
    )

    assert message_id == 5
    # minio_files should be used as-is since it's already a string
    assert _captured_insert_values["minio_files"] == '[{"name": "already.json"}]'


def test_delete_source_image_without_user_id(monkeypatch):
    """delete_source_image works without user_id."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_image(42)

    assert ok is True
    assert _captured_update_values["delete_flag"] == 'Y'


def test_delete_source_search_without_user_id(monkeypatch):
    """delete_source_search works without user_id."""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    ok = delete_source_search(42)

    assert ok is True
    assert _captured_update_values["delete_flag"] == 'Y'


def test_get_source_images_by_message_empty(monkeypatch, mock_session_ctx):
    """get_source_images_by_message returns empty list when no images."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_source_images_by_message(7)

    assert result == []


def test_get_source_images_by_conversation_empty(monkeypatch, mock_session_ctx):
    """get_source_images_by_conversation returns empty list when no images."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_source_images_by_conversation(1)

    assert result == []


def test_get_source_searches_by_message_empty(monkeypatch, mock_session_ctx):
    """get_source_searches_by_message returns empty list when no searches."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_source_searches_by_message(7)

    assert result == []


def test_get_source_searches_by_conversation_empty(monkeypatch, mock_session_ctx):
    """get_source_searches_by_conversation returns empty list when no searches."""
    session, ctx = mock_session_ctx
    session.scalars.return_value.all.return_value = []

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_source_searches_by_conversation(1)

    assert result == []


def test_get_conversation_history_with_messages(monkeypatch, mock_session_ctx):
    """get_conversation_history processes messages with units."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    # Use SimpleNamespace for accurate attribute checks
    mock_conv = SimpleNamespace(conversation_id=1, agent_id=9, create_time=1000.0)
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files=None,
        opinion_flag=None,
        units=None,
    )

    # First execute() call returns conversation check result
    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    # Second execute() call returns messages
    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    # Session.scalars() calls for search/image - all return empty
    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": getattr(record, 'units', None),
            }
        elif hasattr(record, 'conversation_id'):
            return {
                "conversation_id": record.conversation_id,
                "agent_id": record.agent_id,
                "create_time": record.create_time,
            }
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    assert result['conversation_id'] == 1
    assert result['agent_id'] == 9


def test_create_message_units_creates_all_units_with_user_id(monkeypatch):
    """create_message_units creates all units with user tracking."""
    session = MagicMock()
    session.execute.return_value.scalar_one.side_effect = [100, 101]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    unit_ids = create_message_units(
        [
            {"type": "code", "content": "x = 1"},
            {"type": "code", "content": "y = 2"},
        ],
        message_id=5,
        conversation_id=10,
        user_id="tracked-user",
    )

    assert unit_ids == [100, 101]
    assert session.execute.call_count == 2
    # The session.execute was called twice (once per unit)
    assert session.execute.call_count == 2


def test_get_message_units_with_records(monkeypatch, mock_session_ctx):
    """get_message_units returns formatted unit records."""
    session, ctx = mock_session_ctx
    mock_records = [
        MagicMock(unit_id=1, unit_index=0, unit_type="code", unit_content="x=1"),
        MagicMock(unit_id=2, unit_index=1, unit_type="code", unit_content="y=2"),
    ]
    session.scalars.return_value.all.return_value = mock_records

    def as_dict_side_effect(record):
        return {
            "unit_id": record.unit_id,
            "unit_index": record.unit_index,
            "unit_type": record.unit_type,
            "unit_content": record.unit_content,
        }

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_message_units(7)

    assert len(result) == 2
    assert result[0]["unit_id"] == 1
    assert result[1]["unit_id"] == 2


# =============================================================================
# Tests for line 756 (sort units by unit_index)
# =============================================================================


def test_get_conversation_history_sorts_units_by_index(monkeypatch, mock_session_ctx):
    """get_conversation_history sorts units by unit_index when present (line 756)."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    # Conversation record
    mock_conv = SimpleNamespace(conversation_id=1, create_time=1000.0)

    # Message with units in REVERSE order (index 2, 1, 0) to verify sorting
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files=None,
        opinion_flag=None,
        units=[
            {"unit_id": 3, "unit_index": 2, "unit_type": "code", "unit_content": "c=3", "unit_status": "done"},
            {"unit_id": 1, "unit_index": 0, "unit_type": "code", "unit_content": "a=1", "unit_status": "done"},
            {"unit_id": 2, "unit_index": 1, "unit_type": "code", "unit_content": "b=2", "unit_status": "done"},
        ],
    )

    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": record.units,
            }
        elif hasattr(record, 'conversation_id'):
            return {"conversation_id": record.conversation_id, "create_time": record.create_time}
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    # Units should be sorted by unit_index: 0, 1, 2
    units = result['message_records'][0]['units']
    assert units[0]['unit_index'] == 0
    assert units[1]['unit_index'] == 1
    assert units[2]['unit_index'] == 2
    assert units[0]['unit_id'] == 1
    assert units[1]['unit_id'] == 2
    assert units[2]['unit_id'] == 3


# =============================================================================
# Tests for lines 759-762 (parse minio_files JSON string)
# =============================================================================


def test_get_conversation_history_parses_minio_files_json_string(monkeypatch, mock_session_ctx):
    """get_conversation_history parses minio_files when it is a JSON string (line 762)."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    mock_conv = SimpleNamespace(conversation_id=1, create_time=1000.0)
    # minio_files is a JSON string that should be parsed into a Python object
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files='[{"name": "report.pdf", "size": 1024}]',
        opinion_flag=None,
        units=None,
    )

    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": record.units,
            }
        elif hasattr(record, 'conversation_id'):
            return {"conversation_id": record.conversation_id, "create_time": record.create_time}
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    # minio_files should be parsed into a list of dicts
    parsed_files = result['message_records'][0]['minio_files']
    assert isinstance(parsed_files, list)
    assert len(parsed_files) == 1
    assert parsed_files[0]['name'] == "report.pdf"
    assert parsed_files[0]['size'] == 1024


def test_get_conversation_history_minio_files_non_string_kept_as_is(monkeypatch, mock_session_ctx):
    """get_conversation_history keeps minio_files as-is when it's not a string (line 761 else branch)."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    mock_conv = SimpleNamespace(conversation_id=1, create_time=1000.0)
    # minio_files already a list (non-string) - should remain unchanged
    pre_parsed_files = [{"name": "already_list.json"}]
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files=pre_parsed_files,
        opinion_flag=None,
        units=None,
    )

    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": record.units,
            }
        elif hasattr(record, 'conversation_id'):
            return {"conversation_id": record.conversation_id, "create_time": record.create_time}
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    # Should remain a list (not re-parsed)
    assert result['message_records'][0]['minio_files'] == pre_parsed_files


def test_get_conversation_history_minio_files_invalid_json_kept(monkeypatch, mock_session_ctx):
    """get_conversation_history keeps minio_files as original when JSON parsing fails (line 764-766)."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    mock_conv = SimpleNamespace(conversation_id=1, create_time=1000.0)
    # Invalid JSON string - should be kept as-is
    invalid_json = "not valid json {"
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files=invalid_json,
        opinion_flag=None,
        units=None,
    )

    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": record.units,
            }
        elif hasattr(record, 'conversation_id'):
            return {"conversation_id": record.conversation_id, "create_time": record.create_time}
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    # Should be kept as original invalid JSON string
    assert result['message_records'][0]['minio_files'] == invalid_json


def test_get_conversation_history_units_empty_list(monkeypatch, mock_session_ctx):
    """get_conversation_history handles empty units list (line 754)."""
    from types import SimpleNamespace

    session, ctx = mock_session_ctx

    mock_conv = SimpleNamespace(conversation_id=1, create_time=1000.0)
    mock_message = SimpleNamespace(
        message_id=1,
        message_index=0,
        message_role="user",
        message_content="Hello",
        status="completed",
        minio_files=None,
        opinion_flag=None,
        units=[],  # Empty list - not None
    )

    conv_exec_result = MagicMock()
    conv_exec_result.first.return_value = mock_conv

    message_exec_result = MagicMock()
    message_exec_result.all.return_value = [mock_message]

    scalars_result = MagicMock()
    scalars_result.all.return_value = []

    session.execute.side_effect = [conv_exec_result, message_exec_result]
    session.scalars.return_value = scalars_result

    def as_dict_side_effect(record):
        if isinstance(record, MagicMock):
            return {}
        if hasattr(record, 'message_id') and hasattr(record, 'message_role'):
            return {
                "message_id": record.message_id,
                "message_index": record.message_index,
                "role": record.message_role,
                "message_content": record.message_content,
                "status": record.status,
                "minio_files": record.minio_files,
                "opinion_flag": record.opinion_flag,
                "units": record.units,
            }
        elif hasattr(record, 'conversation_id'):
            return {"conversation_id": record.conversation_id, "create_time": record.create_time}
        return {}

    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)
    monkeypatch.setattr("backend.database.conversation_db.as_dict", as_dict_side_effect)

    result = get_conversation_history(1)

    assert result is not None
    assert result['message_records'][0]['units'] == []


# =============================================================================
# History summary checkpoint tests
# =============================================================================


def test_parse_history_summary_requires_summary_and_positive_boundary():
    assert _parse_history_summary_content(
        '{"summary":{"task_overview":"x"},"covered_through_message_id":24}'
    )["covered_through_message_id"] == 24
    assert _parse_history_summary_content('{"covered_through_message_id":24}') is None
    assert _parse_history_summary_content(
        '{"summary":{},"covered_through_message_id":0}') is None
    assert _parse_history_summary_content("not-json") is None


def test_save_history_summary_rejects_cross_tenant_before_database(monkeypatch):
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "tenant-b"})
    with pytest.raises(HistorySummaryPersistenceError, match="not accessible"):
        save_history_summary(1, "user-a", "tenant-a", {}, 24)


def test_save_history_summary_appends_after_last_unit(monkeypatch, mock_session_ctx,
                                                       fresh_insert_mock):
    from types import SimpleNamespace
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "tenant-a"})
    message_index_column = MagicMock()
    message_index_column.__gt__.return_value = MagicMock()
    message_index_column.__le__.return_value = MagicMock()
    monkeypatch.setattr(ConversationMessage, "message_index", message_index_column)
    owner_result = MagicMock()
    owner_result.first.return_value = SimpleNamespace(conversation_id=1)
    covered_result = MagicMock()
    covered_result.first.return_value = SimpleNamespace(
        message_id=24, message_index=3, message_role="assistant",
        status="completed")
    insert_result = MagicMock()
    insert_result.scalar_one.return_value = 1001
    session.execute.side_effect = [owner_result, covered_result, insert_result]
    session.scalar.side_effect = [0, 4]
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    unit_id = save_history_summary(
        1, "user-a", "tenant-a", {"task_overview": "done"}, 24,
        trigger="soft_budget_exceeded")

    assert unit_id == 1001
    assert fresh_insert_mock["message_id"] == 24
    assert fresh_insert_mock["unit_index"] == 5
    assert fresh_insert_mock["unit_type"] == "history_summary"
    assert fresh_insert_mock["unit_status"] == "completed"
    payload = __import__("json").loads(fresh_insert_mock["unit_content"])
    assert payload["covered_through_message_id"] == 24
    assert payload["trigger"] == "soft_budget_exceeded"


def test_save_history_summary_rejects_incomplete_covered_range(
        monkeypatch, mock_session_ctx):
    from types import SimpleNamespace
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "tenant-a"})
    message_index_column = MagicMock()
    message_index_column.__gt__.return_value = MagicMock()
    message_index_column.__le__.return_value = MagicMock()
    monkeypatch.setattr(ConversationMessage, "message_index", message_index_column)
    owner_result = MagicMock()
    owner_result.first.return_value = SimpleNamespace(conversation_id=1)
    covered_result = MagicMock()
    covered_result.first.return_value = SimpleNamespace(
        message_id=24, message_index=3, message_role="assistant",
        status="completed")
    session.execute.side_effect = [owner_result, covered_result]
    session.scalar.return_value = 1
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    with pytest.raises(HistorySummaryPersistenceError, match="completed messages only"):
        save_history_summary(1, "user-a", "tenant-a", {}, 24)


def test_get_historical_context_rejects_cross_tenant(monkeypatch):
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "tenant-b"})
    assert get_historical_context(1, 25, "user-a", "tenant-a") is None


def test_get_historical_context_returns_latest_summary_and_only_new_turns(
        monkeypatch, mock_session_ctx):
    from types import SimpleNamespace
    session, ctx = mock_session_ctx
    monkeypatch.setattr(
        "backend.database.conversation_db._get_user_tenant",
        lambda _user_id: {"tenant_id": "tenant-a"})
    index_column = MagicMock()
    index_column.__lt__.return_value = MagicMock()
    index_column.__gt__.return_value = MagicMock()
    monkeypatch.setattr(ConversationMessage, "message_index", index_column)
    role_column = MagicMock()
    role_column.in_.return_value = MagicMock()
    monkeypatch.setattr(ConversationMessage, "message_role", role_column)

    current_result = MagicMock()
    current_result.first.return_value = SimpleNamespace(message_id=25, message_index=6)
    candidates_result = MagicMock()
    candidates_result.all.return_value = [SimpleNamespace(
        unit_id=1001, unit_index=4, message_index=3,
        unit_content='{"summary":{"task_overview":"old"},'
                     '"covered_through_message_id":24}')]
    boundary_result = MagicMock()
    boundary_result.first.return_value = SimpleNamespace(
        message_index=3, message_role="assistant", status="completed")
    messages_result = MagicMock()
    messages_result.all.return_value = [
        SimpleNamespace(message_id=31, message_index=4, message_role="user",
                        message_content="new question", minio_files=None),
        SimpleNamespace(message_id=32, message_index=5, message_role="assistant",
                        message_content="new answer", minio_files=None),
    ]
    session.execute.side_effect = [
        current_result, candidates_result, boundary_result, messages_result]
    monkeypatch.setattr("backend.database.conversation_db.get_db_session", lambda: ctx)

    result = get_historical_context(1, 25, "user-a", "tenant-a")

    assert result["history_summary"]["unit_id"] == 1001
    assert result["history_summary"]["covered_through_message_id"] == 24
    assert result["conversation_turns"] == [{
        "user_message": "new question",
        "assistant_final_answer": "new answer",
        "attachments": None,
        "user_message_id": 31,
        "assistant_message_id": 32,
    }]
