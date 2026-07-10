"""
Unit tests for backend/database/market_review_db.py
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
def _as_dict_review(obj):
    """Convert an object to a dict, handling both real objects and MagicMock."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}


client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = _as_dict_review
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
    def __hash__(self): return 0
    def desc(self): return MagicMock()
    def ilike(self, key): return MagicMock()
    def any(self, val): return MagicMock()


class _MockMcpMarketReview:
    """Mock ORM model for McpMarketReview."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


for _col in [
    'review_id', 'market_id', 'mcp_name', 'tenant_id', 'user_id',
    'delete_flag', 'description', 'tags', 'transport_type',
    'review_status', 'review_type', 'mcp_server', 'registry_json',
    'config_json', 'source', 'created_by', 'updated_by',
]:
    setattr(_MockMcpMarketReview, _col, _MockColumn())

db_models_mock = MagicMock()
db_models_mock.McpMarketReview = _MockMcpMarketReview
sys.modules['database.db_models'] = db_models_mock

from backend.database.market_review_db import (
    create_mcp_market_review,
    get_mcp_market_review_by_id,
    list_mcp_market_review_records,
    list_mcp_market_review_records_by_tenant_and_user,
    update_mcp_market_review_status,
    update_mcp_market_review_market_id,
    list_mcp_market_review_records_by_market_id,
)

# Override as_dict in the module to avoid MagicProxy descriptor bug in mock 3.15.1
import backend.database.market_review_db as _market_review_db_mod
_market_review_db_mod.as_dict = _as_dict_review


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


class TestCreateMcpMarketReview:
    """Test create_mcp_market_review."""

    @patch('backend.database.market_review_db.get_db_session')
    @patch('backend.database.market_review_db.filter_property', side_effect=lambda d, m: d)
    def test_create(self, mock_filter, mock_get_session):
        session = MockSession()
        session.add = MagicMock(side_effect=lambda obj: setattr(obj, 'review_id', 42))
        session.flush = MagicMock()
        session.query = MagicMock(return_value=MockSession())
        mock_get_session.return_value = session

        result = create_mcp_market_review(
            mcp_data={"mcp_name": "svc1"},
            tenant_id="tid", user_id="uid",
        )
        assert result == 42


class TestGetMcpMarketReviewById:
    """Test get_mcp_market_review_by_id."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_found(self, mock_session):
        row = MagicMock()
        row.review_id = 10
        row.mcp_name = "svc1"
        row.delete_flag = "N"

        session = MockSession()
        session.first = lambda: row
        mock_session.return_value = session

        result = get_mcp_market_review_by_id(10, tenant_id="tid")
        assert result is not None
        assert result.get("review_id") == 10

    @patch('backend.database.market_review_db.get_db_session')
    def test_not_found(self, mock_session):
        session = MockSession()
        session.first = lambda: None
        mock_session.return_value = session

        result = get_mcp_market_review_by_id(999)
        assert result is None

    @patch('backend.database.market_review_db.get_db_session')
    def test_found_no_tenant_scope(self, mock_session):
        row = MagicMock()
        row.review_id = 10
        row.tenant_id = "other_tid"
        row.delete_flag = "N"

        session = MockSession()
        session.first = lambda: row
        mock_session.return_value = session

        # Without tenant scope, across all tenants
        result = get_mcp_market_review_by_id(10, tenant_id=None)
        assert result is not None


class TestListMcpMarketReviewRecords:
    """Test list_mcp_market_review_records."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_empty(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        session.limit = lambda x: MockSession()
        session.order_by = lambda *a: MockSession()
        mock_session.return_value = session

        result = list_mcp_market_review_records(tenant_id="tid")
        assert result["count"] == 0


class TestListMcpMarketReviewRecordsByTenantAndUser:
    """Test list_mcp_market_review_records_by_tenant_and_user."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_includes_approved(self, mock_session):
        row = MagicMock()
        row.review_id = 1
        row.tenant_id = "tid"
        row.user_id = "uid"
        session = MockSession()
        session.all = lambda: [row]
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_review_records_by_tenant_and_user(
            "tid", "uid", include_approved=True,
        )
        assert len(result) == 1

    @patch('backend.database.market_review_db.get_db_session')
    def test_excludes_approved(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_review_records_by_tenant_and_user(
            "tid", "uid", include_approved=False,
        )
        assert len(result) == 0


class TestUpdateMcpMarketReviewStatus:
    """Test update_mcp_market_review_status."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_update_status(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        update_mcp_market_review_status(
            review_id=10, tenant_id="tid",
            user_id="uid", review_status="approved",
        )

    @patch('backend.database.market_review_db.get_db_session')
    def test_update_status_no_tenant(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        update_mcp_market_review_status(
            review_id=10, tenant_id=None,
            user_id="su_uid", review_status="rejected",
        )


class TestUpdateMcpMarketReviewMarketId:
    """Test update_mcp_market_review_market_id."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_link_market_id(self, mock_session):
        session = MockSession()
        session.update = MagicMock()
        mock_session.return_value = session

        update_mcp_market_review_market_id(
            review_id=10, market_id=100, user_id="uid",
        )


class TestListMcpMarketReviewRecordsByMarketId:
    """Test list_mcp_market_review_records_by_market_id."""

    @patch('backend.database.market_review_db.get_db_session')
    def test_list(self, mock_session):
        row = MagicMock()
        row.review_id = 1
        row.market_id = 100
        session = MockSession()
        session.all = lambda: [row]
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_review_records_by_market_id(100)
        assert len(result) == 1

    @patch('backend.database.market_review_db.get_db_session')
    def test_empty(self, mock_session):
        session = MockSession()
        session.all = lambda: []
        session.order_by = lambda *a: session
        mock_session.return_value = session

        result = list_mcp_market_review_records_by_market_id(999)
        assert len(result) == 0
