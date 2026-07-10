"""
Unit tests for backend/database/market_mcp_db.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import MagicMock, patch

# Mock consts
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

# Mock database.client
def _as_dict(obj):
    """Convert an object to a dict, handling both real objects and MagicMock."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}


client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = _as_dict
client_mock.filter_property = MagicMock(side_effect=lambda data, model: data)
sys.modules['database.client'] = client_mock

# Mock Column helper for SQLAlchemy-style model comparisons
class _MockColumn:
    """Mock SQLAlchemy column supporting comparison operators."""
    __slots__ = ()
    def __eq__(self, other): return MagicMock()
    def __ne__(self, other): return MagicMock()
    def __lt__(self, other): return MagicMock()
    def __gt__(self, other): return MagicMock()
    def __le__(self, other): return MagicMock()
    def __ge__(self, other): return MagicMock()
    def __add__(self, other): return MagicMock()
    def __radd__(self, other): return MagicMock()
    def __hash__(self): return 0
    def desc(self): return MagicMock()
    def ilike(self, key): return MagicMock()
    def any(self, val): return MagicMock()


class _MockMcpMarketRecord:
    """Mock ORM model for McpMarketRecord."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


for _col in [
    'market_id', 'mcp_name', 'tenant_id', 'user_id', 'delete_flag',
    'description', 'tags', 'transport_type', 'download_count',
    'mcp_server', 'registry_json', 'config_json', 'source',
    'created_by', 'updated_by',
]:
    setattr(_MockMcpMarketRecord, _col, _MockColumn())

db_models_mock = MagicMock()
db_models_mock.McpMarketRecord = _MockMcpMarketRecord
sys.modules['database.db_models'] = db_models_mock

from backend.database.market_mcp_db import (
    get_mcp_market_records,
    get_mcp_market_tag_stats,
    create_mcp_market_record,
    get_mcp_market_record_by_id,
    check_mcp_market_name_exists,
    update_mcp_market_record,
    delete_mcp_market_record_by_id,
    list_mcp_market_records_by_tenant_and_user,
    increment_mcp_market_download_count,
    get_mcp_market_tag_stats_by_tenant,
)

# Override as_dict in the module to avoid MagicProxy descriptor bug in mock 3.15.1
import backend.database.market_mcp_db as _market_mcp_db_mod
_market_mcp_db_mod.as_dict = _as_dict


class MockQuery:
    """Fluent mock for SQLAlchemy query chains."""

    def __init__(self, return_rows=None):
        self._filter_kwargs = {}
        self._order_calls = []
        self._limit_val = None
        self._return_rows = return_rows or []

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        self._order_calls.append(args)
        return self

    def limit(self, val):
        self._limit_val = val
        return self

    def all(self):
        return self._return_rows

    def first(self):
        return self._return_rows[0] if self._return_rows else None

    def update(self, values):
        pass

    def add(self, instance):
        pass

    def flush(self):
        pass

    def __getattr__(self, name):
        return self


class MockSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def query(self, *args):
        return self

    def add(self, instance):
        pass

    def flush(self):
        pass

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def limit(self, val):
        return self

    def all(self):
        return []

    def first(self):
        return None

    def update(self, values):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: self


class TestGetMcpMarketRecords:
    """Test get_mcp_market_records with cursor pagination."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_no_records(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        session.limit = lambda x: session
        mock_session.return_value = session
        result = get_mcp_market_records(tenant_id="tid")
        assert result["count"] == 0

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_with_records(self, mock_session):
        row = MagicMock()
        row.market_id = 1
        row.mcp_name = "svc1"
        row.delete_flag = "N"

        session = MockSession()
        session.all = lambda: [row]
        session.limit = lambda x: session
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = get_mcp_market_records(tenant_id="tid")
        assert result["count"] == 1

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_cursor_pagination(self, mock_session):
        rows = []
        for i in range(5, 0, -1):
            r = MagicMock()
            r.market_id = i
            r.mcp_name = f"svc{i}"
            r.delete_flag = "N"
            rows.append(r)

        session = MockSession()
        session.all = lambda: rows
        session.limit = lambda x: MockQuery(rows[:x])
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = get_mcp_market_records(tenant_id="tid", cursor="3", limit=2)
        assert result["count"] <= 2


class TestCreateMcpMarketRecord:
    """Test create_mcp_market_record."""

    @patch('backend.database.market_mcp_db.get_db_session')
    @patch('backend.database.market_mcp_db.filter_property', side_effect=lambda d, m: d)
    def test_create(self, mock_filter, mock_get_session):
        session = MockSession()
        session.add = MagicMock(side_effect=lambda obj: setattr(obj, 'market_id', 42))
        session.flush = MagicMock()
        session.query = MagicMock(return_value=MockSession())
        mock_get_session.return_value = session

        result = create_mcp_market_record(
            mcp_data={"mcp_name": "svc1"},
            tenant_id="tid", user_id="uid",
        )
        assert result == 42


class TestGetMcpMarketRecordById:
    """Test get_mcp_market_record_by_id."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_found(self, mock_session):
        row = MagicMock()
        row.market_id = 1
        row.mcp_name = "svc1"
        row.delete_flag = "N"

        session = MockSession()
        session.first = lambda: row
        mock_session.return_value = session

        result = get_mcp_market_record_by_id(1)
        assert result is not None
        assert result.get("market_id") == 1

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_not_found(self, mock_session):
        session = MockSession()
        session.first = lambda: None
        mock_session.return_value = session

        result = get_mcp_market_record_by_id(999)
        assert result is None


class TestCheckMcpMarketNameExists:
    """Test check_mcp_market_name_exists."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_name_exists(self, mock_session):
        session = MockSession()
        session.first = lambda: MagicMock()
        mock_session.return_value = session

        assert check_mcp_market_name_exists("existing") is True

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_name_not_exists(self, mock_session):
        session = MockSession()
        session.first = lambda: None
        mock_session.return_value = session

        assert check_mcp_market_name_exists("new") is False


class TestUpdateMcpMarketRecord:
    """Test update_mcp_market_record."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_update_partial_fields(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        update_mcp_market_record(
            market_id=1, user_id="uid",
            mcp_name="new-name", description="new-desc",
        )

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_update_all_fields(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        update_mcp_market_record(
            market_id=1, user_id="uid",
            mcp_name="n", description="d", tags=["a"],
            registry_json={"key": "v"}, mcp_server="http://srv",
            config_json={"cfg": "val"}, transport_type="url",
        )


class TestDeleteMcpMarketRecord:
    """Test delete_mcp_market_record_by_id (soft delete)."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_soft_delete(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        delete_mcp_market_record_by_id(market_id=1, user_id="uid")


class TestListMcpMarketRecordsByTenantAndUser:
    """Test list_mcp_market_records_by_tenant_and_user."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_list(self, mock_session):
        row = MagicMock()
        row.market_id = 1
        row.tenant_id = "tid"
        row.user_id = "uid"
        session = MockSession()
        session.all = lambda: [row]
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_records_by_tenant_and_user("tid", "uid")
        assert len(result) == 1

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_empty(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_records_by_tenant_and_user("tid", "uid")
        assert len(result) == 0


class TestIncrementMcpMarketDownloadCount:
    """Test increment_mcp_market_download_count."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_increment(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        increment_mcp_market_download_count(1)


class TestGetMcpMarketTagStats:
    """Test get_mcp_market_tag_stats."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_tag_stats(self, mock_session):
        row = MagicMock()
        row.tag = "python"
        row.count = 5
        session = MockSession()
        session.all = lambda: [row]
        mock_session.return_value = session

        result = get_mcp_market_tag_stats()
        assert len(result) == 1
        assert result[0]["tag"] == "python"

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_tag_stats_empty(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        mock_session.return_value = session

        result = get_mcp_market_tag_stats()
        assert len(result) == 0


class TestGetMcpMarketTagStatsByTenant:
    """Test get_mcp_market_tag_stats_by_tenant."""

    @patch('backend.database.market_mcp_db.get_db_session')
    def test_tag_stats_scoped(self, mock_session):
        row = MagicMock()
        row.tag = "python"
        row.count = 3
        session = MockSession()
        session.all = lambda: [row]
        mock_session.return_value = session

        result = get_mcp_market_tag_stats_by_tenant("tid")
        assert len(result) == 1
