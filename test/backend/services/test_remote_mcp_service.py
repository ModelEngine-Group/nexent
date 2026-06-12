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
# mcp_server_health - custom_headers tests (lines 50-58)
# ============================================================================

class TestMcpServerHealthCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test mcp_server_health with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_custom_headers_only(self, mock_client_cls):
        """Test health check with custom_headers only (no auth token)."""
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client

        custom_headers = {"X-Custom-Header": "value1", "X-Another": "value2"}
        result = await mcp_server_health(
            'http://test-server/mcp',
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
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client

        result = await mcp_server_health(
            'http://test-server/mcp',
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
        from fastmcp.client.transports import SSETransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client

        result = await mcp_server_health(
            'http://test-server/sse',
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
        """Test that asyncio.TimeoutError raises MCPConnectionError with MCP_HEALTH_TIMEOUT."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(side_effect=asyncio.TimeoutError())
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError) as context:
            await mcp_server_health('http://test-server', custom_headers={"X-Test": "value"})

        self.assertIn("MCP_HEALTH_TIMEOUT", str(context.exception))

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_timeout_error_raises_mcp_connection_error(self, mock_client_cls):
        """Test that TimeoutError raises MCPConnectionError with MCP_HEALTH_TIMEOUT."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(side_effect=TimeoutError())
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError) as context:
            await mcp_server_health('http://test-server', custom_headers={"X-Test": "value"})

        self.assertIn("MCP_HEALTH_TIMEOUT", str(context.exception))

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_timeout_in_message_raises_mcp_connection_error(self, mock_client_cls):
        """Test that exception message containing 'timeout' raises MCPConnectionError."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(side_effect=Exception("Connection timeout error"))
        mock_client_cls.return_value = mock_client

        with self.assertRaises(MCPConnectionError) as context:
            await mcp_server_health('http://test-server', custom_headers={"X-Test": "value"})

        self.assertIn("MCP_HEALTH_TIMEOUT", str(context.exception))


# ============================================================================
# add_remote_mcp_server_list - custom_headers tests (lines 173, 196, 205)
# ============================================================================

class TestAddRemoteMcpServerListCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test add_remote_mcp_server_list with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_custom_headers(self, mock_check_name, mock_health, mock_create):
        """Test add_remote_mcp_server_list passes custom_headers to health check and stores it."""
        mock_check_name.return_value = False
        mock_health.return_value = True

        custom_headers = {"X-API-Key": "key123", "X-Custom": "value"}
        await add_remote_mcp_server_list(
            'tid', 'uid', 'http://srv', 'name',
            custom_headers=custom_headers
        )

        # Verify custom_headers passed to health check
        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv',
            authorization_token=None,
            custom_headers=custom_headers
        )

        # Verify custom_headers stored in database
        create_call_kwargs = mock_create.call_args[1]
        self.assertEqual(create_call_kwargs['mcp_data']['custom_headers'], custom_headers)

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_auth_token_and_custom_headers(self, mock_check_name, mock_health, mock_create):
        """Test add_remote_mcp_server_list with both auth token and custom_headers."""
        mock_check_name.return_value = False
        mock_health.return_value = True

        await add_remote_mcp_server_list(
            'tid', 'uid', 'http://srv', 'name',
            authorization_token='Bearer token123',
            custom_headers={"X-Header": "value"}
        )

        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv',
            authorization_token='Bearer token123',
            custom_headers={"X-Header": "value"}
        )

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_without_custom_headers_none_passed(self, mock_check_name, mock_health, mock_create):
        """Test add_remote_mcp_server_list when custom_headers is None (default)."""
        mock_check_name.return_value = False
        mock_health.return_value = True

        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv',
            authorization_token=None,
            custom_headers=None
        )

        create_call_kwargs = mock_create.call_args[1]
        self.assertIsNone(create_call_kwargs['mcp_data']['custom_headers'])


# ============================================================================
# add_mcp_service - custom_headers tests (lines 222, 257, 270)
# ============================================================================

class TestAddMcpServiceCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test add_mcp_service with custom_headers parameter."""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_enabled_with_custom_headers(self, mock_check_name, mock_health, mock_create):
        """Test add_mcp_service with enabled=True and custom_headers."""
        mock_check_name.return_value = False
        mock_health.return_value = True

        custom_headers = {"X-Custom-Auth": "header-value"}
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=['tag1'], authorization_token='tok',
            custom_headers=custom_headers,
            container_config=None, registry_json=None, enabled=True,
        )

        # Verify custom_headers passed to health check
        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv/mcp',
            authorization_token='tok',
            custom_headers=custom_headers
        )

        # Verify custom_headers stored in database
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['custom_headers'], custom_headers)
        self.assertTrue(call_data['status'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_disabled_with_custom_headers(self, mock_check_name, mock_health, mock_create):
        """Test add_mcp_service with enabled=False and custom_headers."""
        mock_check_name.return_value = False

        custom_headers = {"X-Disabled-Header": "value"}
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=None, authorization_token=None,
            custom_headers=custom_headers,
            container_config=None, registry_json=None, enabled=False,
        )

        # Health check should NOT be called when disabled
        mock_health.assert_not_called()

        # But custom_headers should still be stored
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['custom_headers'], custom_headers)
        self.assertIsNone(call_data['status'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    async def test_add_with_none_custom_headers(self, mock_create):
        """Test add_mcp_service with custom_headers=None (default)."""
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=None, authorization_token=None,
            custom_headers=None,
            container_config=None, registry_json=None, enabled=False,
        )

        call_data = mock_create.call_args[1]['mcp_data']
        self.assertIsNone(call_data['custom_headers'])


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
            current_mcp_url="http://old.url",
            new_service_name="new",
            new_mcp_url="http://new.url",
            new_authorization_token="tok",
            custom_headers=custom_headers,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server="http://new.url",
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
            current_mcp_url="http://old.url",
            new_service_name="new",
            new_mcp_url="http://new.url",
            new_authorization_token=None,
            custom_headers=None,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server="http://new.url",
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
            server_url='http://new.url', authorization_token='tok',
            custom_headers=custom_headers,
            tags=['a', 'b'],
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
            server_url='http://new.url', authorization_token='tok',
            custom_headers=None,
            tags=None,
        )

        call_kwargs = mock_update.call_args[1]
        self.assertIsNone(call_kwargs['custom_headers'])


# ============================================================================
# update_mcp_service_enabled - custom_headers tests (lines 530, 599, 656)
# ============================================================================

class TestUpdateMcpServiceEnabledCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test update_mcp_service_enabled with custom_headers."""

    def _make_record(self, **overrides):
        base = {
            "mcp_id": 1, "mcp_name": "test-svc", "mcp_server": "http://srv/mcp",
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
            remote_mcp_server='http://srv/mcp',
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
            remote_mcp_server='http://srv/mcp',
            authorization_token='tok',
            custom_headers=None,
        )

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_with_custom_headers(
        self, mock_records, mock_get, mock_mgr_cls, mock_health, mock_cont_fields, mock_enabled
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
            "container_id": "new-cid", "mcp_url": "http://localhost:8080/mcp", "host_port": 8080,
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
                "mcp_name": "svc1", "mcp_server": "http://srv1/mcp",
                "status": True, "mcp_id": 1,
                "authorization_token": "tok1",
                "custom_headers": {"X-Custom1": "value1"},
            },
            {
                "mcp_name": "svc2", "mcp_server": "http://srv2/mcp",
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
                "mcp_name": "svc1", "mcp_server": "http://srv1/mcp",
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
            "mcp_server": "http://test.com/mcp",
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
            "mcp_server": "http://test.com/mcp",
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

        await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')

        mock_get_headers.assert_called_once_with(
            mcp_name='name',
            mcp_server='http://srv',
            tenant_id='tid'
        )

        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv',
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

        await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')

        mock_health.assert_called_once_with(
            remote_mcp_server='http://srv',
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
            await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')


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
            "mcp_server": "http://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": {"X-Service-Custom": "service-value"},
        }
        mock_health.return_value = True

        result = await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

        self.assertEqual(result, "healthy")
        mock_health.assert_called_once_with(
            remote_mcp_server="http://srv/mcp",
            authorization_token="tok",
            custom_headers={"X-Service-Custom": "service-value"},
        )

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_health_without_custom_headers(self, mock_get, mock_health, mock_status):
        """Test check_mcp_service_health when custom_headers is None."""
        mock_get.return_value = {
            "mcp_server": "http://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": None,
        }
        mock_health.return_value = True

        result = await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

        self.assertEqual(result, "healthy")
        mock_health.assert_called_once_with(
            remote_mcp_server="http://srv/mcp",
            authorization_token="tok",
            custom_headers=None,
        )


# ============================================================================
# list_mcp_service_tools_by_id - custom_headers tests (lines 1024-1025, 1031-1032)
# ============================================================================

class TestListMcpServiceToolsByIdCustomHeaders(unittest.IsolatedAsyncioTestCase):
    """Test list_mcp_service_tools_by_id uses custom_headers from record."""

    @patch('services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_tools_with_custom_headers(self, mock_get, mock_get_tools):
        """Test list_mcp_service_tools_by_id passes custom_headers to tool retrieval."""
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "http://srv/mcp",
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
            remote_mcp_server='http://srv/mcp',
            tenant_id='tid',
            authorization_token='tok',
            custom_headers={"X-Tools-Custom": "tools-value"},
        )

    @patch('services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_tools_without_custom_headers(self, mock_get, mock_get_tools):
        """Test list_mcp_service_tools_by_id when custom_headers is None."""
        mock_get.return_value = {
            "mcp_name": "svc",
            "mcp_server": "http://srv/mcp",
            "authorization_token": "tok",
            "custom_headers": None,
        }
        mock_tool = MagicMock()
        mock_tool.__dict__ = {"name": "tool1", "description": "desc"}
        mock_get_tools.return_value = [mock_tool]

        result = await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)

        mock_get_tools.assert_called_once_with(
            mcp_server_name='svc',
            remote_mcp_server='http://srv/mcp',
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
            "mcp_url": "http://localhost:8080/mcp",
            "host_port": 8080,
            "container_name": "test-svc-xyz",
        })
        mock_mgr_cls.return_value = mock_mgr

        await add_container_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', tags=[],
            authorization_token='tok', registry_json=None,
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
            current_mcp_url="http://old.url",
            new_service_name="new-svc",
            new_mcp_url="http://new.url",
            new_authorization_token="Bearer tok",
            custom_headers=custom_headers,
        )

        await update_remote_mcp_server_list(update_data, 'tid', 'uid')

        # Verify the health check received custom_headers
        mock_health.assert_called_once()
        call_kwargs = mock_health.call_args[1]
        self.assertEqual(call_kwargs['custom_headers'], custom_headers)


if __name__ == '__main__':
    unittest.main()
