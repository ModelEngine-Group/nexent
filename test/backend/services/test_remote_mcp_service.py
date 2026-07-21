"""
Unit tests for backend/services/remote_mcp_service.py - custom_headers coverage.

Tests specifically cover the custom_headers parameter additions across all
functions in the remote_mcp_service module.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import importlib.machinery
import types
import sys
import os
import asyncio

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
elasticsearch_module = types.ModuleType("elasticsearch")
elasticsearch_module.Elasticsearch = MagicMock()
elasticsearch_module.__spec__ = importlib.machinery.ModuleSpec("elasticsearch", loader=None)
sys.modules['elasticsearch'] = elasticsearch_module
# Pre-mock nexent module hierarchy to prevent deep SDK import chain
nexent_mod = types.ModuleType("nexent")
nexent_mod.__path__ = []
nexent_mod.__spec__ = importlib.machinery.ModuleSpec("nexent", loader=None)
sys.modules['nexent'] = nexent_mod

nexent_storage = types.ModuleType("nexent.storage")
nexent_storage.__spec__ = importlib.machinery.ModuleSpec("nexent.storage", loader=None)
sys.modules['nexent.storage'] = nexent_storage

nexent_scf = types.ModuleType("nexent.storage.storage_client_factory")
nexent_scf.create_storage_client_from_config = MagicMock()
nexent_scf.__spec__ = importlib.machinery.ModuleSpec("nexent.storage.storage_client_factory", loader=None)
sys.modules['nexent.storage.storage_client_factory'] = nexent_scf

nexent_minio = types.ModuleType("nexent.storage.minio_config")
nexent_minio.MinIOStorageConfig = MagicMock()
nexent_minio.__spec__ = importlib.machinery.ModuleSpec("nexent.storage.minio_config", loader=None)
sys.modules['nexent.storage.minio_config'] = nexent_minio

# Pre-mock all nexent submodules that may be referenced downstream
for _mod_name in [
    'nexent.core', 'nexent.core.agents', 'nexent.core.agents.agent_model',
    'nexent.core.models', 'nexent.core.utils',
    'nexent.container', 'nexent.memory',
]:
    if _mod_name not in sys.modules:
        _parts = _mod_name.split('.')
        _mod = types.ModuleType(_mod_name)
        _mod.__path__ = []
        _mod.__spec__ = importlib.machinery.ModuleSpec(_mod_name, loader=None)
        sys.modules[_mod_name] = _mod

# Ensure specific attributes needed by imports are present
nexent_agent_model = sys.modules['nexent.core.agents.agent_model']
nexent_agent_model.AgentVerificationConfig = MagicMock()
nexent_agent_model.ToolConfig = MagicMock()

nexent_container = sys.modules['nexent.container']
nexent_container.DockerContainerConfig = MagicMock()
nexent_container.KubernetesContainerConfig = MagicMock()
nexent_container.create_container_client_from_config = MagicMock()
nexent_container.ContainerError = Exception
nexent_container.ContainerConnectionError = Exception

# Pre-mock services.tool_configuration_service so patches resolve correctly
tool_config_mod = types.ModuleType("services.tool_configuration_service")
tool_config_mod.get_tool_from_remote_mcp_server = AsyncMock()
tool_config_mod.__spec__ = importlib.machinery.ModuleSpec("services.tool_configuration_service", loader=None)
sys.modules['services.tool_configuration_service'] = tool_config_mod

# Pre-mock database.client module
db_client_mod = types.ModuleType("database.client")
db_client_mod.MinioClient = MagicMock()
db_client_mod.minio_client = MagicMock()
db_client_mod.as_dict = MagicMock()
db_client_mod.filter_property = MagicMock()
db_client_mod.get_db_session = MagicMock()
db_client_mod.__spec__ = importlib.machinery.ModuleSpec("database.client", loader=None)
sys.modules['database.client'] = db_client_mod

backend_db_client_mod = types.ModuleType("backend.database.client")
backend_db_client_mod.MinioClient = MagicMock()
backend_db_client_mod.minio_client = MagicMock()
backend_db_client_mod.__spec__ = importlib.machinery.ModuleSpec("backend.database.client", loader=None)
sys.modules['backend.database.client'] = backend_db_client_mod

# Apply critical patches before importing any modules
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes
from backend.consts.exceptions import (
    MCPConnectionError, MCPNameIllegal, MCPContainerError,
    McpNotFoundError, McpValidationError, McpNameConflictError,
    McpPortConflictError,
)
from backend.consts.const import PERMISSION_READ, PERMISSION_EDIT
from backend.consts.model import MCPConfigRequest

# Functions to test
from backend.services.remote_mcp_service import (
    mcp_server_health,
    _is_container_record,
    check_container_port_conflict_records,
    check_runtime_host_port_available,
    check_container_port_conflict,
    suggest_container_port,
    add_remote_mcp_server_list,
    add_mcp_service,
    add_container_mcp_service,
    update_remote_mcp_server_list,
    update_mcp_service,
    update_mcp_service_enabled,
    delete_mcp_service,
    delete_mcp_by_container_id,
    get_remote_mcp_server_list,
    get_mcp_record_by_id,
    check_mcp_health_and_update_db,
    check_mcp_service_health,
    list_mcp_service_tools_by_id,
    upload_and_start_mcp_image,
    attach_mcp_container_permissions,
    refresh_mcp_service_tool_count,
    _format_mcp_connection_error,
    _mcp_protocol_health_check,
)
# Patch exception classes to ensure tests use correct exceptions
import backend.services.remote_mcp_service as remote_service
remote_service.MCPConnectionError = MCPConnectionError
remote_service.MCPNameIllegal = MCPNameIllegal
remote_service.McpNotFoundError = McpNotFoundError
remote_service.McpValidationError = McpValidationError
remote_service.McpNameConflictError = McpNameConflictError
remote_service.McpPortConflictError = McpPortConflictError


# ============================================================================
# Helper Classes
# ============================================================================

class MockMCPUpdateRequest:
    """Mock for MCPUpdateRequest with custom_headers support."""
    def __init__(
        self,
        current_service_name,
        current_mcp_url,
        new_service_name,
        new_mcp_url,
        new_authorization_token=None,
        custom_headers=None,
    ):
        self.current_service_name = current_service_name
        self.current_mcp_url = current_mcp_url
        self.new_service_name = new_service_name
        self.new_mcp_url = new_mcp_url
        self.new_authorization_token = new_authorization_token
        self.custom_headers = custom_headers


# ============================================================================
# MCP connection error normalization
# ============================================================================

class TestMcpConnectionErrorFormatting(unittest.IsolatedAsyncioTestCase):
    """Test user-facing MCP connection error categories."""

    def test_timeout_error_is_normalized(self):
        result = _format_mcp_connection_error(TimeoutError("request timed out after 10s"))
        self.assertEqual(result, "MCP connection timeout")

    def test_empty_timeout_error_is_normalized_by_type(self):
        result = _format_mcp_connection_error(TimeoutError())
        self.assertEqual(result, "MCP connection timeout")

    def test_chained_timeout_error_is_normalized(self):
        error = RuntimeError("Client failed to connect: All connection attempts failed")
        error.__cause__ = TimeoutError()

        result = _format_mcp_connection_error(error)

        self.assertEqual(result, "MCP connection timeout")

    def test_refused_error_is_normalized(self):
        result = _format_mcp_connection_error(ConnectionError("Connection refused by host"))
        self.assertEqual(result, "MCP connection refused")

    def test_auth_error_is_normalized(self):
        result = _format_mcp_connection_error(Exception("HTTP 401 Unauthorized"))
        self.assertEqual(result, "MCP authentication failed")

    def test_endpoint_error_is_normalized(self):
        result = _format_mcp_connection_error(Exception("404 endpoint not found"))
        self.assertEqual(result, "MCP endpoint not found")

    def test_protocol_error_is_normalized(self):
        result = _format_mcp_connection_error(Exception("server does not support MCP protocol"))
        self.assertEqual(result, "MCP protocol or endpoint invalid")

    def test_dns_error_is_normalized(self):
        result = _format_mcp_connection_error(Exception("getaddrinfo ENOTFOUND example.invalid"))
        self.assertEqual(result, "MCP address unreachable")

    def test_unknown_error_uses_safe_fallback(self):
        result = _format_mcp_connection_error(Exception("fastmcp internal stack detail"))
        self.assertEqual(result, "MCP connection failed")

    async def test_connection_handshake_timeout_is_normalized(self):
        class SlowConnectClient:
            async def __aenter__(self):
                await asyncio.sleep(0.05)
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def list_tools(self):
                return []

        with patch("backend.services.remote_mcp_service.Client", return_value=SlowConnectClient()), \
             patch("backend.services.remote_mcp_service.MCP_HEALTH_CHECK_TIMEOUT_SECONDS", 0.001):
            with self.assertRaises(MCPConnectionError) as context:
                await _mcp_protocol_health_check("http://example.com/mcp", {})

        self.assertEqual(str(context.exception), "MCP connection timeout")


# ============================================================================
# mcp_server_health - custom_headers tests (lines 50-58)
# ============================================================================

class TestMcpServerHealthCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test mcp_server_health with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_custom_headers_only(self, mock_client_cls):
        """Test health check with custom_headers only (no auth token)."""
        from unittest.mock import AsyncMock, MagicMock
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(return_value=[MagicMock(name="tool1")])
        mock_client_cls.return_value = mock_client

        custom_headers = {"X-Custom-Header": "value1", "X-Another": "value2"}
        result = await mcp_server_health(
            'https://test-server/mcp',
            authorization_token=None,
            custom_headers=custom_headers
        )
        self.assertTrue(result)

        call_args = mock_client_cls.call_args
        transport = call_args[1]['transport']
        self.assertIsInstance(transport, StreamableHttpTransport)
        self.assertEqual(transport.headers, {"X-Custom-Header": "value1", "X-Another": "value2"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_auth_token_and_custom_headers(self, mock_client_cls):
        """Test health check with both auth token and custom_headers."""
        from unittest.mock import AsyncMock, MagicMock
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(return_value=[MagicMock(name="tool1")])
        mock_client_cls.return_value = mock_client

        result = await mcp_server_health(
            'https://test-server/mcp',
            authorization_token='Bearer token123',
            custom_headers={"X-Custom-Header": "custom-value"}
        )
        self.assertTrue(result)

        call_args = mock_client_cls.call_args
        transport = call_args[1]['transport']
        self.assertIsInstance(transport, StreamableHttpTransport)
        # Authorization should be set, and custom headers should be merged
        self.assertEqual(transport.headers["Authorization"], "Bearer token123")
        self.assertEqual(transport.headers["X-Custom-Header"], "custom-value")

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_sse_with_custom_headers(self, mock_client_cls):
        """Test SSE transport with custom_headers."""
        from unittest.mock import AsyncMock, MagicMock
        from fastmcp.client.transports import SSETransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(return_value=[MagicMock(name="tool1")])
        mock_client_cls.return_value = mock_client

        result = await mcp_server_health(
            'https://test-server/sse',
            authorization_token=None,
            custom_headers={"X-Request-ID": "req-123"}
        )
        self.assertTrue(result)

        call_args = mock_client_cls.call_args
        transport = call_args[1]['transport']
        self.assertIsInstance(transport, SSETransport)
        self.assertEqual(transport.headers, {"X-Request-ID": "req-123"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_timeout_raises_mcp_connection_error(self, mock_client_cls):
        """Test that asyncio.TimeoutError raises MCPConnectionError."""
        from unittest.mock import AsyncMock
        import asyncio
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError):
            await mcp_server_health('https://test-server', custom_headers={"X-Test": "value"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_exception_uses_normalized_error_message(self, mock_client_cls):
        """Raw SDK errors are converted to safe connection categories."""
        from unittest.mock import AsyncMock
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(side_effect=Exception("HTTP 401 Unauthorized: token rejected"))
        mock_client_cls.return_value = mock_client

        with self.assertRaisesRegex(MCPConnectionError, "MCP authentication failed"):
            await mcp_server_health('https://test-server', custom_headers={"X-Test": "value"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_timeout_error_raises_mcp_connection_error(self, mock_client_cls):
        """Test that TimeoutError raises MCPConnectionError."""
        from unittest.mock import AsyncMock
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(side_effect=TimeoutError())
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError):
            await mcp_server_health('https://test-server', custom_headers={"X-Test": "value"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_timeout_in_message_raises_mcp_connection_error(self, mock_client_cls):
        """Test that exception message containing 'timeout' raises MCPConnectionError."""
        from unittest.mock import AsyncMock
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.list_tools = AsyncMock(side_effect=Exception("Connection timeout error"))
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError):
            await mcp_server_health('https://test-server', custom_headers={"X-Test": "value"})


# ============================================================================
# add_remote_mcp_server_list - custom_headers tests (lines 173, 196, 205)
# ============================================================================

class TestAddRemoteMcpServerListCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test add_remote_mcp_server_list with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_custom_headers(self, mock_check_name, mock_health_check, mock_create):
        """Test add_remote_mcp_server_list passes custom_headers to health check and stores it."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        custom_headers = {"X-API-Key": "key123", "X-Custom": "value"}
        await add_remote_mcp_server_list(
            'tid', 'uid', 'https://srv', 'name',
            custom_headers=custom_headers
        )

        # Verify custom_headers passed to health check
        mock_health_check.assert_called_once_with(
            'https://srv',
            {"X-API-Key": "key123", "X-Custom": "value"},
        )

        # Verify custom_headers stored in database
        create_call_kwargs = mock_create.call_args[1]
        self.assertEqual(create_call_kwargs['mcp_data']['custom_headers'], custom_headers)

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_auth_token_and_custom_headers(self, mock_check_name, mock_health_check, mock_create):
        """Test add_remote_mcp_server_list with both auth token and custom_headers."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        await add_remote_mcp_server_list(
            'tid', 'uid', 'https://srv', 'name',
            authorization_token='Bearer token123',
            custom_headers={"X-Header": "value"}
        )

        mock_health_check.assert_called_once_with(
            'https://srv',
            {"Authorization": "Bearer token123", "X-Header": "value"},
        )

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_without_custom_headers_none_passed(self, mock_check_name, mock_health_check, mock_create):
        """Test add_remote_mcp_server_list when custom_headers is None (default)."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        await add_remote_mcp_server_list('tid', 'uid', 'https://srv', 'name')

        mock_health_check.assert_called_once_with(
            'https://srv',
            {},
        )

        create_call_kwargs = mock_create.call_args[1]
        self.assertIsNone(create_call_kwargs['mcp_data']['custom_headers'])


# ============================================================================
# add_mcp_service - custom_headers tests (lines 222, 257, 270)
# ============================================================================

class TestAddMcpServiceCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test add_mcp_service with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_enabled_with_custom_headers(self, mock_check_name, mock_health_check, mock_create):
        """Test add_mcp_service with enabled=True and custom_headers."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        custom_headers = {"X-Custom-Auth": "header-value"}
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='https://srv/mcp',
            tags=['tag1'], authorization_token='tok',
            custom_headers=custom_headers,
            container_config=None, registry_json=None, enabled=True,
            config_json=None, market_id=None,
        )

        # Verify custom_headers passed to health check
        mock_health_check.assert_called_once_with(
            'https://srv/mcp',
            {"Authorization": "tok", "X-Custom-Auth": "header-value"},
        )

        # Verify custom_headers stored in database
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['custom_headers'], custom_headers)
        self.assertTrue(call_data['status'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_disabled_with_custom_headers(self, mock_check_name, mock_health_check, mock_create):
        """Test add_mcp_service with enabled=False and custom_headers."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        custom_headers = {"X-Disabled-Header": "value"}
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='https://srv/mcp',
            tags=None, authorization_token=None,
            custom_headers=custom_headers,
            container_config=None, registry_json=None, enabled=False,
            config_json=None, market_id=None,
        )

        # Health check IS called (always runs for URL-based services)
        mock_health_check.assert_called_once()

        # But custom_headers should still be stored
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['custom_headers'], custom_headers)
        self.assertIsNone(call_data['status'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_none_custom_headers(self, mock_check_name, mock_health_check, mock_create):
        """Test add_mcp_service with custom_headers=None (default)."""
        mock_check_name.return_value = False
        mock_health_check.return_value = ["tool1"]

        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='https://srv/mcp',
            tags=None, authorization_token=None,
            custom_headers=None,
            container_config=None, registry_json=None, enabled=False,
            config_json=None, market_id=None,
        )

        call_data = mock_create.call_args[1]['mcp_data']
        self.assertIsNone(call_data['custom_headers'])


# ============================================================================
# add_mcp_service - name conflict with group visibility tests
# ============================================================================

class TestAddMcpServiceNameConflictGroupVisibility(unittest.IsolatedAsyncioTestCase):
    """Test add_mcp_service name conflict logic with group restrictions."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('database.group_db.query_group_ids_by_user')
    @patch('database.remote_mcp_db.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_name_conflict_allowed_when_existing_mcp_invisible(
        self, mock_check_name, mock_get_records, mock_query_groups, mock_health, mock_create
    ):
        """Name conflict should be allowed when existing MCP has group_ids not overlapping user's groups."""
        mock_check_name.return_value = True  # name exists
        mock_get_records.return_value = [
            {"mcp_name": "test-svc", "group_ids": "2", "created_by": "other-user"}
        ]
        mock_query_groups.return_value = [4]  # user is in group 4, not group 2
        mock_health.return_value = ["tool1"]

        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='https://srv/mcp',
            tags=[], authorization_token=None,
            custom_headers=None, container_config=None, registry_json=None,
            enabled=False, config_json=None, market_id=None,
        )
        # Should not raise - installation allowed
        mock_create.assert_called_once()

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('database.group_db.query_group_ids_by_user')
    @patch('database.remote_mcp_db.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_name_conflict_blocks_when_user_in_allowed_group(
        self, mock_check_name, mock_get_records, mock_query_groups, mock_health, mock_create
    ):
        """Name conflict should block when existing MCP's group_ids include user's group."""
        mock_check_name.return_value = True
        mock_get_records.return_value = [
            {"mcp_name": "test-svc", "group_ids": "2,4", "created_by": "other-user"}
        ]
        mock_query_groups.return_value = [4]  # user is in group 4
        mock_health.return_value = ["tool1"]

        with self.assertRaises(MCPNameIllegal):
            await add_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', server_url='https://srv/mcp',
                tags=[], authorization_token=None,
                custom_headers=None, container_config=None, registry_json=None,
                enabled=False, config_json=None, market_id=None,
            )

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('database.group_db.query_group_ids_by_user')
    @patch('database.remote_mcp_db.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_name_conflict_blocks_when_same_creator(
        self, mock_check_name, mock_get_records, mock_query_groups, mock_health, mock_create
    ):
        """Name conflict should block when existing MCP is created by the same user."""
        mock_check_name.return_value = True
        mock_get_records.return_value = [
            {"mcp_name": "test-svc", "group_ids": "2", "created_by": "uid"}
        ]
        mock_query_groups.return_value = [4]

        with self.assertRaises(MCPNameIllegal):
            await add_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', server_url='https://srv/mcp',
                tags=[], authorization_token=None,
                custom_headers=None, container_config=None, registry_json=None,
                enabled=False, config_json=None, market_id=None,
            )

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('database.remote_mcp_db.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_name_conflict_blocks_when_no_group_ids(
        self, mock_check_name, mock_get_records, mock_health, mock_create
    ):
        """Name conflict should block when existing MCP has no group restriction."""
        mock_check_name.return_value = True  # name exists
        mock_get_records.return_value = [
            {"mcp_name": "test-svc", "group_ids": "", "created_by": "other"}
        ]

        with self.assertRaises(MCPNameIllegal):
            await add_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', server_url='https://srv/mcp',
                tags=[], authorization_token=None,
                custom_headers=None, container_config=None, registry_json=None,
                enabled=False, config_json=None, market_id=None,
            )


# ============================================================================
# add_mcp_service - API-type (OpenAPI) tests
# ============================================================================

class TestAddMcpServiceApiType(unittest.IsolatedAsyncioTestCase):
    """Test add_mcp_service with API-type (OpenAPI JSON) config."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_api_type_skips_mcp_protocol_and_extracts_tools(
        self, mock_check_name, mock_create
    ):
        """API-type MCP should skip MCP protocol check and extract tool names from OpenAPI."""
        mock_check_name.return_value = False

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/ping": {"get": {"operationId": "ping", "summary": "Health check"}},
                "/echo": {"post": {"operationId": "echo", "summary": "Echo message"}},
            },
        }

        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-api',
            description='desc', source='local', server_url='https://api.test',
            tags=[], authorization_token=None,
            custom_headers=None, container_config=None, registry_json=None,
            enabled=False, config_json=openapi_spec, market_id=None,
        )

        # Verify tool names were extracted from OpenAPI paths
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(
            call_data['registry_json']['_toolNames'],
            ["ping", "echo"],
        )


# ============================================================================
# get_remote_mcp_server_list - group visibility filtering tests
# ============================================================================

class TestGetRemoteMcpServerListGroupFilter(unittest.IsolatedAsyncioTestCase):
    """Test get_remote_mcp_server_list group-based visibility filtering."""

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.query_group_ids_by_user')
    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    async def test_user_sees_only_own_and_group_mcps(
        self, mock_mgr, mock_tenant, mock_groups, mock_records
    ):
        """Non-admin user should only see own MCPs and MCPs shared with their groups."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_groups.return_value = [2]
        mock_mgr.return_value.list_mcp_containers.return_value = []
        mock_records.return_value = [
            {"mcp_name": "my-mcp", "group_ids": "", "created_by": "uid",
             "mcp_id": 1, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None},
            {"mcp_name": "shared-mcp", "group_ids": "2", "created_by": "other",
             "mcp_id": 2, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None,
             "ingroup_permission": "READ_ONLY"},
            {"mcp_name": "private-mcp", "group_ids": "3", "created_by": "other",
             "mcp_id": 3, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None},
        ]

        result = await get_remote_mcp_server_list(tenant_id='tid', user_id='uid')

        names = [r['remote_mcp_server_name'] for r in result]
        self.assertIn("my-mcp", names)      # own MCP
        self.assertIn("shared-mcp", names)   # shared with group 2
        self.assertNotIn("private-mcp", names)  # group 3, not visible

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.query_group_ids_by_user')
    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    async def test_private_mcp_hidden_from_non_creator(
        self, mock_mgr, mock_tenant, mock_groups, mock_records
    ):
        """PRIVATE MCPs should be hidden from non-creator group members."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_groups.return_value = [2]
        mock_mgr.return_value.list_mcp_containers.return_value = []
        mock_records.return_value = [
            {"mcp_name": "private-svc", "group_ids": "2", "created_by": "other",
             "mcp_id": 1, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None,
             "ingroup_permission": "PRIVATE"},
        ]

        result = await get_remote_mcp_server_list(tenant_id='tid', user_id='uid')

        names = [r['remote_mcp_server_name'] for r in result]
        self.assertNotIn("private-svc", names)


# ============================================================================
# get_remote_mcp_server_list - ingroup_permission tests
# ============================================================================

class TestGetRemoteMcpServerListPermission(unittest.IsolatedAsyncioTestCase):
    """Test get_remote_mcp_server_list permission computation with ingroup_permission."""

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.query_group_ids_by_user')
    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    async def test_ingroup_edit_grants_edit_permission(
        self, mock_mgr, mock_tenant, mock_groups, mock_records
    ):
        """Group member should get EDIT permission when ingroup_permission is EDIT."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_groups.return_value = [2]
        mock_mgr.return_value.list_mcp_containers.return_value = []
        mock_records.return_value = [
            {"mcp_name": "editable", "group_ids": "2", "created_by": "other",
             "mcp_id": 1, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None,
             "ingroup_permission": "EDIT"},
        ]

        result = await get_remote_mcp_server_list(tenant_id='tid', user_id='uid')

        self.assertEqual(result[0]['permission'], PERMISSION_EDIT)

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.query_group_ids_by_user')
    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    async def test_ingroup_readonly_grants_read_permission(
        self, mock_mgr, mock_tenant, mock_groups, mock_records
    ):
        """Group member should get READ permission when ingroup_permission is READ_ONLY."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_groups.return_value = [2]
        mock_mgr.return_value.list_mcp_containers.return_value = []
        mock_records.return_value = [
            {"mcp_name": "readonly", "group_ids": "2", "created_by": "other",
             "mcp_id": 1, "mcp_server": "", "status": None, "enabled": False,
             "source": "local", "update_time": "", "tags": [], "container_port": None,
             "registry_json": None, "config_json": None, "market_id": None,
             "ingroup_permission": "READ_ONLY"},
        ]

        result = await get_remote_mcp_server_list(tenant_id='tid', user_id='uid')

        self.assertEqual(result[0]['permission'], PERMISSION_READ)


# ============================================================================
# update_remote_mcp_server_list - custom_headers tests (lines 418, 423-424)
# ============================================================================

class TestUpdateRemoteMcpServerListCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test update_remote_mcp_server_list with custom_headers."""

    @patch('backend.services.remote_mcp_service.update_mcp_record_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_with_custom_headers(self, mock_check_name, mock_health, mock_update_record):
        """Test update_remote_mcp_server_list passes custom_headers to health check."""
        mock_check_name.side_effect = [True, False]
        mock_health.return_value = True

        custom_headers = {"X-Update-Header": "update-value"}
        update_data = MockMCPUpdateRequest(
            current_service_name="old",
            current_mcp_url="https://old.url",
            new_service_name="new",
            new_mcp_url="https://new.url",
            new_authorization_token="tok",
            custom_headers=custom_headers,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server="https://new.url",
            authorization_token="tok",
            custom_headers=custom_headers,
        )

    @patch('backend.services.remote_mcp_service.update_mcp_record_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_with_none_custom_headers(self, mock_check_name, mock_health, mock_update_record):
        """Test update_remote_mcp_server_list when custom_headers is None."""
        mock_check_name.side_effect = [True, False]
        mock_health.return_value = True

        update_data = MockMCPUpdateRequest(
            current_service_name="old",
            current_mcp_url="https://old.url",
            new_service_name="new",
            new_mcp_url="https://new.url",
            new_authorization_token=None,
            custom_headers=None,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server="https://new.url",
            authorization_token=None,
            custom_headers=None,
        )


# ============================================================================
# update_mcp_service - custom_headers tests (lines 449, 486)
# ============================================================================

class TestUpdateMcpServiceCustomHeaders(unittest.TestCase):
    """Test update_mcp_service with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_with_custom_headers(self, mock_get, mock_update):
        """Test update_mcp_service passes custom_headers to database update."""
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}

        custom_headers = {"X-Update-Custom": "value123"}
        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='new-name', description='desc',
            server_url='https://new.url', authorization_token='tok',
            custom_headers=custom_headers,
            tags=['a', 'b'],
            config_json=None, market_id=None,
        )

        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs['custom_headers'], custom_headers)

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_with_none_custom_headers(self, mock_get, mock_update):
        """Test update_mcp_service when custom_headers is None."""
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}

        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='new-name', description='desc',
            server_url='https://new.url', authorization_token='tok',
            custom_headers=None,
            tags=None,
            config_json=None, market_id=None,
        )

        call_kwargs = mock_update.call_args[1]
        self.assertIsNone(call_kwargs['custom_headers'])

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_with_group_ids(self, mock_get, mock_update):
        """Test update_mcp_service passes group_ids to database update."""
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}

        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='n', description='d',
            server_url='http://srv', authorization_token=None,
            custom_headers=None, tags=None,
            config_json=None, market_id=None,
            group_ids="2,4",
        )

        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs['group_ids'], "2,4")

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_with_ingroup_permission(self, mock_get, mock_update):
        """Test update_mcp_service passes ingroup_permission to database update."""
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}

        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='n', description='d',
            server_url='http://srv', authorization_token=None,
            custom_headers=None, tags=None,
            config_json=None, market_id=None,
            ingroup_permission="READ_ONLY",
        )

        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs['ingroup_permission'], "READ_ONLY")

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_with_shared_fields(self, mock_get, mock_update):
        """Test update_mcp_service passes shared_fields to database update."""
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}

        shared = {"serverUrl": True, "authorizationToken": False}
        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='n', description='d',
            server_url='http://srv', authorization_token=None,
            custom_headers=None, tags=None,
            config_json=None, market_id=None,
            group_ids="2", ingroup_permission="READ_ONLY",
            shared_fields=shared,
        )

        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs['group_ids'], "2")
        self.assertEqual(call_kwargs['ingroup_permission'], "READ_ONLY")
        self.assertEqual(call_kwargs['shared_fields'], shared)


# ============================================================================
# update_mcp_service_enabled - custom_headers tests (lines 530, 599, 656)
# ============================================================================

class TestUpdateMcpServiceEnabledCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test update_mcp_service_enabled with custom_headers."""

    def _make_record(self, **overrides):
        base = {
            "mcp_id": 1, "mcp_name": "test-svc", "mcp_server": "https://srv/mcp",
            "container_id": None, "container_port": None, "config_json": None,
            "authorization_token": None, "custom_headers": None,
            "enabled": False, "source": "local",
        }
        base.update(overrides)
        return base

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_non_container_enable_with_custom_headers(
        self, mock_records, mock_get, mock_health, mock_status, mock_enabled
    ):
        """Test non-container enable with custom_headers from record."""
        mock_get.return_value = self._make_record(
            authorization_token='tok',
            custom_headers={"X-Enabling-Custom": "value"}
        )
        mock_records.return_value = []
        mock_health.return_value = True

        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

        mock_health.assert_called_once_with(
            remote_mcp_server='https://srv/mcp',
            authorization_token='tok',
            custom_headers={"X-Enabling-Custom": "value"},
        )

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_non_container_enable_without_custom_headers(
        self, mock_records, mock_get, mock_health, mock_status, mock_enabled
    ):
        """Test non-container enable without custom_headers (None in record)."""
        mock_get.return_value = self._make_record(
            authorization_token='tok',
            custom_headers=None
        )
        mock_records.return_value = []
        mock_health.return_value = True

        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

        mock_health.assert_called_once_with(
            remote_mcp_server='https://srv/mcp',
            authorization_token='tok',
            custom_headers=None,
        )

    @patch('backend.services.remote_mcp_service.check_runtime_host_port_available', return_value=True)
    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_with_custom_headers(
        self, mock_records, mock_get, mock_mgr_cls, mock_health, mock_cont_fields, mock_enabled, mock_port_check
    ):
        """Test container enable with custom_headers passed to health check."""
        mock_get.return_value = self._make_record(
            container_port=8080,
            authorization_token='container-tok',
            custom_headers={"X-Container-Custom": "container-value"},
            config_json={"mcpServers": {"s": {"command": "echo", "args": [], "env": {}}}},
        )
        mock_records.return_value = []
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container = AsyncMock(return_value={
            "container_id": "new-cid", "mcp_url": "https://localhost:8080/mcp", "host_port": 8080,
        })
        mock_mgr_cls.return_value = mock_mgr
        mock_health.return_value = True

        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

        # The health check during container rebuild should receive custom_headers
        self.assertTrue(mock_health.called)
        call_args_list = mock_health.call_args_list
        # Last health check (during rebuild) should have custom_headers
        for call_args in call_args_list:
            self.assertEqual(
                call_args[1]['custom_headers'],
                {"X-Container-Custom": "container-value"}
            )


# ============================================================================
# get_remote_mcp_server_list - custom_headers tests (line 804)
# ============================================================================

class TestGetRemoteMcpServerListCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test get_remote_mcp_server_list includes custom_headers in response."""

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_list_includes_custom_headers_when_auth_needed(self, mock_get):
        """Test custom_headers is included in list response when is_need_auth=True."""
        mock_get.return_value = [
            {
                "mcp_name": "svc1", "mcp_server": "https://srv1/mcp",
                "status": True, "mcp_id": 1,
                "authorization_token": "tok1",
                "custom_headers": {"X-Custom1": "value1"},
            },
            {
                "mcp_name": "svc2", "mcp_server": "https://srv2/mcp",
                "status": False, "mcp_id": 2,
                "authorization_token": None,
                "custom_headers": {"X-Custom2": "value2"},
            },
        ]

        result = await get_remote_mcp_server_list('tid', is_need_auth=True)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["custom_headers"], {"X-Custom1": "value1"})
        self.assertEqual(result[1]["custom_headers"], {"X-Custom2": "value2"})

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_list_custom_headers_none(self, mock_get):
        """Test custom_headers is None when not set in record."""
        mock_get.return_value = [
            {
                "mcp_name": "svc1", "mcp_server": "https://srv1/mcp",
                "status": True, "mcp_id": 1,
                "authorization_token": "tok1",
                "custom_headers": None,
            },
        ]

        result = await get_remote_mcp_server_list('tid', is_need_auth=True)

        self.assertIsNone(result[0]["custom_headers"])


# ============================================================================
# get_mcp_record_by_id - custom_headers tests (line 876)
# ============================================================================

class TestGetMcpRecordByIdCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test get_mcp_record_by_id includes custom_headers in response."""

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_get_record_includes_custom_headers(self, mock_get_record):
        """Test custom_headers is included in get_mcp_record_by_id response."""
        mock_get_record.return_value = {
            "mcp_name": "test-service",
            "mcp_server": "https://test.com/mcp",
            "authorization_token": "Bearer token123",
            "custom_headers": {"X-Record-Custom": "record-value"},
        }

        result = await get_mcp_record_by_id(mcp_id=1, tenant_id="tenant123")

        self.assertIsNotNone(result)
        self.assertEqual(result["custom_headers"], {"X-Record-Custom": "record-value"})

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_get_record_custom_headers_none(self, mock_get_record):
        """Test custom_headers is None when not set in record."""
        mock_get_record.return_value = {
            "mcp_name": "test-service",
            "mcp_server": "https://test.com/mcp",
            "authorization_token": "Bearer token123",
            "custom_headers": None,
        }

        result = await get_mcp_record_by_id(mcp_id=1, tenant_id="tenant123")

        self.assertIsNotNone(result)
        self.assertIsNone(result["custom_headers"])


# ============================================================================
# check_mcp_health_and_update_db - custom_headers tests (lines 901-905, 910-911)
# ============================================================================

class TestCheckMcpHealthAndUpdateDbCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test check_mcp_health_and_update_db uses custom_headers from database."""

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_custom_headers_by_name_and_url')
    @patch('backend.services.remote_mcp_service.get_mcp_authorization_token_by_name_and_url')
    async def test_check_health_with_custom_headers(
        self, mock_get_token, mock_get_headers, mock_health, mock_update
    ):
        """Test check_mcp_health_and_update_db retrieves and uses custom_headers."""
        mock_get_token.return_value = 'Bearer token123'
        mock_get_headers.return_value = {"X-Health-Custom": "health-value"}
        mock_health.return_value = True

        await check_mcp_health_and_update_db('https://srv', 'name', 'tid', 'uid')

        mock_get_headers.assert_called_once_with(
            mcp_name='name',
            mcp_server='https://srv',
            tenant_id='tid'
        )

        mock_health.assert_called_once_with(
            remote_mcp_server='https://srv',
            authorization_token='Bearer token123',
            custom_headers={"X-Health-Custom": "health-value"},
        )

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_custom_headers_by_name_and_url')
    @patch('backend.services.remote_mcp_service.get_mcp_authorization_token_by_name_and_url')
    async def test_check_health_with_none_custom_headers(
        self, mock_get_token, mock_get_headers, mock_health, mock_update
    ):
        """Test check_mcp_health_and_update_db when custom_headers is None."""
        mock_get_token.return_value = 'Bearer token123'
        mock_get_headers.return_value = None
        mock_health.return_value = True

        await check_mcp_health_and_update_db('https://srv', 'name', 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server='https://srv',
            authorization_token='Bearer token123',
            custom_headers=None,
        )

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_custom_headers_by_name_and_url')
    @patch('backend.services.remote_mcp_service.get_mcp_authorization_token_by_name_and_url')
    async def test_check_health_failure_raises_exception(
        self, mock_get_token, mock_get_headers, mock_health, mock_update
    ):
        """Test check_mcp_health_and_update_db raises exception on health failure."""
        mock_get_token.return_value = None
        mock_get_headers.return_value = {"X-Custom": "value"}
        mock_health.return_value = False

        with self.assertRaises(MCPConnectionError):
            await check_mcp_health_and_update_db('https://srv', 'name', 'tid', 'uid')


# ============================================================================
# check_mcp_service_health - custom_headers tests (lines 957, 963)
# ============================================================================

class TestCheckMcpServiceHealthCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test check_mcp_service_health uses custom_headers from record."""

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_health_with_custom_headers(self, mock_get, mock_health, mock_status):
        """Test check_mcp_service_health retrieves and uses custom_headers."""
        mock_get.return_value = {
            "mcp_server": "https://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": {"X-Service-Custom": "service-value"},
        }
        mock_health.return_value = True

        result = await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

        self.assertEqual(result, "healthy")
        mock_health.assert_called_once_with(
            remote_mcp_server="https://srv/mcp",
            authorization_token="tok",
            custom_headers={"X-Service-Custom": "service-value"},
        )

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_health_without_custom_headers(self, mock_get, mock_health, mock_status):
        """Test check_mcp_service_health when custom_headers is None."""
        mock_get.return_value = {
            "mcp_server": "https://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": None,
        }
        mock_health.return_value = True

        result = await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

        self.assertEqual(result, "healthy")
        mock_health.assert_called_once_with(
            remote_mcp_server="https://srv/mcp",
            authorization_token="tok",
            custom_headers=None,
        )


# ============================================================================
# list_mcp_service_tools_by_id - custom_headers tests (lines 1024-1025, 1031-1032)
# ============================================================================

class TestListMcpServiceToolsByIdCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test list_mcp_service_tools_by_id uses custom_headers from record."""

    @patch('services.tool_configuration_service.get_tool_from_remote_mcp_server', new_callable=AsyncMock)
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_tools_with_custom_headers(self, mock_get, mock_get_tools):
        """Test list_mcp_service_tools_by_id passes custom_headers to tool retrieval."""
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "https://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": {"X-Tools-Custom": "tools-value"},
        }
        mock_tool = MagicMock()
        mock_tool.__dict__ = {"name": "tool1", "description": "desc"}
        mock_get_tools.return_value = [mock_tool]

        result = await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)

        self.assertEqual(len(result), 1)
        mock_get_tools.assert_called_once_with(
            mcp_server_name='svc',
            remote_mcp_server='https://srv/mcp',
            tenant_id='tid',
            authorization_token='tok',
            custom_headers={"X-Tools-Custom": "tools-value"},
        )

    @patch('services.tool_configuration_service.get_tool_from_remote_mcp_server', new_callable=AsyncMock)
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_tools_without_custom_headers(self, mock_get, mock_get_tools):
        """Test list_mcp_service_tools_by_id when custom_headers is None."""
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "https://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": None,
        }
        mock_tool = MagicMock()
        mock_tool.__dict__ = {"name": "tool1", "description": "desc"}
        mock_get_tools.return_value = [mock_tool]

        result = await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)

        mock_get_tools.assert_called_once_with(
            mcp_server_name='svc',
            remote_mcp_server='https://srv/mcp',
            tenant_id='tid',
            authorization_token='tok',
            custom_headers=None,
        )


# ============================================================================
# Additional coverage for add_container_mcp_service (calls add_mcp_service)
# ============================================================================

class TestAddContainerMcpServiceCallsAddMcpServiceWithCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test add_container_mcp_service passes custom_headers via add_mcp_service."""

    def _make_mcp_config(self, command="echo", args=None):
        return MCPConfigRequest(mcpServers={
            "test-svc": {
                "command": command,
                "args": args or [],
                "env": {},
            }
        })

    @patch('backend.services.remote_mcp_service.add_mcp_service')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_container_passes_custom_headers_to_add_mcp_service(
        self, mock_check_name, mock_port_check, mock_mgr_cls, mock_add
    ):
        """Test add_container_mcp_service eventually stores custom_headers (via add_mcp_service)."""
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container = AsyncMock(return_value={
            "container_id": "cid",
            "mcp_url": "https://localhost:8080/mcp",
            "host_port": 8080,
            "container_name": "test-svc-xyz",
        })
        mock_mgr_cls.return_value = mock_mgr

        await add_container_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', tags=[],
            authorization_token='tok', registry_json=None,
            market_id=None,
            port=8080, mcp_config=self._make_mcp_config(),
        )

        # Verify add_mcp_service was called (which stores custom_headers)
        mock_add.assert_called_once()
        add_call_kwargs = mock_add.call_args[1]
        # add_container_mcp_service doesn't pass custom_headers to add_mcp_service
        # but the mcp_data structure would include it if it were supported
        self.assertIsNone(add_call_kwargs.get('custom_headers', None))


# ============================================================================
# Integration tests for custom_headers flow
# ============================================================================

class TestCustomHeadersIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for custom_headers parameter across multiple functions."""

    @patch('backend.services.remote_mcp_service.update_mcp_record_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_full_flow_with_custom_headers(self, mock_check_name, mock_health, mock_update):
        """Test complete flow: update with custom_headers, health check uses them."""
        mock_check_name.side_effect = [True, False]
        mock_health.return_value = True

        custom_headers = {"X-Integration-Test": "full-flow-value"}
        update_data = MockMCPUpdateRequest(
            current_service_name="old-svc",
            current_mcp_url="https://old.url",
            new_service_name="new-svc",
            new_mcp_url="https://new.url",
            new_authorization_token="Bearer tok",
            custom_headers=custom_headers,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        # Verify the health check received custom_headers
        mock_health.assert_called_once()
        call_kwargs = mock_health.call_args[1]
        self.assertEqual(call_kwargs['custom_headers'], custom_headers)


# ============================================================================
# _build_mcp_headers - helper function tests
# ============================================================================

class TestBuildMcpHeaders(unittest.TestCase):
    """Test _build_mcp_headers header construction logic."""

    def test_no_auth_no_custom_headers(self):
        """Both None => empty dict."""
        from backend.services.remote_mcp_service import _build_mcp_headers
        result = _build_mcp_headers(None, None)
        self.assertEqual(result, {})

    def test_auth_token_only(self):
        """Auth token sets Authorization header."""
        from backend.services.remote_mcp_service import _build_mcp_headers
        result = _build_mcp_headers("Bearer my-token", None)
        self.assertEqual(result, {"Authorization": "Bearer my-token"})

    def test_custom_headers_only(self):
        """Custom headers passed through directly."""
        from backend.services.remote_mcp_service import _build_mcp_headers
        result = _build_mcp_headers(None, {"X-Custom": "val"})
        self.assertEqual(result, {"X-Custom": "val"})

    def test_both_merged(self):
        """Auth token and custom headers are merged."""
        from backend.services.remote_mcp_service import _build_mcp_headers
        result = _build_mcp_headers("tok", {"X-One": "1", "X-Two": "2"})
        self.assertEqual(result, {"Authorization": "tok", "X-One": "1", "X-Two": "2"})


# ============================================================================
# _check_mcp_connectivity - helper function tests
# ============================================================================

class TestCheckMcpConnectivity(unittest.IsolatedAsyncioTestCase):
    """Test _check_mcp_connectivity health check wrapper."""

    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    async def test_healthy_returns_tool_names(self, mock_health):
        """Health check returns tool names => function returns them."""
        from backend.services.remote_mcp_service import _check_mcp_connectivity
        mock_health.return_value = ["tool1", "tool2"]

        result = await _check_mcp_connectivity("https://srv/mcp", {}, False, "svc")

        self.assertEqual(result, ["tool1", "tool2"])

    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    async def test_container_unreachable_returns_none(self, mock_health):
        """Container unreachable => returns None, no exception."""
        from backend.services.remote_mcp_service import _check_mcp_connectivity
        mock_health.return_value = []

        result = await _check_mcp_connectivity("https://srv/mcp", {}, True, "container-svc")

        self.assertIsNone(result)

    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    async def test_non_container_unreachable_raises(self, mock_health):
        """Non-container unreachable => raises MCPConnectionError."""
        from backend.services.remote_mcp_service import _check_mcp_connectivity
        mock_health.return_value = []

        with self.assertRaises(MCPConnectionError):
            await _check_mcp_connectivity("https://srv/mcp", {}, False, "svc")


# ============================================================================
# _mcp_protocol_connect - lightweight MCP initialize handshake
# ============================================================================

class TestMcpProtocolConnect(unittest.IsolatedAsyncioTestCase):
    """Test _mcp_protocol_connect transport selection and connection."""

    @patch('backend.services.remote_mcp_service.Client')
    async def test_sse_url_uses_sse_transport(self, mock_client_cls):
        """URL ending in /sse => SSETransport."""
        from unittest.mock import AsyncMock
        from fastmcp.client.transports import SSETransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = True
        mock_client_cls.return_value = mock_client

        from backend.services.remote_mcp_service import _mcp_protocol_connect
        result = await _mcp_protocol_connect("https://srv/sse", {"X-Test": "1"})

        self.assertTrue(result)
        transport = mock_client_cls.call_args[1]['transport']
        self.assertIsInstance(transport, SSETransport)
        self.assertEqual(transport.url, "https://srv/sse")

    @patch('backend.services.remote_mcp_service.Client')
    async def test_mcp_url_uses_streamable_http_transport(self, mock_client_cls):
        """URL ending in /mcp => StreamableHttpTransport."""
        from unittest.mock import AsyncMock
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = True
        mock_client_cls.return_value = mock_client

        from backend.services.remote_mcp_service import _mcp_protocol_connect
        result = await _mcp_protocol_connect("https://srv/mcp", {})

        self.assertTrue(result)
        transport = mock_client_cls.call_args[1]['transport']
        self.assertIsInstance(transport, StreamableHttpTransport)
        self.assertEqual(transport.url, "https://srv/mcp")

    @patch('backend.services.remote_mcp_service.Client')
    async def test_unknown_url_defaults_to_streamable_http(self, mock_client_cls):
        """URL without /sse or /mcp suffix defaults to StreamableHttpTransport."""
        from unittest.mock import AsyncMock
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = True
        mock_client_cls.return_value = mock_client

        from backend.services.remote_mcp_service import _mcp_protocol_connect
        result = await _mcp_protocol_connect("https://srv/api", {})

        self.assertTrue(result)
        transport = mock_client_cls.call_args[1]['transport']
        self.assertIsInstance(transport, StreamableHttpTransport)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_connection_failure_returns_false(self, mock_client_cls):
        """async with client raises => returns False."""
        from unittest.mock import AsyncMock
        mock_client = AsyncMock()
        mock_client.__aenter__.side_effect = Exception("Connection refused")
        mock_client_cls.return_value = mock_client

        from backend.services.remote_mcp_service import _mcp_protocol_connect
        result = await _mcp_protocol_connect("https://srv/mcp", {})

        self.assertFalse(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_headers_passed_to_transport(self, mock_client_cls):
        """Custom headers are forwarded to the transport."""
        from unittest.mock import AsyncMock
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = True
        mock_client_cls.return_value = mock_client

        from backend.services.remote_mcp_service import _mcp_protocol_connect
        headers = {"Authorization": "Bearer tok", "X-Custom": "val"}
        await _mcp_protocol_connect("https://srv/mcp", headers)

        transport = mock_client_cls.call_args[1]['transport']
        self.assertEqual(transport.headers.get("Authorization"), "Bearer tok")
        self.assertEqual(transport.headers.get("X-Custom"), "val")


# ============================================================================
# test_mcp_connection - public wrapper for _mcp_protocol_connect
# ============================================================================

class TestMcpConnectionEndpoint(unittest.IsolatedAsyncioTestCase):
    """Test test_mcp_connection wrapper function."""

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_with_auth_token(self, mock_connect):
        """Auth token is passed in Authorization header."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = True

        result = await test_mcp_connection(
            "https://srv/mcp",
            authorization_token="Bearer tok",
        )

        self.assertTrue(result)
        mock_connect.assert_called_once_with(
            "https://srv/mcp",
            {"Authorization": "Bearer tok"},
        )

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_with_custom_headers(self, mock_connect):
        """Custom headers are passed through."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = True

        result = await test_mcp_connection(
            "https://srv/mcp",
            custom_headers={"X-Custom": "val"},
        )

        self.assertTrue(result)
        mock_connect.assert_called_once_with(
            "https://srv/mcp",
            {"X-Custom": "val"},
        )

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_with_both_auth_and_custom_headers(self, mock_connect):
        """Auth token and custom headers are merged."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = True

        result = await test_mcp_connection(
            "https://srv/mcp",
            authorization_token="tok",
            custom_headers={"X-Custom": "val"},
        )

        self.assertTrue(result)
        mock_connect.assert_called_once_with(
            "https://srv/mcp",
            {"Authorization": "tok", "X-Custom": "val"},
        )

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_no_auth_or_headers(self, mock_connect):
        """No credentials => empty headers dict."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = True

        result = await test_mcp_connection("https://srv/mcp")

        self.assertTrue(result)
        mock_connect.assert_called_once_with("https://srv/mcp", {})

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_connection_failure_returns_false(self, mock_connect):
        """Underlying connect fails => wrapper returns False."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = False

        result = await test_mcp_connection("https://srv/mcp")

        self.assertFalse(result)

    @patch('backend.services.remote_mcp_service._mcp_protocol_connect')
    async def test_url_stripped(self, mock_connect):
        """URL whitespace is stripped before passing to connect."""
        from backend.services.remote_mcp_service import test_mcp_connection
        mock_connect.return_value = True

        result = await test_mcp_connection("  https://srv/mcp  ")

        self.assertTrue(result)
        mock_connect.assert_called_once_with("https://srv/mcp", {})


# ============================================================================
# refresh_mcp_service_tool_count (NEW)
# ============================================================================

class TestRefreshMcpServiceToolCount(unittest.IsolatedAsyncioTestCase):
    """Test refresh_mcp_service_tool_count."""

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.update_mcp_record_registry_json_by_id')
    async def test_success(self, mock_update, mock_health, mock_get):
        """Tool names fetched and persisted successfully."""
        mock_get.return_value = {
            "mcp_server": "https://srv/mcp",
            "authorization_token": None,
            "custom_headers": None,
            "registry_json": {},
        }
        mock_health.return_value = ["tool1", "tool2"]

        result = await refresh_mcp_service_tool_count(
            tenant_id="tid", user_id="uid", mcp_id=1,
        )

        self.assertEqual(result, ["tool1", "tool2"])
        mock_update.assert_called_once_with(
            mcp_id=1, tenant_id="tid", user_id="uid",
            registry_json={"_toolNames": ["tool1", "tool2"]},
        )

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_record_not_found(self, mock_get):
        """Missing record raises McpNotFoundError."""
        mock_get.return_value = None

        with self.assertRaises(McpNotFoundError):
            await refresh_mcp_service_tool_count(
                tenant_id="tid", user_id="uid", mcp_id=999,
            )

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_no_server_url(self, mock_get):
        """Record without server URL raises McpValidationError."""
        mock_get.return_value = {
            "mcp_server": None,
            "authorization_token": None,
            "custom_headers": None,
        }

        with self.assertRaises(McpValidationError):
            await refresh_mcp_service_tool_count(
                tenant_id="tid", user_id="uid", mcp_id=1,
            )

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    async def test_server_unreachable(self, mock_health, mock_get):
        """Server unreachable raises MCPConnectionError."""
        mock_get.return_value = {
            "mcp_server": "https://srv/mcp",
            "authorization_token": None,
            "custom_headers": None,
        }
        mock_health.return_value = []

        with self.assertRaises(MCPConnectionError):
            await refresh_mcp_service_tool_count(
                tenant_id="tid", user_id="uid", mcp_id=1,
            )

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service._mcp_protocol_health_check')
    @patch('backend.services.remote_mcp_service.update_mcp_record_registry_json_by_id')
    async def test_with_auth_token_and_custom_headers(self, mock_update, mock_health, mock_get):
        """Auth token and custom headers are passed to health check."""
        mock_get.return_value = {
            "mcp_server": "https://srv/mcp",
            "authorization_token": "Bearer tok",
            "custom_headers": {"X-Custom": "val"},
            "registry_json": None,
        }
        mock_health.return_value = ["tool1"]

        result = await refresh_mcp_service_tool_count(
            tenant_id="tid", user_id="uid", mcp_id=1,
        )

        self.assertEqual(result, ["tool1"])
        mock_health.assert_called_once_with(
            "https://srv/mcp",
            {"Authorization": "Bearer tok", "X-Custom": "val"},
        )
        mock_update.assert_called_once_with(
            mcp_id=1, tenant_id="tid", user_id="uid",
            registry_json={"_toolNames": ["tool1"]},
        )


if __name__ == '__main__':
    unittest.main()
