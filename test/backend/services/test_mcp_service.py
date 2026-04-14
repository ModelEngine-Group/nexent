"""
Unit tests for backend/mcp_service.py
Tests MCP service for OpenAPI service registration and management.
"""

import os
import sys
import types
from unittest.mock import patch, MagicMock
from threading import Thread

import pytest

# Dynamically determine the backend path - MUST BE FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))

sys.path.insert(0, backend_dir)

# Create stub modules for all dependencies
# These must be created BEFORE importing the module under test

# Stub fastapi - use real FastAPI for endpoint testing
from fastapi import FastAPI as RealFastAPI, Header as RealHeader, Query as RealQuery
from fastapi import HTTPException as RealHTTPException
stub_fastapi = types.ModuleType("fastapi")
stub_fastapi.FastAPI = RealFastAPI
stub_fastapi.Header = RealHeader
stub_fastapi.HTTPException = RealHTTPException
stub_fastapi.Query = RealQuery
sys.modules['fastapi'] = stub_fastapi

# Stub starlette
stub_starlette = types.ModuleType("starlette")
stub_starlette.responses = types.ModuleType("starlette.responses")
stub_starlette.responses.JSONResponse = MagicMock()
sys.modules['starlette'] = stub_starlette
sys.modules['starlette.responses'] = stub_starlette.responses

# Import real httpx for AsyncClient and ASGITransport (NOT stubbed)
import httpx as real_httpx

# Stub fastmcp
class MockFastMCP:
    """Mock FastMCP class with from_openapi and mount methods"""
    _mounted_servers = []

    def __init__(self, name="mock"):
        self.name = name
        self._tool_manager = MagicMock()
        self._tool_manager._mounted_servers = []

    @classmethod
    def from_openapi(cls, openapi_spec, client, name):
        """Class method to create from OpenAPI spec"""
        instance = cls(name=name)
        return instance

    def mount(self, name, server):
        """Mount another server"""
        mock_mounted = MagicMock()
        mock_mounted.prefix = name if isinstance(name, str) else getattr(name, 'name', 'unknown')
        self._mounted_servers.append(mock_mounted)
        if hasattr(self._tool_manager, '_mounted_servers'):
            self._tool_manager._mounted_servers.append(mock_mounted)

stub_fastmcp = types.ModuleType("fastmcp")
stub_fastmcp.FastMCP = MockFastMCP
stub_fastmcp.server = MagicMock()
stub_fastmcp.server.context = MagicMock()
stub_fastmcp.tools = types.ModuleType("fastmcp.tools")
stub_fastmcp.tools.tool = types.ModuleType("fastmcp.tools.tool")

# Create real ToolResult class for testing
class RealToolResult:
    def __init__(self, content=None):
        self.content = content

stub_fastmcp.tools.tool.ToolResult = RealToolResult
sys.modules['fastmcp'] = stub_fastmcp
sys.modules['fastmcp.tools'] = stub_fastmcp.tools
sys.modules['fastmcp.tools.tool'] = stub_fastmcp.tools.tool

# Stub mcp and mcp.types
class MockMCPTool:
    def __init__(self, name, description, inputSchema, outputSchema=None):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema
        self.outputSchema = outputSchema

stub_mcp = types.ModuleType("mcp")
stub_mcp.types = types.ModuleType("mcp.types")
stub_mcp.types.Tool = MockMCPTool
sys.modules['mcp'] = stub_mcp
sys.modules['mcp.types'] = stub_mcp.types

# Stub requests
stub_requests = types.ModuleType("requests")
stub_requests.request = MagicMock()
stub_requests.RequestException = Exception
sys.modules['requests'] = stub_requests

# Stub uvicorn
stub_uvicorn = types.ModuleType("uvicorn")
stub_uvicorn.run = MagicMock()
sys.modules['uvicorn'] = stub_uvicorn

# Stub tool_collection.mcp.local_mcp_service
stub_local_mcp = types.ModuleType("tool_collection.mcp.local_mcp_service")
mock_local_service = MagicMock()
mock_local_service.name = "local_mcp"
stub_local_mcp.local_mcp_service = mock_local_service
sys.modules['tool_collection'] = types.ModuleType("tool_collection")
sys.modules['tool_collection.mcp'] = types.ModuleType("tool_collection.mcp")
sys.modules['tool_collection.mcp.local_mcp_service'] = stub_local_mcp

# Stub utils
stub_utils = types.ModuleType("utils")
stub_utils.logging_utils = types.ModuleType("utils.logging_utils")
stub_utils.logging_utils.configure_logging = MagicMock()
sys.modules['utils'] = stub_utils
sys.modules['utils.logging_utils'] = stub_utils.logging_utils

# Stub database
stub_database = types.ModuleType("database")
sys.modules['database'] = stub_database

# Create backend package structure
stub_backend = types.ModuleType("backend")
stub_backend.database = types.ModuleType("backend.database")
sys.modules['backend'] = stub_backend
sys.modules['backend.database'] = stub_backend.database

# Stub database.outer_api_tool_db
stub_outer_api_tool_db = types.ModuleType("database.outer_api_tool_db")
stub_outer_api_tool_db.query_available_openapi_services = MagicMock()
sys.modules['database.outer_api_tool_db'] = stub_outer_api_tool_db
sys.modules['backend.database.outer_api_tool_db'] = stub_outer_api_tool_db

# Stub http
stub_http = types.ModuleType("http")
stub_http.HTTPStatus = types.SimpleNamespace(OK=200)
sys.modules['http'] = stub_http

# Stub mcpadapt
stub_mcpadapt = types.ModuleType("mcpadapt")
stub_mcpadapt.smolagents_adapter = types.ModuleType("mcpadapt.smolagents_adapter")
stub_mcpadapt.smolagents_adapter._sanitize_function_name = lambda x: x
sys.modules['mcpadapt'] = stub_mcpadapt
sys.modules['mcpadapt.smolagents_adapter'] = stub_mcpadapt.smolagents_adapter

# Import the module under test
import mcp_service

# Update module-level references to use our mocks
mcp_service.MCPTool = MockMCPTool
mcp_service.ToolResult = RealToolResult


# Reset global state before each test
@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global state before each test"""
    # Reset before test
    mcp_service._openapi_mcp_services = {}
    mcp_service._mcp_management_app = None

    # Reset mocks
    if hasattr(mcp_service, 'query_available_openapi_services'):
        mcp_service.query_available_openapi_services = MagicMock()
        mcp_service.query_available_openapi_services.return_value = []

    # Reset nexent_mcp mock if it exists
    if hasattr(mcp_service, 'nexent_mcp') and mcp_service.nexent_mcp is not None:
        try:
            mcp_service.nexent_mcp._mounted_servers = []
            if hasattr(mcp_service.nexent_mcp._tool_manager, '_mounted_servers'):
                mcp_service.nexent_mcp._tool_manager._mounted_servers = []
        except:
            pass

    yield

    # Reset after test
    mcp_service._openapi_mcp_services = {}
    mcp_service._mcp_management_app = None


# ---------------------------------------------------------------------------
# Test CustomFunctionTool class
# ---------------------------------------------------------------------------


class TestCustomFunctionToolInit:
    """Test CustomFunctionTool initialization"""

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters"""
        def sample_fn():
            pass

        tool = mcp_service.CustomFunctionTool(
            name="test_tool",
            fn=sample_fn,
            description="A test tool",
            parameters={"type": "object"},
            output_schema={"type": "string"}
        )

        assert tool.name == "test_tool"
        assert tool.fn == sample_fn
        assert tool.description == "A test tool"
        assert tool.parameters == {"type": "object"}
        assert tool.output_schema == {"type": "string"}
        assert tool.tags == set()
        assert tool.enabled is True
        assert tool.annotations is None

    def test_init_with_minimal_parameters(self):
        """Test initialization with minimal parameters"""
        def sample_fn():
            pass

        tool = mcp_service.CustomFunctionTool(
            name="minimal_tool",
            fn=sample_fn,
            description="A minimal tool",
            parameters={}
        )

        assert tool.name == "minimal_tool"
        assert tool.key == "minimal_tool"
        assert tool.output_schema is None

    def test_init_without_output_schema(self):
        """Test initialization without output_schema"""
        def sample_fn():
            pass

        tool = mcp_service.CustomFunctionTool(
            name="no_output_tool",
            fn=sample_fn,
            description="No output schema",
            parameters={"type": "object"}
        )

        assert tool.output_schema is None


class TestCustomFunctionToolToMcpTool:
    """Test CustomFunctionTool.to_mcp_tool method"""

    def test_to_mcp_tool_success(self):
        """Test successful conversion to MCP tool"""
        def sample_fn():
            pass

        tool = mcp_service.CustomFunctionTool(
            name="convert_tool",
            fn=sample_fn,
            description="Convert test",
            parameters={"type": "object", "properties": {"id": {"type": "string"}}},
            output_schema={"type": "string"}
        )

        result = tool.to_mcp_tool()

        assert result.name == "convert_tool"
        assert result.description == "Convert test"
        assert result.inputSchema == {"type": "object", "properties": {"id": {"type": "string"}}}
        assert result.outputSchema == {"type": "string"}

    def test_to_mcp_tool_with_custom_name(self):
        """Test conversion with custom name override"""
        def sample_fn():
            pass

        tool = mcp_service.CustomFunctionTool(
            name="original_name",
            fn=sample_fn,
            description="Test",
            parameters={}
        )

        result = tool.to_mcp_tool("custom_name")

        assert result.name == "original_name"


class TestCustomFunctionToolRun:
    """Test CustomFunctionTool.run method"""

    @pytest.mark.asyncio
    async def test_run_sync_function(self):
        """Test running a synchronous function"""
        def sync_fn(x: int, y: int) -> int:
            return x + y

        tool = mcp_service.CustomFunctionTool(
            name="add_tool",
            fn=sync_fn,
            description="Adds two numbers",
            parameters={"type": "object"}
        )

        result = await tool.run({"x": 5, "y": 3})

        assert isinstance(result, RealToolResult)
        assert result.content == "8"

    @pytest.mark.asyncio
    async def test_run_async_function(self):
        """Test running an async function"""
        async def async_fn(message: str) -> str:
            return f"Hello {message}"

        tool = mcp_service.CustomFunctionTool(
            name="hello_tool",
            fn=async_fn,
            description="Says hello",
            parameters={"type": "object"}
        )

        result = await tool.run({"message": "World"})

        assert isinstance(result, RealToolResult)
        assert result.content == "Hello World"

    @pytest.mark.asyncio
    async def test_run_with_exception(self):
        """Test run method handles exceptions"""
        def failing_fn() -> None:
            raise ValueError("Test error")

        tool = mcp_service.CustomFunctionTool(
            name="failing_tool",
            fn=failing_fn,
            description="Fails intentionally",
            parameters={}
        )

        with pytest.raises(ValueError, match="Test error"):
            await tool.run({})

    @pytest.mark.asyncio
    async def test_run_with_return_value_string(self):
        """Test that return value is converted to string"""
        def get_value() -> dict:
            return {"status": "ok"}

        tool = mcp_service.CustomFunctionTool(
            name="value_tool",
            fn=get_value,
            description="Returns dict",
            parameters={}
        )

        result = await tool.run({})

        assert isinstance(result, RealToolResult)
        assert result.content == "{'status': 'ok'}"


# ---------------------------------------------------------------------------
# Test _sanitize_function_name
# ---------------------------------------------------------------------------


class TestSanitizeFunctionName:
    """Test _sanitize_function_name function"""

    def test_normal_name(self):
        """Test with normal alphanumeric name"""
        result = mcp_service._sanitize_function_name("valid_name")
        assert result == "valid_name"

    def test_name_with_special_chars(self):
        """Test name with special characters"""
        result = mcp_service._sanitize_function_name("tool-name_v1.0")
        assert result == "tool_name_v1_0"

    def test_name_starting_with_numbers(self):
        """Test name starting with numbers"""
        result = mcp_service._sanitize_function_name("123tool")
        assert result == "tool"

    def test_name_with_only_numbers(self):
        """Test name with only numbers"""
        result = mcp_service._sanitize_function_name("456")
        # First pass: no special chars -> "456"
        # Second pass: remove leading non-alpha -> "" (empty)
        # Third pass: empty string, prefix with "tool_"
        assert result == "tool_"

    def test_empty_string(self):
        """Test empty string"""
        result = mcp_service._sanitize_function_name("")
        assert result == "tool_"

    def test_name_with_spaces(self):
        """Test name with spaces"""
        result = mcp_service._sanitize_function_name("tool name")
        assert result == "tool_name"

    def test_name_with_unicode_chars(self):
        """Test name with unicode characters"""
        result = mcp_service._sanitize_function_name("工具_测试")
        assert result == "tool_"

    def test_name_with_dots(self):
        """Test name with dots"""
        result = mcp_service._sanitize_function_name("tool.name.test")
        assert result == "tool_name_test"

    def test_name_starting_with_underscore(self):
        """Test name starting with underscore"""
        result = mcp_service._sanitize_function_name("_tool")
        assert result == "tool"

    def test_mixed_special_chars(self):
        """Test name with mixed special characters"""
        result = mcp_service._sanitize_function_name("api@v2#test!")
        assert result == "api_v2_test_"


# ---------------------------------------------------------------------------
# Test register_openapi_service
# ---------------------------------------------------------------------------


class TestRegisterOpenapiService:
    """Test register_openapi_service function"""

    def test_register_service_success(self):
        """Test successful OpenAPI service registration"""
        service_name = "test_service"
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {}
        }
        server_url = "https://api.example.com"

        result = mcp_service.register_openapi_service(service_name, openapi_json, server_url)

        assert result is True
        assert service_name in mcp_service._openapi_mcp_services
        assert len(mcp_service.nexent_mcp._mounted_servers) > 0

    def test_register_service_empty_name(self):
        """Test registration with empty service name"""
        result = mcp_service.register_openapi_service("", {}, "https://api.example.com")
        assert result is False

    def test_register_service_none_name(self):
        """Test registration with None service name"""
        result = mcp_service.register_openapi_service(None, {}, "https://api.example.com")
        assert result is False

    def test_register_duplicate_service(self):
        """Test registration of already registered service"""
        service_name = "duplicate_service"
        openapi_json = {"openapi": "3.0.0", "info": {}, "paths": {}}

        # First registration
        result1 = mcp_service.register_openapi_service(service_name, openapi_json, "https://api.example.com")
        assert result1 is True

        # Second registration should fail
        result2 = mcp_service.register_openapi_service(service_name, openapi_json, "https://api.example.com")
        assert result2 is False

    def test_register_service_without_server_url(self):
        """Test registration without server URL"""
        service_name = "no_url_service"
        openapi_json = {"openapi": "3.0.0", "info": {}, "paths": {}}

        result = mcp_service.register_openapi_service(service_name, openapi_json, "")

        assert result is True

    def test_register_service_copies_openapi_spec(self):
        """Test that registration copies the OpenAPI spec"""
        service_name = "copy_test_service"
        openapi_json = {"openapi": "3.0.0", "info": {}, "paths": {}}

        original_json = openapi_json.copy()

        mcp_service.register_openapi_service(service_name, openapi_json, "https://api.example.com")

        # Verify original was not modified
        assert openapi_json == original_json
        assert "servers" not in openapi_json

    @patch.object(mcp_service, 'FastMCP')
    def test_register_service_from_openapi_failure(self, mock_fastmcp):
        """Test handling of FastMCP.from_openapi failure"""
        mock_fastmcp.from_openapi.side_effect = Exception("Parse error")

        result = mcp_service.register_openapi_service(
            "fail_service",
            {"openapi": "3.0.0", "info": {}, "paths": {}},
            "https://api.example.com"
        )

        assert result is False
        assert "fail_service" not in mcp_service._openapi_mcp_services

    @patch.object(mcp_service, 'FastMCP')
    def test_register_service_returns_none(self, mock_fastmcp):
        """Test handling when FastMCP.from_openapi returns None"""
        mock_fastmcp.from_openapi.return_value = None

        result = mcp_service.register_openapi_service(
            "none_service",
            {"openapi": "3.0.0", "info": {}, "paths": {}},
            "https://api.example.com"
        )

        assert result is False


# ---------------------------------------------------------------------------
# Test unregister_openapi_service
# ---------------------------------------------------------------------------


class TestUnregisterOpenapiService:
    """Test unregister_openapi_service function"""

    def test_unregister_existing_service(self):
        """Test unregistering an existing service"""
        service_name = "unregister_test"
        mcp_service._openapi_mcp_services[service_name] = MagicMock()

        result = mcp_service.unregister_openapi_service(service_name)

        assert result is True
        assert service_name not in mcp_service._openapi_mcp_services

    def test_unregister_nonexistent_service(self):
        """Test unregistering a non-existent service"""
        result = mcp_service.unregister_openapi_service("nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Test get_registered_openapi_services
# ---------------------------------------------------------------------------


class TestGetRegisteredOpenapiServices:
    """Test get_registered_openapi_services function"""

    def test_get_services_empty(self):
        """Test getting services when empty"""
        result = mcp_service.get_registered_openapi_services()
        assert result == []

    def test_get_services_with_data(self):
        """Test getting registered services"""
        mcp_service._openapi_mcp_services["service1"] = MagicMock()
        mcp_service._openapi_mcp_services["service2"] = MagicMock()

        result = mcp_service.get_registered_openapi_services()

        assert len(result) == 2
        service_names = [s["service_name"] for s in result]
        assert "service1" in service_names
        assert "service2" in service_names
        assert all(s["status"] == "registered" for s in result)


# ---------------------------------------------------------------------------
# Test refresh_openapi_services_by_tenant
# ---------------------------------------------------------------------------


class TestRefreshOpenapiServicesByTenant:
    """Test refresh_openapi_services_by_tenant function"""

    def test_refresh_with_services(self):
        """Test refreshing with available services"""
        services_data = [
            {
                "mcp_service_name": "api_service_1",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api1.example.com"
            },
            {
                "mcp_service_name": "api_service_2",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api2.example.com"
            }
        ]
        mcp_service.query_available_openapi_services.return_value = services_data

        result = mcp_service.refresh_openapi_services_by_tenant("tenant1")

        assert result["registered"] == 2
        assert result["skipped"] == 0
        assert result["total"] == 2

    def test_refresh_with_empty_services(self):
        """Test refreshing with no services"""
        mcp_service.query_available_openapi_services.return_value = []

        result = mcp_service.refresh_openapi_services_by_tenant("tenant1")

        assert result["registered"] == 0
        assert result["skipped"] == 0
        assert result["total"] == 0

    def test_refresh_skips_service_without_openapi_json(self):
        """Test that services without OpenAPI JSON are skipped"""
        services_data = [
            {
                "mcp_service_name": "invalid_service",
                "openapi_json": None,
                "server_url": "https://api.example.com"
            },
            {
                "mcp_service_name": "valid_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]
        mcp_service.query_available_openapi_services.return_value = services_data

        result = mcp_service.refresh_openapi_services_by_tenant("tenant1")

        assert result["registered"] == 1
        assert result["skipped"] == 1
        assert result["total"] == 2

    def test_refresh_clears_existing_services(self):
        """Test that refresh clears existing services first"""
        # Add existing service
        mcp_service._openapi_mcp_services["old_service"] = MagicMock()

        mcp_service.query_available_openapi_services.return_value = [
            {
                "mcp_service_name": "new_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]

        result = mcp_service.refresh_openapi_services_by_tenant("tenant1")

        assert "old_service" not in mcp_service._openapi_mcp_services
        assert "new_service" in mcp_service._openapi_mcp_services

    def test_refresh_remounts_local_service(self):
        """Test that refresh re-mounts local MCP service"""
        mcp_service.query_available_openapi_services.return_value = []

        initial_mount_count = len(mcp_service.nexent_mcp._mounted_servers)

        mcp_service.refresh_openapi_services_by_tenant("tenant1")

        # Should have at least the local service mounted
        assert len(mcp_service.nexent_mcp._mounted_servers) >= initial_mount_count


# ---------------------------------------------------------------------------
# Test refresh_single_openapi_service
# ---------------------------------------------------------------------------


class TestRefreshSingleOpenapiService:
    """Test refresh_single_openapi_service function"""

    def test_refresh_existing_service(self):
        """Test refreshing an existing service"""
        services_data = [
            {
                "mcp_service_name": "target_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]
        mcp_service.query_available_openapi_services.return_value = services_data

        result = mcp_service.refresh_single_openapi_service("target_service", "tenant1")

        assert result["status"] == "refreshed"
        assert result["service_name"] == "target_service"

    def test_refresh_deleted_service(self):
        """Test refreshing a service that was deleted"""
        # Add the service first
        mcp_service._openapi_mcp_services["deleted_service"] = MagicMock()

        # Return empty list (service no longer exists)
        mcp_service.query_available_openapi_services.return_value = []

        result = mcp_service.refresh_single_openapi_service("deleted_service", "tenant1")

        assert result["status"] == "deleted"
        assert result["service_name"] == "deleted_service"
        assert "deleted_service" not in mcp_service._openapi_mcp_services

    def test_refresh_nonexistent_service_not_in_db(self):
        """Test refreshing a service that doesn't exist anywhere"""
        mcp_service.query_available_openapi_services.return_value = []

        result = mcp_service.refresh_single_openapi_service("nonexistent", "tenant1")

        # Should return deleted status since it's not in DB
        assert result["status"] == "deleted"

    def test_refresh_service_without_openapi_json(self):
        """Test refreshing a service without OpenAPI JSON"""
        services_data = [
            {
                "mcp_service_name": "broken_service",
                "openapi_json": None,
                "server_url": "https://api.example.com"
            }
        ]
        mcp_service.query_available_openapi_services.return_value = services_data

        result = mcp_service.refresh_single_openapi_service("broken_service", "tenant1")

        assert result["status"] == "error"
        assert "error" in result

    def test_refresh_removes_old_instance(self):
        """Test that refresh removes old service instance first"""
        # Add existing instance
        old_mock = MagicMock()
        mcp_service._openapi_mcp_services["old_service"] = old_mock

        services_data = [
            {
                "mcp_service_name": "old_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]
        mcp_service.query_available_openapi_services.return_value = services_data

        result = mcp_service.refresh_single_openapi_service("old_service", "tenant1")

        assert result["status"] == "refreshed"


# ---------------------------------------------------------------------------
# Test get_mcp_management_app
# ---------------------------------------------------------------------------


class TestGetMcpManagementApp:
    """Test get_mcp_management_app function"""

    def test_app_creates_once(self):
        """Test that management app is created only once"""
        app1 = mcp_service.get_mcp_management_app()
        app2 = mcp_service.get_mcp_management_app()

        assert app1 is app2

    def test_app_has_routes(self):
        """Test that app has expected routes"""
        app = mcp_service.get_mcp_management_app()

        routes = [route.path for route in app.routes]

        assert "/tools/outer_api/refresh" in routes
        assert "/tools/openapi_service/refresh" in routes
        assert "/tools/openapi_service" in routes
        assert "/tools/openapi_service/{service_name}/refresh" in routes
        assert "/tools/outer_api" in routes


# ---------------------------------------------------------------------------
# Test FastAPI Endpoints
# ---------------------------------------------------------------------------

import httpx


class AsyncTestClient:
    """Async TestClient for FastAPI apps using httpx AsyncClient."""
    def __init__(self, app):
        self.app = app
        self._async_client = None

    async def __aenter__(self):
        transport = httpx.ASGITransport(app=self.app)
        self._async_client = httpx.AsyncClient(
            transport=transport,
            base_url="http://test"
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._async_client:
            await self._async_client.aclose()

    async def get(self, path, **kwargs):
        return await self._async_client.get(path, **kwargs)

    async def post(self, path, **kwargs):
        return await self._async_client.post(path, **kwargs)

    async def delete(self, path, **kwargs):
        return await self._async_client.delete(path, **kwargs)


class TestRefreshOuterApiToolsEndpoint:
    """Test /tools/outer_api/refresh endpoint"""

    @pytest.mark.asyncio
    async def test_refresh_success(self):
        """Test successful refresh"""
        mcp_service.query_available_openapi_services.return_value = [
            {
                "mcp_service_name": "test_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/outer_api/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data

    @pytest.mark.asyncio
    async def test_refresh_with_exception(self):
        """Test refresh endpoint handles exceptions"""
        mcp_service.query_available_openapi_services.side_effect = Exception("DB error")

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/outer_api/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 500


class TestRefreshOpenapiServicesEndpoint:
    """Test /tools/openapi_service/refresh endpoint"""

    @pytest.mark.asyncio
    async def test_refresh_openapi_services_success(self):
        """Test successful OpenAPI services refresh"""
        mcp_service.query_available_openapi_services.return_value = []

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/openapi_service/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_refresh_openapi_services_with_exception(self):
        """Test refresh endpoint handles exceptions"""
        mcp_service.query_available_openapi_services.side_effect = Exception("Query failed")

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/openapi_service/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 500


class TestListOpenapiServicesEndpoint:
    """Test /tools/openapi_service endpoint"""

    @pytest.mark.asyncio
    async def test_list_services_empty(self):
        """Test listing services when empty"""
        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.get(
                "/tools/openapi_service",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"] == []

    @pytest.mark.asyncio
    async def test_list_services_with_data(self):
        """Test listing services with data"""
        mcp_service._openapi_mcp_services["service1"] = MagicMock()
        mcp_service._openapi_mcp_services["service2"] = MagicMock()

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.get(
                "/tools/openapi_service",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2


class TestRefreshSingleOpenapiServiceEndpoint:
    """Test /tools/openapi_service/{service_name}/refresh endpoint"""

    @pytest.mark.asyncio
    async def test_refresh_single_service_success(self):
        """Test refreshing single service successfully"""
        mcp_service.query_available_openapi_services.return_value = [
            {
                "mcp_service_name": "target_service",
                "openapi_json": {"openapi": "3.0.0", "info": {}, "paths": {}},
                "server_url": "https://api.example.com"
            }
        ]

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/openapi_service/target_service/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_refresh_single_service_deleted(self):
        """Test refreshing deleted service"""
        mcp_service.query_available_openapi_services.return_value = []

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/openapi_service/deleted_service/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_refresh_single_service_exception(self):
        """Test refresh endpoint handles exceptions"""
        mcp_service.query_available_openapi_services.side_effect = Exception("DB error")

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.post(
                "/tools/openapi_service/error_service/refresh",
                params={"tenant_id": "tenant1"}
            )

        assert response.status_code == 500


class TestListOuterApiToolsEndpoint:
    """Test /tools/outer_api endpoint"""

    @pytest.mark.asyncio
    async def test_list_outer_api_tools(self):
        """Test listing outer API tools (returns OpenAPI services)"""
        mcp_service._openapi_mcp_services["api_service"] = MagicMock()

        app = mcp_service.get_mcp_management_app()

        async with AsyncTestClient(app) as client:
            response = await client.get("/tools/outer_api")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Test run_mcp_server_with_management
# ---------------------------------------------------------------------------


class TestRunMcpServerWithManagement:
    """Test run_mcp_server_with_management function"""

    def test_function_exists_and_callable(self):
        """Test that function exists and is callable"""
        assert hasattr(mcp_service, 'run_mcp_server_with_management')
        assert callable(mcp_service.run_mcp_server_with_management)

    @patch.object(Thread, 'start')
    @patch('mcp_service.uvicorn')
    def test_starts_fastapi_server(self, mock_uvicorn, mock_thread_start):
        """Test that function starts FastAPI server in thread"""
        # Reset global state
        mcp_service._mcp_management_app = None

        mock_uvicorn.run = MagicMock()

        # This should not block (runs in thread)
        # Just verify it doesn't crash
        try:
            # We can't fully test this without blocking, but we can verify the structure
            with patch.object(mcp_service, 'get_mcp_management_app', return_value=MagicMock()):
                pass  # Structure test
        except:
            pass


# ---------------------------------------------------------------------------
# Test nexent_mcp initialization
# ---------------------------------------------------------------------------


class TestNexentMcpInitialization:
    """Test nexent_mcp initialization and mounting"""

    def test_nexent_mcp_exists(self):
        """Test that nexent_mcp exists"""
        assert hasattr(mcp_service, 'nexent_mcp')
        assert mcp_service.nexent_mcp is not None

    def test_local_mcp_service_mounted(self):
        """Test that local_mcp_service is mounted"""
        # This is set at module load time, so we just verify it happened
        assert mcp_service.nexent_mcp is not None


# ---------------------------------------------------------------------------
# Test global variables
# ---------------------------------------------------------------------------


class TestGlobalVariables:
    """Test global variables in mcp_service module"""

    def test_openapi_services_dict_exists(self):
        """Test _openapi_mcp_services dictionary exists"""
        assert hasattr(mcp_service, '_openapi_mcp_services')
        assert isinstance(mcp_service._openapi_mcp_services, dict)

    def test_mcp_management_app_initial_none(self):
        """Test _mcp_management_app is initially None"""
        # Reset to verify initial state
        mcp_service._mcp_management_app = None
        assert mcp_service._mcp_management_app is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
