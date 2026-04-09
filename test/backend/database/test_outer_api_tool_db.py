"""
Unit tests for backend/database/outer_api_tool_db.py
Tests CRUD operations for outer API tools (OpenAPI to MCP conversion).
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock consts module first
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
consts_mock.const.DEFAULT_TENANT_ID = "default_tenant"

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock database client module
client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock db_models module
db_models_mock = MagicMock()
db_models_mock.OuterApiTool = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Import the module under test
from backend.database.outer_api_tool_db import (
    create_outer_api_tool,
    batch_create_outer_api_tools,
    query_outer_api_tools_by_tenant,
    query_available_outer_api_tools,
    query_outer_api_tool_by_id,
    query_outer_api_tool_by_name,
    update_outer_api_tool,
    delete_outer_api_tool,
    delete_all_outer_api_tools,
    sync_outer_api_tools,
)


class MockOuterApiTool:
    """Mock OuterApiTool instance for testing"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        # Set default values if not provided
        self.delete_flag = getattr(self, 'delete_flag', 'N')
        self.is_available = getattr(self, 'is_available', True)


@pytest.fixture
def mock_session():
    """Create a mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


class TestCreateOuterApiTool:
    """Tests for create_outer_api_tool function"""

    def test_create_outer_api_tool_success(self, monkeypatch, mock_session):
        """Test successful creation of outer API tool"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: {k: v for k, v in data.items() if k in ['name', 'description', 'url', 'tenant_id', 'created_by', 'updated_by', 'is_available']})

        # Mock OuterApiTool class
        def create_mock_tool(**kwargs):
            return MockOuterApiTool(**kwargs)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", create_mock_tool)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {
            "name": "test_tool",
            "description": "Test tool description",
            "url": "https://api.example.com/test",
            "method": "GET"
        }

        result = create_outer_api_tool(tool_data, "tenant1", "user1")

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert result["name"] == "test_tool"
        assert result["tenant_id"] == "tenant1"
        assert result["created_by"] == "user1"
        assert result["updated_by"] == "user1"

    def test_create_outer_api_tool_with_is_available_false(self, monkeypatch, mock_session):
        """Test creation with is_available=False explicitly set"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        def create_mock_tool(**kwargs):
            return MockOuterApiTool(**kwargs)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", create_mock_tool)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {
            "name": "disabled_tool",
            "url": "https://api.example.com/disabled",
            "is_available": False
        }

        result = create_outer_api_tool(tool_data, "tenant1", "user1")

        assert result["is_available"] is False
        assert result["name"] == "disabled_tool"

    def test_create_outer_api_tool_with_all_fields(self, monkeypatch, mock_session):
        """Test creation with all optional fields"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        def create_mock_tool(**kwargs):
            return MockOuterApiTool(**kwargs)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", create_mock_tool)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {
            "name": "full_tool",
            "description": "Full tool description",
            "method": "POST",
            "url": "https://api.example.com/full",
            "headers_template": {"Authorization": "Bearer {{token}}"},
            "query_template": {"page": 1},
            "body_template": {"data": "test"},
            "input_schema": {"type": "object"},
            "is_available": True
        }

        result = create_outer_api_tool(tool_data, "tenant1", "user1")

        assert result["name"] == "full_tool"
        assert result["method"] == "POST"
        assert result["headers_template"] == {"Authorization": "Bearer {{token}}"}


class TestBatchCreateOuterApiTools:
    """Tests for batch_create_outer_api_tools function"""

    def test_batch_create_success(self, monkeypatch, mock_session):
        """Test successful batch creation"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        def create_mock_tool(**kwargs):
            return MockOuterApiTool(**kwargs)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", create_mock_tool)

        tools_data = [
            {"name": "tool1", "url": "https://api.example.com/1"},
            {"name": "tool2", "url": "https://api.example.com/2"},
        ]

        results = batch_create_outer_api_tools(tools_data, "tenant1", "user1")

        assert len(results) == 2
        assert session.add.call_count == 2
        session.flush.assert_called_once()

    def test_batch_create_empty_list(self, monkeypatch, mock_session):
        """Test batch creation with empty list"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        results = batch_create_outer_api_tools([], "tenant1", "user1")

        assert len(results) == 0
        session.add.assert_not_called()

    def test_batch_create_with_is_available(self, monkeypatch, mock_session):
        """Test batch creation with is_available field"""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        def create_mock_tool(**kwargs):
            return MockOuterApiTool(**kwargs)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", create_mock_tool)

        tools_data = [
            {"name": "enabled_tool", "url": "https://api.example.com/enabled", "is_available": True},
            {"name": "disabled_tool", "url": "https://api.example.com/disabled", "is_available": False},
        ]

        results = batch_create_outer_api_tools(tools_data, "tenant1", "user1")

        assert len(results) == 2


class TestQueryOuterApiToolsByTenant:
    """Tests for query_outer_api_tools_by_tenant function"""

    def test_query_by_tenant_success(self, monkeypatch, mock_session):
        """Test successful query by tenant"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="tool1", tenant_id="tenant1", delete_flag='N')
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_outer_api_tools_by_tenant("tenant1")

        assert len(results) == 1
        assert results[0]["name"] == "tool1"
        query.filter.assert_called_once()

    def test_query_by_tenant_empty(self, monkeypatch, mock_session):
        """Test query with no results"""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_outer_api_tools_by_tenant("nonexistent_tenant")

        assert len(results) == 0


class TestQueryAvailableOuterApiTools:
    """Tests for query_available_outer_api_tools function"""

    def test_query_available_success(self, monkeypatch, mock_session):
        """Test successful query of available tools"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="available_tool", tenant_id="tenant1",
            delete_flag='N', is_available=True)
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_available_outer_api_tools("tenant1")

        assert len(results) == 1
        assert results[0]["is_available"] is True

    def test_query_available_empty(self, monkeypatch, mock_session):
        """Test query with no available tools"""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_available_outer_api_tools("tenant1")

        assert len(results) == 0


class TestQueryOuterApiToolById:
    """Tests for query_outer_api_tool_by_id function"""

    def test_query_by_id_found(self, monkeypatch, mock_session):
        """Test successful query by ID"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="tool1", tenant_id="tenant1", delete_flag='N')
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_outer_api_tool_by_id(1, "tenant1")

        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "tool1"

    def test_query_by_id_not_found(self, monkeypatch, mock_session):
        """Test query by ID with no result"""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_outer_api_tool_by_id(999, "tenant1")

        assert result is None


class TestQueryOuterApiToolByName:
    """Tests for query_outer_api_tool_by_name function"""

    def test_query_by_name_found(self, monkeypatch, mock_session):
        """Test successful query by name"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="specific_tool", tenant_id="tenant1", delete_flag='N')
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_outer_api_tool_by_name("specific_tool", "tenant1")

        assert result is not None
        assert result["name"] == "specific_tool"

    def test_query_by_name_not_found(self, monkeypatch, mock_session):
        """Test query by name with no result"""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_outer_api_tool_by_name("nonexistent", "tenant1")

        assert result is None


class TestUpdateOuterApiTool:
    """Tests for update_outer_api_tool function"""

    def test_update_tool_success(self, monkeypatch, mock_session):
        """Test successful update"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="old_name", description="old_desc",
            tenant_id="tenant1", delete_flag='N', updated_by="old_user")
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {"name": "new_name", "description": "new_desc"}
        result = update_outer_api_tool(1, tool_data, "tenant1", "user1")

        assert result is not None
        assert mock_tool.name == "new_name"
        assert mock_tool.description == "new_desc"
        assert mock_tool.updated_by == "user1"

    def test_update_tool_not_found(self, monkeypatch, mock_session):
        """Test update with non-existent tool"""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        tool_data = {"name": "new_name"}
        result = update_outer_api_tool(999, tool_data, "tenant1", "user1")

        assert result is None

    def test_update_tool_with_extra_fields(self, monkeypatch, mock_session):
        """Test update ignores fields not in model"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="tool1", description="desc",
            tenant_id="tenant1", delete_flag='N')
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {
            "name": "new_name",
            "extra_field": "should_be_ignored",
            "another_extra": 123
        }
        result = update_outer_api_tool(1, tool_data, "tenant1", "user1")

        assert result is not None
        assert not hasattr(mock_tool, 'extra_field')

    def test_update_tool_partial_update(self, monkeypatch, mock_session):
        """Test partial update (only some fields)"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="original", description="original_desc",
            method="GET", tenant_id="tenant1", delete_flag='N')
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        tool_data = {"method": "POST"}
        result = update_outer_api_tool(1, tool_data, "tenant1", "user1")

        assert result is not None
        assert mock_tool.name == "original"
        assert mock_tool.description == "original_desc"
        assert mock_tool.method == "POST"


class TestDeleteOuterApiTool:
    """Tests for delete_outer_api_tool function"""

    def test_delete_tool_success(self, monkeypatch, mock_session):
        """Test successful soft delete"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="tool1", tenant_id="tenant1",
            delete_flag='N', updated_by="old_user")
        mock_first = MagicMock()
        mock_first.return_value = mock_tool
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        result = delete_outer_api_tool(1, "tenant1", "user1")

        assert result is True
        assert mock_tool.delete_flag == 'Y'
        assert mock_tool.updated_by == "user1"

    def test_delete_tool_not_found(self, monkeypatch, mock_session):
        """Test delete with non-existent tool"""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        result = delete_outer_api_tool(999, "tenant1", "user1")

        assert result is False


class TestDeleteAllOuterApiTools:
    """Tests for delete_all_outer_api_tools function"""

    def test_delete_all_success(self, monkeypatch, mock_session):
        """Test successful deletion of all tools"""
        session, query = mock_session

        mock_update = MagicMock()
        mock_update.return_value = 5
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        result = delete_all_outer_api_tools("tenant1", "user1")

        assert result == 5
        mock_update.assert_called_once()

    def test_delete_all_no_tools(self, monkeypatch, mock_session):
        """Test deletion when no tools exist"""
        session, query = mock_session

        mock_update = MagicMock()
        mock_update.return_value = 0
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        result = delete_all_outer_api_tools("empty_tenant", "user1")

        assert result == 0


class TestSyncOuterApiTools:
    """Tests for sync_outer_api_tools function"""

    def test_sync_create_new_tools(self, monkeypatch, mock_session):
        """Test sync creates new tools that don't exist"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="existing_tool", tenant_id="tenant1", delete_flag='N')
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = [
            {"name": "existing_tool", "url": "https://api.example.com/existing"},
            {"name": "new_tool", "url": "https://api.example.com/new"},
        ]

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert result["created"] == 1
        assert result["updated"] == 1
        assert result["deleted"] == 0

    def test_sync_delete_old_tools(self, monkeypatch, mock_session):
        """Test sync deletes tools not in new data"""
        session, query = mock_session

        mock_tool1 = MockOuterApiTool(
            id=1, name="old_tool", tenant_id="tenant1", delete_flag='N')
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool1]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = []  # Empty list means all tools should be deleted

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["deleted"] == 1
        assert mock_tool1.delete_flag == 'Y'
        assert mock_tool1.updated_by == "user1"

    def test_sync_update_existing_tool(self, monkeypatch, mock_session):
        """Test sync updates existing tool attributes"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="tool_to_update", description="old_desc",
            tenant_id="tenant1", delete_flag='N', is_available=False)
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = [{
            "name": "tool_to_update",
            "description": "new_desc",
            "url": "https://api.example.com/updated"
        }]

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert mock_tool.description == "new_desc"
        assert mock_tool.updated_by == "user1"
        assert mock_tool.is_available is True

    def test_sync_with_no_name_tools(self, monkeypatch, mock_session):
        """Test sync handles tools without name field"""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        # Tool without name - should not be counted in new_tool_names
        tools_data = [{"url": "https://api.example.com/no_name"}]

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["deleted"] == 0

    def test_sync_empty_tenant(self, monkeypatch, mock_session):
        """Test sync on tenant with no existing tools"""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = [{"name": "brand_new", "url": "https://api.example.com/new"}]

        result = sync_outer_api_tools(tools_data, "new_tenant", "user1")

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["deleted"] == 0

    def test_sync_updates_multiple_attributes(self, monkeypatch, mock_session):
        """Test sync updates multiple tool attributes"""
        session, query = mock_session

        mock_tool = MockOuterApiTool(
            id=1, name="multi_update", description="old",
            method="GET", tenant_id="tenant1", delete_flag='N',
            is_available=True, url="https://api.example.com/old")
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = [{
            "name": "multi_update",
            "description": "new description",
            "method": "POST",
            "url": "https://api.example.com/new",
            "headers_template": {"Content-Type": "application/json"}
        }]

        sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert mock_tool.description == "new description"
        assert mock_tool.method == "POST"
        assert mock_tool.url == "https://api.example.com/new"

    def test_sync_delete_multiple_tools(self, monkeypatch, mock_session):
        """Test sync deletes multiple tools not in new data"""
        session, query = mock_session

        mock_tool1 = MockOuterApiTool(
            id=1, name="to_delete_1", tenant_id="tenant1", delete_flag='N')
        mock_tool2 = MockOuterApiTool(
            id=2, name="to_delete_2", tenant_id="tenant1", delete_flag='N')
        mock_all = MagicMock()
        mock_all.return_value = [mock_tool1, mock_tool2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        # Keep only one tool
        tools_data = [{"name": "to_keep", "url": "https://api.example.com/keep"}]

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert result["deleted"] == 2
        assert mock_tool1.delete_flag == 'Y'
        assert mock_tool2.delete_flag == 'Y'

    def test_sync_new_tool_inherits_defaults(self, monkeypatch, mock_session):
        """Test sync new tool inherits tenant_id, created_by, updated_by, is_available"""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        # Create a mock OuterApiTool class that has proper class attributes for query
        class MockOuterApiToolClass:
            tenant_id = MagicMock()
            delete_flag = MagicMock()
            name = MagicMock()

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.OuterApiTool", MockOuterApiToolClass)

        tools_data = [{"name": "new_defaulted", "url": "https://api.example.com/new"}]

        result = sync_outer_api_tools(tools_data, "tenant1", "user1")

        assert result["created"] == 1
        # Verify session.add was called (new tool created)
        assert session.add.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
