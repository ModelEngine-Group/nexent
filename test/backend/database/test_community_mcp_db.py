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

from backend.database.community_mcp_db import (
    get_mcp_community_records,
    get_mcp_community_tag_stats,
    create_mcp_community_record,
    get_mcp_community_record_by_id_and_tenant,
    update_mcp_community_record_by_id,
    delete_mcp_community_record_by_id,
    list_mcp_community_records_by_tenant,
    get_mcp_community_tag_stats_by_tenant,
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
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

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
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

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
# list_mcp_community_records_by_tenant
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

    result = list_mcp_community_records_by_tenant("tid")
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
