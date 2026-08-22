"""
Unit tests for backend/database/outer_api_tool_db.py

Tests CRUD operations for OpenAPI services (MCP service level).
"""

import sys
import pytest
from unittest.mock import MagicMock

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

client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

db_models_mock = MagicMock()
db_models_mock.OuterApiService = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

from backend.database.outer_api_tool_db import (
    create_openapi_service,
    upsert_openapi_service,
    query_services_by_tenant,
    query_available_services,
    query_service_by_name,
    query_service_by_id,
    update_service,
    delete_service,
    delete_service_by_id,
    delete_all_services,
    query_available_openapi_services,
    query_openapi_services_by_tenant,
    delete_openapi_service,
    create_openapi_service_with_tools,
    sync_openapi_service,
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


class MockOuterApiService:
    """Mock OuterApiService instance for testing."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.delete_flag = getattr(self, 'delete_flag', 'N')
        self.is_available = getattr(self, 'is_available', True)


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def _setup_mock_context(monkeypatch, session):
    """Helper to setup mock get_db_session context manager."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.outer_api_tool_db.get_db_session", lambda: mock_ctx)
    return mock_ctx


def _setup_mock_service(monkeypatch, mock_session, service_attrs=None):
    """Helper to setup complete mock environment for service operations."""
    session, query = mock_session
    _setup_mock_context(monkeypatch, session)
    monkeypatch.setattr(
        "backend.database.outer_api_tool_db.as_dict",
        lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj)
    monkeypatch.setattr(
        "backend.database.outer_api_tool_db.filter_property",
        lambda data, model: data)

    class MockServiceClass:
        tenant_id = MagicMock()
        mcp_service_name = MagicMock()
        delete_flag = MagicMock()
        id = MagicMock()

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(
        "backend.database.outer_api_tool_db.OuterApiService", MockServiceClass)

    if service_attrs:
        return MockServiceClass(**service_attrs)
    return MockServiceClass


class TestCreateOpenapiService:
    """Tests for create_openapi_service function."""

    def test_create_service_success(self, monkeypatch, mock_session):
        """Test successful service creation."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        _setup_mock_service(monkeypatch, mock_session)

        openapi_json = {"openapi": "3.0.0", "paths": {"/test": {}}}
        result = create_openapi_service(
            service_name="test_service",
            openapi_json=openapi_json,
            server_url="https://api.example.com",
            tenant_id="tenant1",
            user_id="user1"
        )

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert result["mcp_service_name"] == "test_service"
        assert result["server_url"] == "https://api.example.com"
        assert result["tenant_id"] == "tenant1"
        assert result["created_by"] == "user1"
        assert result["updated_by"] == "user1"
        assert result["is_available"] is True

    def test_create_service_with_description(self, monkeypatch, mock_session):
        """Test service creation with description."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        _setup_mock_service(monkeypatch, mock_session)

        result = create_openapi_service(
            service_name="described_service",
            openapi_json={},
            server_url="https://api.example.com",
            tenant_id="tenant1",
            user_id="user1",
            description="A test service description"
        )

        assert result["description"] == "A test service description"

    def test_create_service_with_headers(self, monkeypatch, mock_session):
        """Test service creation with headers_template."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        _setup_mock_service(monkeypatch, mock_session)

        headers = {"Authorization": "Bearer {{token}}", "X-API-Key": "{{api_key}}"}
        result = create_openapi_service(
            service_name="header_service",
            openapi_json={},
            server_url="https://api.example.com",
            tenant_id="tenant1",
            user_id="user1",
            headers_template=headers
        )

        assert result["headers_template"] == headers


class TestUpsertOpenapiService:
    """Tests for upsert_openapi_service function."""

    def test_upsert_create_new_service(self, monkeypatch, mock_session):
        """Test upsert creates new service when not exists."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_service(monkeypatch, mock_session)

        result = upsert_openapi_service(
            service_name="new_service",
            openapi_json={"openapi": "3.0.0"},
            server_url="https://api.example.com",
            tenant_id="tenant1",
            user_id="user1"
        )

        session.add.assert_called_once()
        assert result["mcp_service_name"] == "new_service"

    def test_upsert_update_existing_service(self, monkeypatch, mock_session):
        """Test upsert updates existing service."""
        session, query = mock_session
        session.flush = MagicMock()

        existing_service = MockOuterApiService(
            id=1,
            mcp_service_name="existing_service",
            openapi_json={"old": "json"},
            server_url="https://old.example.com",
            tenant_id="tenant1",
            delete_flag='N',
            is_available=True,
            created_by="creator",
            updated_by="creator"
        )
        mock_first = MagicMock()
        mock_first.return_value = existing_service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.filter_property",
            lambda data, model: data)

        result = upsert_openapi_service(
            service_name="existing_service",
            openapi_json={"new": "json"},
            server_url="https://new.example.com",
            tenant_id="tenant1",
            user_id="updater"
        )

        assert existing_service.openapi_json == {"new": "json"}
        assert existing_service.server_url == "https://new.example.com"
        assert existing_service.updated_by == "updater"
        assert result["mcp_service_name"] == "existing_service"


class TestQueryServicesByTenant:
    """Tests for query_services_by_tenant function."""

    def test_query_services_found(self, monkeypatch, mock_session):
        """Test query returns services for tenant."""
        session, query = mock_session

        service1 = MockOuterApiService(
            id=1, mcp_service_name="service1", tenant_id="tenant1", delete_flag='N')
        service2 = MockOuterApiService(
            id=2, mcp_service_name="service2", tenant_id="tenant1", delete_flag='N')

        mock_all = MagicMock()
        mock_all.return_value = [service1, service2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_services_by_tenant("tenant1")

        assert len(results) == 2
        assert results[0]["mcp_service_name"] == "service1"
        assert results[1]["mcp_service_name"] == "service2"

    def test_query_services_empty(self, monkeypatch, mock_session):
        """Test query returns empty list when no services."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_services_by_tenant("empty_tenant")

        assert len(results) == 0


class TestQueryAvailableServices:
    """Tests for query_available_services function."""

    def test_query_available_services(self, monkeypatch, mock_session):
        """Test query returns only available services."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="available_service",
            tenant_id="tenant1", delete_flag='N', is_available=True)

        mock_all = MagicMock()
        mock_all.return_value = [service]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_available_services("tenant1")

        assert len(results) == 1
        assert results[0]["is_available"] is True

    def test_query_available_services_empty(self, monkeypatch, mock_session):
        """Test query returns empty when no available services."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_available_services("tenant1")

        assert len(results) == 0


class TestQueryServiceByName:
    """Tests for query_service_by_name function."""

    def test_query_by_name_found(self, monkeypatch, mock_session):
        """Test query returns service when found."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="specific_service",
            tenant_id="tenant1", delete_flag='N')

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_service_by_name("specific_service", "tenant1")

        assert result is not None
        assert result["mcp_service_name"] == "specific_service"

    def test_query_by_name_not_found(self, monkeypatch, mock_session):
        """Test query returns None when not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_service_by_name("nonexistent", "tenant1")

        assert result is None


class TestQueryServiceById:
    """Tests for query_service_by_id function."""

    def test_query_by_id_found(self, monkeypatch, mock_session):
        """Test query returns service by ID when found."""
        session, query = mock_session

        service = MockOuterApiService(
            id=42, mcp_service_name="service_by_id",
            tenant_id="tenant1", delete_flag='N')

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_service_by_id(42, "tenant1")

        assert result is not None
        assert result["id"] == 42

    def test_query_by_id_not_found(self, monkeypatch, mock_session):
        """Test query returns None when ID not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = query_service_by_id(999, "tenant1")

        assert result is None


class TestUpdateService:
    """Tests for update_service function."""

    def test_update_service_success(self, monkeypatch, mock_session):
        """Test successful service update."""
        session, query = mock_session
        session.flush = MagicMock()

        service = MockOuterApiService(
            id=1, mcp_service_name="old_service",
            description="old_desc", server_url="https://old.com",
            tenant_id="tenant1",
            delete_flag='N', updated_by="old_user")

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = update_service(
            service_name="old_service",
            service_data={"description": "new_desc", "server_url": "https://new.com"},
            tenant_id="tenant1",
            user_id="updater"
        )

        assert result is not None
        assert service.description == "new_desc"
        assert service.server_url == "https://new.com"
        assert service.updated_by == "updater"

    def test_update_service_not_found(self, monkeypatch, mock_session):
        """Test update returns None when service not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = update_service(
            service_name="nonexistent",
            service_data={"description": "new"},
            tenant_id="tenant1",
            user_id="user1"
        )

        assert result is None

    def test_update_service_ignores_extra_fields(self, monkeypatch, mock_session):
        """Test update ignores fields not in model."""
        session, query = mock_session
        session.flush = MagicMock()

        service = MockOuterApiService(
            id=1, mcp_service_name="service",
            tenant_id="tenant1", delete_flag='N')

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        result = update_service(
            service_name="service",
            service_data={"extra_field": "should_be_ignored"},
            tenant_id="tenant1",
            user_id="user1"
        )

        assert result is not None
        assert not hasattr(service, 'extra_field')


class TestDeleteService:
    """Tests for delete_service function (soft delete by name)."""

    def test_delete_service_success(self, monkeypatch, mock_session):
        """Test successful soft delete by name."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="to_delete",
            tenant_id="tenant1", delete_flag='N', updated_by="old_user")

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_service("to_delete", "tenant1", "deleter")

        assert result is True
        assert service.delete_flag == 'Y'
        assert service.updated_by == "deleter"

    def test_delete_service_not_found(self, monkeypatch, mock_session):
        """Test delete returns False when service not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_service("nonexistent", "tenant1", "user1")

        assert result is False


class TestDeleteServiceById:
    """Tests for delete_service_by_id function."""

    def test_delete_service_by_id_success(self, monkeypatch, mock_session):
        """Test successful soft delete by ID."""
        session, query = mock_session

        service = MockOuterApiService(
            id=42, mcp_service_name="to_delete_by_id",
            tenant_id="tenant1", delete_flag='N', updated_by="old_user")

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_service_by_id(42, "tenant1", "deleter")

        assert result is True
        assert service.delete_flag == 'Y'
        assert service.updated_by == "deleter"

    def test_delete_service_by_id_not_found(self, monkeypatch, mock_session):
        """Test delete by ID returns False when not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_service_by_id(999, "tenant1", "user1")

        assert result is False


class TestDeleteAllServices:
    """Tests for delete_all_services function."""

    def test_delete_all_services_success(self, monkeypatch, mock_session):
        """Test successful deletion of all services."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_update.return_value = 5
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_all_services("tenant1", "deleter")

        assert result == 5
        mock_update.assert_called_once()

    def test_delete_all_services_none_exist(self, monkeypatch, mock_session):
        """Test deletion returns 0 when no services exist."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_update.return_value = 0
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_all_services("empty_tenant", "deleter")

        assert result == 0


class TestBackwardCompatibilityAliases:
    """Tests for backward compatibility alias functions."""

    def test_query_available_openapi_services(self, monkeypatch, mock_session):
        """Test query_available_openapi_services alias."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="alias_service",
            tenant_id="tenant1", delete_flag='N', is_available=True)

        mock_all = MagicMock()
        mock_all.return_value = [service]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_available_openapi_services("tenant1")

        assert len(results) == 1

    def test_query_openapi_services_by_tenant(self, monkeypatch, mock_session):
        """Test query_openapi_services_by_tenant alias."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="tenant_service",
            tenant_id="tenant1", delete_flag='N')

        mock_all = MagicMock()
        mock_all.return_value = [service]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)
        monkeypatch.setattr(
            "backend.database.outer_api_tool_db.as_dict",
            lambda obj: obj.__dict__)

        results = query_openapi_services_by_tenant("tenant1")

        assert len(results) == 1

    def test_delete_openapi_service_alias(self, monkeypatch, mock_session):
        """Test delete_openapi_service alias."""
        session, query = mock_session

        service = MockOuterApiService(
            id=1, mcp_service_name="alias_delete",
            tenant_id="tenant1", delete_flag='N')

        mock_first = MagicMock()
        mock_first.return_value = service
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_context(monkeypatch, session)

        result = delete_openapi_service("alias_delete", "tenant1", "deleter")

        assert result is True
        assert service.delete_flag == 'Y'

    def test_create_openapi_service_with_tools(self, monkeypatch, mock_session):
        """Test create_openapi_service_with_tools alias."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        _setup_mock_service(monkeypatch, mock_session)

        result = create_openapi_service_with_tools(
            service_name="aliased_service",
            openapi_json={"openapi": "3.0.0"},
            server_url="https://api.example.com",
            tenant_id="tenant1",
            user_id="user1",
            service_description="Description via alias"
        )

        session.add.assert_called_once()
        assert result["mcp_service_name"] == "aliased_service"
        assert result["description"] == "Description via alias"

    def test_sync_openapi_service(self, monkeypatch, mock_session):
        """Test sync_openapi_service alias."""
        session, query = mock_session
        session.add = MagicMock()
        session.flush = MagicMock()

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        _setup_mock_service(monkeypatch, mock_session)

        result = sync_openapi_service(
            service_name="sync_alias_service",
            openapi_json={"openapi": "3.0.0"},
            server_url="https://api.example.com",
            tools_data=[{"name": "ignored_tool"}],
            tenant_id="tenant1",
            user_id="user1"
        )

        session.add.assert_called_once()
        assert result["mcp_service_name"] == "sync_alias_service"


class TestDeprecatedFunctions:
    """Tests for deprecated functions that raise NotImplementedError."""

    def test_create_outer_api_tool_deprecated(self):
        """Test create_outer_api_tool raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            create_outer_api_tool({}, "tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_batch_create_outer_api_tools_deprecated(self):
        """Test batch_create_outer_api_tools raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            batch_create_outer_api_tools([], "tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_query_outer_api_tools_by_tenant_deprecated(self):
        """Test query_outer_api_tools_by_tenant raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            query_outer_api_tools_by_tenant("tenant1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_query_available_outer_api_tools_deprecated(self):
        """Test query_available_outer_api_tools raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            query_available_outer_api_tools("tenant1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_query_outer_api_tool_by_id_deprecated(self):
        """Test query_outer_api_tool_by_id raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            query_outer_api_tool_by_id(1, "tenant1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_query_outer_api_tool_by_name_deprecated(self):
        """Test query_outer_api_tool_by_name raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            query_outer_api_tool_by_name("name", "tenant1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_update_outer_api_tool_deprecated(self):
        """Test update_outer_api_tool raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            update_outer_api_tool(1, {}, "tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_delete_outer_api_tool_deprecated(self):
        """Test delete_outer_api_tool raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            delete_outer_api_tool(1, "tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_delete_all_outer_api_tools_deprecated(self):
        """Test delete_all_outer_api_tools raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            delete_all_outer_api_tools("tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()

    def test_sync_outer_api_tools_deprecated(self):
        """Test sync_outer_api_tools raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            sync_outer_api_tools([], "tenant1", "user1")
        assert "deprecated" in str(exc_info.value).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
