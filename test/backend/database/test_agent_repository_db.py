"""Unit tests for backend.database.agent_repository_db."""

import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub dependencies before importing the module under test.
# ---------------------------------------------------------------------------

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.CAN_EDIT_ALL_USER_ROLES = frozenset({"admin"})
consts_mock.const.PERMISSION_EDIT = "edit"
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const

agent_repository_consts = MagicMock()
agent_repository_consts.STATUS_NOT_SHARED = "not_shared"
agent_repository_consts.STATUS_PENDING_REVIEW = "pending_review"
agent_repository_consts.STATUS_REJECTED = "rejected"
agent_repository_consts.STATUS_SHARED = "shared"
agent_repository_consts.OWNERSHIP_ALL = "all"
agent_repository_consts.OWNERSHIP_CREATED = "created"
agent_repository_consts.OWNERSHIP_OTHERS = "others"
sys.modules["consts.agent_repository"] = agent_repository_consts

boto3_mock = MagicMock()
sys.modules["boto3"] = boto3_mock

client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules["database.client"] = client_mock
sys.modules["backend.database.client"] = client_mock

group_db_mock = MagicMock()
group_db_mock.query_group_ids_by_user = MagicMock(return_value=[])
sys.modules["database.group_db"] = group_db_mock
sys.modules["backend.database.group_db"] = group_db_mock


class _AgentRepositoryModel:
    """Lightweight ORM stand-in with SQLAlchemy-style column descriptors."""

    agent_repository_id = MagicMock(name="agent_repository_id")
    publisher_tenant_id = MagicMock(name="publisher_tenant_id")
    publisher_user_id = MagicMock(name="publisher_user_id")
    agent_id = MagicMock(name="agent_id")
    version_no = MagicMock(name="version_no")
    name = MagicMock(name="name")
    display_name = MagicMock(name="display_name")
    description = MagicMock(name="description")
    author = MagicMock(name="author")
    submitted_by = MagicMock(name="submitted_by")
    tags = MagicMock(name="tags")
    tool_count = MagicMock(name="tool_count")
    icon = MagicMock(name="icon")
    downloads = MagicMock(name="downloads")
    version_name = MagicMock(name="version_name")
    agent_info_json = MagicMock(name="agent_info_json")
    status = MagicMock(name="status")
    delete_flag = MagicMock(name="delete_flag")
    create_time = MagicMock(name="create_time")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "agent_repository_id" not in self.__dict__:
            self.agent_repository_id = 1


class _AgentInfoModel:
    agent_id = MagicMock(name="agent_id")
    created_by = MagicMock(name="created_by")
    current_version_no = MagicMock(name="current_version_no")
    tenant_id = MagicMock(name="tenant_id")
    version_no = MagicMock(name="version_no")
    delete_flag = MagicMock(name="delete_flag")
    enabled = MagicMock(name="enabled")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _AgentVersionModel:
    agent_id = MagicMock(name="agent_id")
    version_no = MagicMock(name="version_no")
    tenant_id = MagicMock(name="tenant_id")
    version_name = MagicMock(name="version_name")
    create_time = MagicMock(name="create_time")
    delete_flag = MagicMock(name="delete_flag")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


db_models_mock = MagicMock()
db_models_mock.AgentRepository = _AgentRepositoryModel
db_models_mock.AgentInfo = _AgentInfoModel
db_models_mock.AgentVersion = _AgentVersionModel
sys.modules["database.db_models"] = db_models_mock
sys.modules["backend.database.db_models"] = db_models_mock

from backend.database import agent_repository_db as repo_db  # noqa: E402
from backend.database.agent_repository_db import (  # noqa: E402
    fetch_draft_agent_mine_metadata,
    get_agent_repository_by_agent_id,
    get_agent_repository_by_id,
    get_agent_repository_by_id_and_publisher,
    increment_agent_repository_downloads,
    insert_agent_repository_record,
    list_agent_repository_by_agent_ids,
    list_agent_repository_by_publisher,
    list_agent_repository_summaries,
    reset_agent_repository_status,
    soft_delete_agent_repository_by_id,
    sum_agent_repository_downloads_by_agent_ids,
    update_agent_repository_by_id,
    update_agent_repository_status_by_id,
    upsert_agent_repository_record,
)

STATUS_NOT_SHARED = "not_shared"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockAgentRepository:
    def __init__(self, **kwargs):
        defaults = {
            "agent_repository_id": 1,
            "agent_id": 10,
            "publisher_tenant_id": "tenant-1",
            "publisher_user_id": "user-1",
            "version_no": 1,
            "name": "test-agent",
            "display_name": "Test Agent",
            "description": "desc",
            "author": "author",
            "submitted_by": None,
            "tags": ["tag1"],
            "tool_count": 2,
            "version_name": "v1",
            "icon": "icon",
            "downloads": 0,
            "status": STATUS_NOT_SHARED,
            "delete_flag": "N",
            "agent_info_json": {"agents": []},
            "created_by": "user-1",
            "updated_by": "user-1",
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


class MockSummaryRow:
    def __init__(self, **kwargs):
        defaults = {
            "agent_repository_id": 1,
            "agent_id": 10,
            "author": "author",
            "submitted_by": None,
            "name": "test-agent",
            "display_name": "Test Agent",
            "description": "desc",
            "status": STATUS_NOT_SHARED,
            "tags": ["tag1"],
            "tool_count": 2,
            "version_name": "v1",
            "icon": "icon",
            "downloads": 0,
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


class MockAgentIdRow:
    def __init__(self, **kwargs):
        defaults = {
            "agent_repository_id": 1,
            "agent_id": 10,
            "status": STATUS_NOT_SHARED,
            "version_no": 1,
            "version_name": "v1",
            "create_time": datetime(2024, 1, 1),
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


class MockDownloadSumRow:
    def __init__(self, agent_id, total_downloads):
        self.agent_id = agent_id
        self.total_downloads = total_downloads


class MockDraftRow:
    def __init__(self, **kwargs):
        defaults = {
            "agent_id": 10,
            "created_by": "user-1",
            "current_version_no": 2,
            "version_name": "v2",
            "create_time": datetime(2024, 2, 1),
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


def _session_ctx(session):
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = None
    return ctx


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(repo_db, "get_db_session", lambda: _session_ctx(session))


def _patch_update(monkeypatch):
    """Patch sqlalchemy update() so mock ORM models do not break DML construction."""

    def _update(_table):
        stmt = MagicMock()
        stmt.where.return_value = stmt
        stmt.values.return_value = stmt
        return stmt

    monkeypatch.setattr(repo_db, "update", _update)


@pytest.fixture
def mock_session():
    session = MagicMock()
    query = MagicMock()
    session.query.return_value = query
    return session, query


# ---------------------------------------------------------------------------
# insert_agent_repository_record
# ---------------------------------------------------------------------------


def test_insert_agent_repository_record_success(monkeypatch, mock_session):
    session, _ = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "filter_property", lambda data, model: data)

    captured = {}

    def _make_record(**kwargs):
        captured.update(kwargs)
        return MockAgentRepository(**kwargs)

    monkeypatch.setattr(repo_db, "AgentRepository", _make_record)

    repository_data = {
        "agent_id": 10,
        "version_no": 1,
        "name": "agent",
        "agent_info_json": {"agents": []},
    }
    result = insert_agent_repository_record(
        repository_data=repository_data,
        publisher_tenant_id="tenant-1",
        publisher_user_id="user-1",
    )

    assert result == 1
    session.add.assert_called_once()
    session.flush.assert_called_once()
    assert captured["publisher_tenant_id"] == "tenant-1"
    assert captured["publisher_user_id"] == "user-1"
    assert captured["created_by"] == "user-1"
    assert captured["updated_by"] == "user-1"
    assert captured["delete_flag"] == "N"
    assert captured["status"] == STATUS_NOT_SHARED


def test_insert_agent_repository_record_preserves_explicit_status(monkeypatch, mock_session):
    session, _ = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "filter_property", lambda data, model: data)

    captured = {}

    def _make_record(**kwargs):
        captured.update(kwargs)
        return MockAgentRepository(**kwargs)

    monkeypatch.setattr(repo_db, "AgentRepository", _make_record)

    insert_agent_repository_record(
        repository_data={
            "agent_id": 10,
            "version_no": 1,
            "name": "agent",
            "status": "shared",
            "agent_info_json": {},
        },
        publisher_tenant_id="tenant-1",
        publisher_user_id="user-1",
    )

    assert captured["status"] == "shared"


# ---------------------------------------------------------------------------
# get_agent_repository_by_id
# ---------------------------------------------------------------------------


def test_get_agent_repository_by_id_found(monkeypatch, mock_session):
    session, query = mock_session
    record = MockAgentRepository(agent_repository_id=5)
    query.filter.return_value.first.return_value = record
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = get_agent_repository_by_id(5)

    assert result["agent_repository_id"] == 5
    assert result["name"] == "test-agent"


def test_get_agent_repository_by_id_not_found(monkeypatch, mock_session):
    session, query = mock_session
    query.filter.return_value.first.return_value = None
    _patch_session(monkeypatch, session)

    assert get_agent_repository_by_id(999) is None


# ---------------------------------------------------------------------------
# get_agent_repository_by_id_and_publisher
# ---------------------------------------------------------------------------


def test_get_agent_repository_by_id_and_publisher_found(monkeypatch, mock_session):
    session, query = mock_session
    record = MockAgentRepository(agent_repository_id=3, publisher_tenant_id="tenant-1")
    query.filter.return_value.first.return_value = record
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = get_agent_repository_by_id_and_publisher(3, "tenant-1")

    assert result["agent_repository_id"] == 3
    assert result["publisher_tenant_id"] == "tenant-1"


def test_get_agent_repository_by_id_and_publisher_not_found(monkeypatch, mock_session):
    session, query = mock_session
    query.filter.return_value.first.return_value = None
    _patch_session(monkeypatch, session)

    assert get_agent_repository_by_id_and_publisher(3, "tenant-1") is None


# ---------------------------------------------------------------------------
# get_agent_repository_by_agent_id
# ---------------------------------------------------------------------------


def test_get_agent_repository_by_agent_id_found(monkeypatch, mock_session):
    session, query = mock_session
    record = MockAgentRepository(agent_id=10)
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.first.return_value = record
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = get_agent_repository_by_agent_id(10)

    assert result["agent_id"] == 10


def test_get_agent_repository_by_agent_id_with_version_and_tenant(monkeypatch, mock_session):
    session, query = mock_session
    record = MockAgentRepository(agent_id=10, version_no=2, publisher_tenant_id="tenant-1")
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.first.return_value = record
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = get_agent_repository_by_agent_id(
        10,
        version_no=2,
        publisher_tenant_id="tenant-1",
    )

    assert result["version_no"] == 2
    assert inner_query.filter.call_count == 2


def test_get_agent_repository_by_agent_id_not_found(monkeypatch, mock_session):
    session, query = mock_session
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.first.return_value = None
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    assert get_agent_repository_by_agent_id(10) is None


# ---------------------------------------------------------------------------
# upsert_agent_repository_record
# ---------------------------------------------------------------------------


def test_upsert_agent_repository_record_missing_agent_id():
    with pytest.raises(ValueError, match="agent_id is required"):
        upsert_agent_repository_record({}, "tenant-1", "user-1")


def test_upsert_agent_repository_record_insert_path(monkeypatch):
    monkeypatch.setattr(
        repo_db,
        "get_agent_repository_by_agent_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        repo_db,
        "insert_agent_repository_record",
        MagicMock(return_value=42),
    )

    repo_id, is_updated = upsert_agent_repository_record(
        {"agent_id": 10, "version_no": 1},
        "tenant-1",
        "user-1",
    )

    assert repo_id == 42
    assert is_updated is False
    repo_db.insert_agent_repository_record.assert_called_once()


def test_upsert_agent_repository_record_same_version_updates_status_only(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)
    monkeypatch.setattr(
        repo_db,
        "get_agent_repository_by_agent_id",
        MagicMock(return_value={
            "agent_repository_id": 7,
            "version_no": 1,
        }),
    )

    repo_id, is_updated = upsert_agent_repository_record(
        {"agent_id": 10, "version_no": 1, "status": "shared"},
        "tenant-1",
        "user-1",
    )

    assert repo_id == 7
    assert is_updated is True
    session.execute.assert_called_once()


def test_upsert_agent_repository_record_different_version_updates_snapshot(monkeypatch, mock_session):
    session, _ = mock_session
    session.execute.return_value = MagicMock()
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)
    monkeypatch.setattr(
        repo_db,
        "get_agent_repository_by_agent_id",
        MagicMock(return_value={
            "agent_repository_id": 7,
            "version_no": 1,
        }),
    )

    repo_id, is_updated = upsert_agent_repository_record(
        {
            "agent_id": 10,
            "version_no": 2,
            "name": "new-name",
            "display_name": "New",
            "agent_info_json": {"agents": []},
            "status": "pending_review",
        },
        "tenant-1",
        "user-1",
    )

    assert repo_id == 7
    assert is_updated is True
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# list_agent_repository_summaries
# ---------------------------------------------------------------------------


def test_list_agent_repository_summaries_returns_expected_shape(monkeypatch, mock_session):
    session, query = mock_session
    row = MockSummaryRow(agent_repository_id=2, agent_id=20)
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = [row]
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    result = list_agent_repository_summaries("tenant-1")

    assert len(result) == 1
    assert result[0]["agent_repository_id"] == 2
    assert result[0]["agent_id"] == 20
    assert set(result[0].keys()) == {
        "agent_repository_id",
        "agent_id",
        "author",
        "submitted_by",
        "name",
        "display_name",
        "description",
        "status",
        "tags",
        "tool_count",
        "version_name",
        "icon",
        "downloads",
    }


def test_list_agent_repository_summaries_with_filters(monkeypatch, mock_session):
    session, query = mock_session
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = []
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    result = list_agent_repository_summaries(
        "tenant-1",
        status="shared",
        agent_id=10,
    )

    assert result == []
    assert inner_query.filter.call_count == 2


def test_list_agent_repository_summaries_empty(monkeypatch, mock_session):
    session, query = mock_session
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = []
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    assert list_agent_repository_summaries("tenant-1") == []


# ---------------------------------------------------------------------------
# update_agent_repository_by_id
# ---------------------------------------------------------------------------


def test_update_agent_repository_by_id_success(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = update_agent_repository_by_id(
        repository_id=1,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
        updates={"display_name": "Updated", "forbidden_field": "x"},
    )

    assert result == 1
    session.execute.assert_called_once()


def test_update_agent_repository_by_id_empty_updates(monkeypatch, mock_session):
    session, _ = mock_session
    _patch_session(monkeypatch, session)

    result = update_agent_repository_by_id(
        repository_id=1,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
        updates={"forbidden_field": "x"},
    )

    assert result == 0
    session.execute.assert_not_called()


def test_update_agent_repository_by_id_no_rows_affected(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 0
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = update_agent_repository_by_id(
        repository_id=999,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
        updates={"status": "shared"},
    )

    assert result == 0


# ---------------------------------------------------------------------------
# update_agent_repository_status_by_id
# ---------------------------------------------------------------------------


def test_update_agent_repository_status_by_id_basic(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = update_agent_repository_status_by_id(
        repository_id=1,
        status="shared",
        user_id="user-1",
    )

    assert result == 1
    session.execute.assert_called_once()


def test_update_agent_repository_status_by_id_with_optional_fields(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = update_agent_repository_status_by_id(
        repository_id=1,
        status="pending_review",
        user_id="user-1",
        filter_publisher_tenant_id="tenant-1",
        publisher_tenant_id="tenant-2",
        publisher_user_id="user-2",
        submitted_by="submitter@example.com",
    )

    assert result == 1
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# reset_agent_repository_status / soft_delete
# ---------------------------------------------------------------------------


def test_reset_agent_repository_status(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 2
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = reset_agent_repository_status(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
        publisher_tenant_id="tenant-1",
    )

    assert result == 2
    session.execute.assert_called_once()


def test_soft_delete_agent_repository_by_id(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = soft_delete_agent_repository_by_id(
        repository_id=1,
        publisher_tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result == 1
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# list_agent_repository_by_publisher
# ---------------------------------------------------------------------------


def test_list_agent_repository_by_publisher_all(monkeypatch, mock_session):
    session, query = mock_session
    record = MockAgentRepository(agent_repository_id=3)
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = [record]
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = list_agent_repository_by_publisher("tenant-1")

    assert len(result) == 1
    assert result[0]["agent_repository_id"] == 3


def test_list_agent_repository_by_publisher_filter_user(monkeypatch, mock_session):
    session, query = mock_session
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = []
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(repo_db, "as_dict", lambda obj: obj.__dict__)

    result = list_agent_repository_by_publisher("tenant-1", publisher_user_id="user-1")

    assert result == []
    inner_query.filter.assert_called_once()


# ---------------------------------------------------------------------------
# list_agent_repository_by_agent_ids
# ---------------------------------------------------------------------------


def test_list_agent_repository_by_agent_ids_empty():
    assert list_agent_repository_by_agent_ids([], statuses=["shared"], publisher_tenant_id="t") == []


def test_list_agent_repository_by_agent_ids_success(monkeypatch, mock_session):
    session, query = mock_session
    row = MockAgentIdRow(agent_repository_id=5, agent_id=10, status="shared")
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.order_by.return_value.all.return_value = [row]
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    result = list_agent_repository_by_agent_ids(
        [10],
        statuses=["shared", "pending_review"],
        publisher_tenant_id="tenant-1",
    )

    assert len(result) == 1
    assert result[0]["agent_repository_id"] == 5
    assert result[0]["agent_id"] == 10
    assert result[0]["status"] == "shared"
    assert result[0]["version_no"] == 1
    assert result[0]["version_name"] == "v1"
    assert result[0]["create_time"] == row.create_time


# ---------------------------------------------------------------------------
# increment_agent_repository_downloads / sum downloads
# ---------------------------------------------------------------------------


def test_increment_agent_repository_downloads(monkeypatch, mock_session):
    session, _ = mock_session
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result
    _patch_session(monkeypatch, session)
    _patch_update(monkeypatch)

    result = increment_agent_repository_downloads(1)

    assert result == 1
    session.execute.assert_called_once()


def test_sum_agent_repository_downloads_by_agent_ids_empty():
    assert sum_agent_repository_downloads_by_agent_ids([]) == {}


def test_sum_agent_repository_downloads_by_agent_ids_success(monkeypatch, mock_session):
    session, query = mock_session
    row = MockDownloadSumRow(agent_id=10, total_downloads=15)
    inner_query = MagicMock()
    inner_query.filter.return_value = inner_query
    inner_query.group_by.return_value.all.return_value = [row]
    query.filter.return_value = inner_query
    _patch_session(monkeypatch, session)

    result = sum_agent_repository_downloads_by_agent_ids([10, 20])

    assert result == {10: 15}


# ---------------------------------------------------------------------------
# fetch_draft_agent_mine_metadata
# ---------------------------------------------------------------------------


def test_fetch_draft_agent_mine_metadata_empty():
    assert fetch_draft_agent_mine_metadata("tenant-1", []) == {}


def test_fetch_draft_agent_mine_metadata_success(monkeypatch, mock_session):
    session, _ = mock_session
    row = MockDraftRow(agent_id=10)
    inner_query = MagicMock()
    inner_query.outerjoin.return_value = inner_query
    inner_query.filter.return_value = inner_query
    inner_query.all.return_value = [row]
    session.query.return_value = inner_query
    _patch_session(monkeypatch, session)

    result = fetch_draft_agent_mine_metadata("tenant-1", [10])

    assert result == {
        10: {
            "created_by": "user-1",
            "current_version_no": 2,
            "version_name": "v2",
            "version_create_time": row.create_time,
        }
    }
