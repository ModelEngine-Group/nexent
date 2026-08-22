"""
Unit tests for backend/database/community_mcp_db.py

Tests community MCP record database operations.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import MagicMock

# Mock modules
consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test_access_key"
consts_mock.const.MINIO_SECRET_KEY = "test_secret_key"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test_user"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_mock.const.POSTGRES_DB = "test_db"
consts_mock.const.POSTGRES_PORT = 5432
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules['database.client'] = client_mock

db_models_mock = MagicMock()
db_models_mock.McpCommunityRecord = MagicMock()
sys.modules['database.db_models'] = db_models_mock


class _MockColumn:
    """Mock for SQLAlchemy column that supports comparison operators."""
    def __lt__(self, other):
        return MagicMock()
    def __eq__(self, other):
        return MagicMock()
    def __ne__(self, other):
        return MagicMock()
    def __hash__(self):
        return hash(id(self))
    def desc(self):
        return MagicMock()
    def ilike(self, s):
        return MagicMock()
    def any(self, s):
        return MagicMock()


# Set up McpCommunityRecord column attributes so SQL comparisons work
db_models_mock.McpCommunityRecord.community_id = _MockColumn()
db_models_mock.McpCommunityRecord.mcp_name = _MockColumn()
db_models_mock.McpCommunityRecord.description = _MockColumn()
db_models_mock.McpCommunityRecord.tags = _MockColumn()
db_models_mock.McpCommunityRecord.transport_type = _MockColumn()
db_models_mock.McpCommunityRecord.review_status = _MockColumn()
db_models_mock.McpCommunityRecord.delete_flag = _MockColumn()
db_models_mock.McpCommunityRecord.tenant_id = _MockColumn()
db_models_mock.McpCommunityRecord.user_id = _MockColumn()
db_models_mock.McpCommunityRecord.mcp_server = _MockColumn()
db_models_mock.McpCommunityRecord.version = _MockColumn()
db_models_mock.McpCommunityRecord.config_json = _MockColumn()
db_models_mock.McpCommunityRecord.registry_json = _MockColumn()


from backend.database.community_mcp_db import (
    get_mcp_community_records,
    get_mcp_community_tag_stats,
    create_mcp_community_record,
    get_mcp_community_record_by_id_and_tenant,
    update_mcp_community_record_by_id,
    delete_mcp_community_record_by_id,
    list_mcp_community_records_by_tenant_and_user,
    get_mcp_community_tag_stats_by_tenant,
    list_mcp_community_review_records,
    update_mcp_community_review_status,
)


class MockCommunityRecord:
    def __init__(self, community_id=1, name="test", tags=None):
        self.community_id = community_id
        self.mcp_name = name
        self.description = "desc"
        self.tags = tags or ["tag1"]
        self.transport_type = "url"
        self.mcp_server = "http://srv"
        self.version = "1.0"
        self.config_json = None
        self.registry_json = None
        self.delete_flag = "N"
        self.tenant_id = "tenant1"
        self.create_time = "2024-01-01"
        self.update_time = "2024-01-01"


@pytest.fixture
def mock_session():
    session = MagicMock()
    query = MagicMock()
    session.query.return_value = query
    return session, query


# ============================================================================
# get_mcp_community_records
# ============================================================================

def test_get_community_records(monkeypatch, mock_session):
    """Test basic retrieval of community records without filters."""
    session, query = mock_session
    r1 = MockCommunityRecord(1, "svc1")
    r2 = MockCommunityRecord(2, "svc2")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r1, r2]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
        "description": obj.description, "tags": obj.tags,
        "transport_type": obj.transport_type, "mcp_server": obj.mcp_server,
        "version": obj.version, "config_json": obj.config_json,
        "registry_json": obj.registry_json, "create_time": obj.create_time,
        "update_time": obj.update_time,
    })

    result = get_mcp_community_records(limit=30)
    assert result["count"] == 2
    assert len(result["items"]) == 2
    assert result["nextCursor"] is None


def test_get_community_records_pagination(monkeypatch, mock_session):
    """Test pagination returns nextCursor when items exceed limit."""
    session, query = mock_session
    # Return limit+1 items to trigger nextCursor
    records = [MockCommunityRecord(i, f"svc{i}") for i in range(1, 32)]  # 31 items, limit=30

    mock_limit = MagicMock()
    mock_limit.all.return_value = records
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
        "description": obj.description, "tags": obj.tags,
        "transport_type": obj.transport_type, "mcp_server": obj.mcp_server,
        "version": obj.version, "config_json": obj.config_json,
        "registry_json": obj.registry_json, "create_time": obj.create_time,
        "update_time": obj.update_time,
    })

    result = get_mcp_community_records(limit=30)
    assert result["count"] == 30
    assert result["nextCursor"] == "30"


# ============================================================================
# get_mcp_community_tag_stats
# ============================================================================

def test_get_community_tag_stats(monkeypatch, mock_session):
    """Test retrieval of community tag statistics."""
    session, query = mock_session

    # Create mock rows with tag and count attributes
    mock_row1 = MagicMock()
    mock_row1.tag = "tag1"
    mock_row1.count = 5
    mock_row2 = MagicMock()
    mock_row2.tag = "tag2"
    mock_row2.count = 3

    mock_all = MagicMock()
    mock_all.all.return_value = [mock_row1, mock_row2]
    mock_group = MagicMock()
    mock_group.order_by.return_value = mock_all
    mock_filter = MagicMock()
    mock_filter.group_by.return_value = mock_group
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_community_tag_stats()
    assert len(result) == 2
    assert result[0] == {"tag": "tag1", "count": 5}


# ============================================================================
# create_mcp_community_record
# ============================================================================

def test_create_community_record(monkeypatch, mock_session):
    """Test successful creation of a community MCP record."""
    session, _ = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.filter_property", lambda data, model: data)

    mock_record = MagicMock()
    mock_record.community_id = 42
    monkeypatch.setattr("backend.database.community_mcp_db.McpCommunityRecord", lambda **kw: mock_record)

    result = create_mcp_community_record(
        {"mcp_name": "test", "mcp_server": "http://srv"},
        tenant_id="tid", user_id="uid",
    )
    assert result == 42
    session.add.assert_called_once()


# ============================================================================
# get_mcp_community_record_by_id_and_tenant
# ============================================================================

def test_get_community_record_by_id_found(monkeypatch, mock_session):
    """Test retrieval of community record by ID when record exists."""
    session, query = mock_session
    r = MockCommunityRecord(1)

    mock_first = MagicMock(return_value=r)
    mock_second_filter = MagicMock()
    mock_second_filter.first = mock_first
    mock_first_filter = MagicMock()
    mock_first_filter.filter.return_value = mock_second_filter
    query.filter.return_value = mock_first_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {"community_id": obj.community_id, "mcp_name": obj.mcp_name})

    result = get_mcp_community_record_by_id_and_tenant(1, "tid")
    assert result is not None
    assert result["community_id"] == 1


def test_get_community_record_by_id_not_found(monkeypatch, mock_session):
    """Test retrieval of community record by ID when record does not exist."""
    session, query = mock_session

    mock_first = MagicMock(return_value=None)
    mock_second_filter = MagicMock()
    mock_second_filter.first = mock_first
    mock_first_filter = MagicMock()
    mock_first_filter.filter.return_value = mock_second_filter
    query.filter.return_value = mock_first_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_community_record_by_id_and_tenant(999, "tid")
    assert result is None


# ============================================================================
# update_mcp_community_record_by_id
# ============================================================================

def test_update_community_record(monkeypatch, mock_session):
    """Test updating a community MCP record with all fields."""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_community_record_by_id(
        community_id=1, tenant_id="tid", user_id="uid",
        name="new-name", description="new-desc", tags=["a", "b"],
    )
    mock_update.assert_called_once()
    call_args = mock_update.call_args[0][0]
    assert call_args["mcp_name"] == "new-name"
    assert call_args["description"] == "new-desc"
    assert call_args["tags"] == ["a", "b"]


def test_update_community_record_partial(monkeypatch, mock_session):
    """Test partial update - only provided fields should be in update."""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_community_record_by_id(
        community_id=1, tenant_id="tid", user_id="uid",
        name="only-name",
    )
    call_args = mock_update.call_args[0][0]
    assert "mcp_name" in call_args
    assert "description" not in call_args


# ============================================================================
# delete_mcp_community_record_by_id
# ============================================================================

def test_delete_community_record(monkeypatch, mock_session):
    """Test soft-deletion of a community MCP record."""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    delete_mcp_community_record_by_id(community_id=1, tenant_id="tid", user_id="uid")
    mock_update.assert_called_once_with({"delete_flag": "Y", "updated_by": "uid"})


# ============================================================================
# list_mcp_community_records_by_tenant_and_user
# ============================================================================

def test_list_community_records_by_tenant(monkeypatch, mock_session):
    """Test listing community records for a specific tenant."""
    session, query = mock_session
    r1 = MockCommunityRecord(1, "svc1")
    r2 = MockCommunityRecord(2, "svc2")

    mock_all = MagicMock(return_value=[r1, r2])
    mock_order = MagicMock()
    mock_order.all = mock_all
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_records_by_tenant_and_user("tid", "uid")
    assert len(result) == 2


# ============================================================================
# get_mcp_community_tag_stats_by_tenant
# ============================================================================

def test_get_community_tag_stats_by_tenant(monkeypatch, mock_session):
    """Test retrieval of community tag statistics for a tenant."""
    session, query = mock_session

    mock_row = MagicMock()
    mock_row.tag = "tagA"
    mock_row.count = 10

    mock_all = MagicMock()
    mock_all.all.return_value = [mock_row]
    mock_group = MagicMock()
    mock_group.order_by.return_value = mock_all
    mock_filter = MagicMock()
    mock_filter.group_by.return_value = mock_group
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    result = get_mcp_community_tag_stats_by_tenant("tid")
    assert len(result) == 1
    assert result[0] == {"tag": "tagA", "count": 10}


# ============================================================================
# get_mcp_community_records - filter paths
# ============================================================================

def test_get_community_records_with_search(monkeypatch, mock_session):
    """Test get_mcp_community_records with search keyword filter."""
    monkeypatch.setattr("backend.database.community_mcp_db.or_", lambda *args: MagicMock())
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_search = MagicMock()
    mock_filter_search.order_by.return_value = mock_order
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_search
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = get_mcp_community_records(search="svc", limit=30)
    assert result["count"] == 1
    assert result["items"][0]["mcp_name"] == "svc1"


def test_get_community_records_with_tag(monkeypatch, mock_session):
    """Test get_mcp_community_records with tag filter."""
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1", tags=["llm"])

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_tag = MagicMock()
    mock_filter_tag.order_by.return_value = mock_order
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_tag
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name, "tags": obj.tags,
    })

    result = get_mcp_community_records(tag="llm", limit=30)
    assert result["count"] == 1


def test_get_community_records_with_transport_type(monkeypatch, mock_session):
    """Test get_mcp_community_records with transport_type filter."""
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_tt = MagicMock()
    mock_filter_tt.order_by.return_value = mock_order
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_tt
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = get_mcp_community_records(transport_type="sse", limit=30)
    assert result["count"] == 1


def test_get_community_records_with_valid_cursor(monkeypatch, mock_session):
    """Test get_mcp_community_records with a valid cursor."""
    session, query = mock_session
    r1 = MockCommunityRecord(5, "svc1")
    r2 = MockCommunityRecord(4, "svc2")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r1, r2]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_cursor = MagicMock()
    mock_filter_cursor.order_by.return_value = mock_order
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_cursor
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = get_mcp_community_records(cursor="10", limit=30)
    assert result["count"] == 2


def test_get_community_records_with_invalid_cursor(monkeypatch, mock_session):
    """Test get_mcp_community_records with invalid cursor (not an int)."""
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_base = MagicMock()
    mock_filter_base.order_by.return_value = mock_order
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = get_mcp_community_records(cursor="invalid", limit=30)
    assert result["count"] == 1


# ============================================================================
# get_mcp_community_record_by_id_and_tenant - tenant_id=None path
# ============================================================================

def test_get_community_record_by_id_tenant_none(monkeypatch, mock_session):
    """Test retrieval when tenant_id is None (skips tenant filter)."""
    session, query = mock_session
    r = MockCommunityRecord(1)

    mock_first = MagicMock(return_value=r)
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {"community_id": obj.community_id})

    result = get_mcp_community_record_by_id_and_tenant(1, None)
    assert result is not None
    assert result["community_id"] == 1


# ============================================================================
# update_mcp_community_review_status
# ============================================================================

def test_update_review_status_with_tenant(monkeypatch, mock_session):
    """Test update with tenant_id filter applied."""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter_tenant = MagicMock()
    mock_filter_tenant.update = mock_update
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_tenant
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_community_review_status(
        community_id=1, tenant_id="tid", user_id="uid", review_status="approved",
    )
    mock_update.assert_called_once_with({"review_status": "approved", "updated_by": "uid"})


def test_update_review_status_without_tenant(monkeypatch, mock_session):
    """Test update without tenant_id (skips tenant filter)."""
    session, query = mock_session
    mock_update = MagicMock()
    query.filter.return_value = mock_update

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)

    update_mcp_community_review_status(
        community_id=1, tenant_id=None, user_id="uid", review_status="rejected",
    )
    mock_update.update.assert_called_once_with({"review_status": "rejected", "updated_by": "uid"})


# ============================================================================
# list_mcp_community_review_records
# ============================================================================

def test_list_review_records_basic(monkeypatch, mock_session):
    """Test basic listing of review records without filters."""
    session, query = mock_session
    r1 = MockCommunityRecord(1, "svc1")
    r2 = MockCommunityRecord(2, "svc2")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r1, r2]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(tenant_id=None)
    assert result["count"] == 2
    assert result["nextCursor"] is None


def test_list_review_records_with_filters(monkeypatch, mock_session):
    """Test review records with status, tag, and transport_type filters."""
    monkeypatch.setattr("backend.database.community_mcp_db.or_", lambda *args: MagicMock())
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_chain = MagicMock()
    mock_filter_chain.order_by.return_value = mock_order
    mock_filter_chain.filter.return_value = mock_filter_chain
    query.filter.return_value = mock_filter_chain

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(
        tenant_id="tid", status="pending", tag="ai", transport_type="url",
    )
    assert result["count"] == 1


def test_list_review_records_with_search(monkeypatch, mock_session):
    """Test review records with search keyword."""
    monkeypatch.setattr("backend.database.community_mcp_db.or_", lambda *args: MagicMock())
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_chain = MagicMock()
    mock_filter_chain.order_by.return_value = mock_order
    mock_filter_chain.filter.return_value = mock_filter_chain
    query.filter.return_value = mock_filter_chain

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(tenant_id="tid", search="test")
    assert result["count"] == 1


def test_list_review_records_with_cursor(monkeypatch, mock_session):
    """Test review records with valid cursor."""
    session, query = mock_session
    r1 = MockCommunityRecord(5, "svc1")
    r2 = MockCommunityRecord(4, "svc2")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r1, r2]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_cursor = MagicMock()
    mock_filter_cursor.order_by.return_value = mock_order
    mock_filter_base = MagicMock()
    mock_filter_base.filter.return_value = mock_filter_cursor
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(tenant_id=None, cursor="10")
    assert result["count"] == 2


def test_list_review_records_with_invalid_cursor(monkeypatch, mock_session):
    """Test review records with invalid cursor (not an int)."""
    session, query = mock_session
    r = MockCommunityRecord(1, "svc1")

    mock_limit = MagicMock()
    mock_limit.all.return_value = [r]
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter_base = MagicMock()
    mock_filter_base.order_by.return_value = mock_order
    query.filter.return_value = mock_filter_base

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(tenant_id=None, cursor="bad")
    assert result["count"] == 1


def test_list_review_records_pagination(monkeypatch, mock_session):
    """Test review records pagination returns nextCursor."""
    session, query = mock_session
    records = [MockCommunityRecord(i, f"svc{i}") for i in range(1, 32)]

    mock_limit = MagicMock()
    mock_limit.all.return_value = records
    mock_order = MagicMock()
    mock_order.limit.return_value = mock_limit
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.community_mcp_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.community_mcp_db.as_dict", lambda obj: {
        "community_id": obj.community_id, "mcp_name": obj.mcp_name,
    })

    result = list_mcp_community_review_records(tenant_id=None, limit=30)
    assert result["count"] == 30
    assert result["nextCursor"] == "30"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
