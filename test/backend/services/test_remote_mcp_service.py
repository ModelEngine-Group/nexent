"""
Unit tests for backend/services/remote_mcp_service.py

Tests the MCP service business logic layer with comprehensive coverage.
Covers: health checks, CRUD operations, container management, port management,
enable/disable lifecycle, and tool listing.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import importlib.machinery
import types
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
# Patch storage factory and MinIO config validation
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
# Helper: _is_container_record
# ============================================================================

class TestIsContainerRecord(unittest.TestCase):
    """Test _is_container_record helper"""

    def test_container_record_with_both(self):
        self.assertTrue(_is_container_record({"container_id": "abc", "config_json": {}}))

    def test_container_record_with_container_id_only(self):
        self.assertTrue(_is_container_record({"container_id": "abc"}))

    def test_container_record_with_config_json_only(self):
        self.assertTrue(_is_container_record({"config_json": {"mcpServers": {}}}))

    def test_non_container_record(self):
        self.assertFalse(_is_container_record({"mcp_server": "http://url"}))

    def test_none_record(self):
        self.assertFalse(_is_container_record(None))

    def test_empty_record(self):
        self.assertFalse(_is_container_record({}))


# ============================================================================
# Port Management Functions
# ============================================================================

class TestCheckContainerPortConflictRecords(unittest.TestCase):
    """Test check_container_port_conflict_records"""

    @patch('database.remote_mcp_db.get_mcp_records_by_container_port')
    def test_port_available_no_records(self, mock_get):
        mock_get.return_value = []
        result = check_container_port_conflict_records(8080)
        self.assertTrue(result)
        mock_get.assert_called_once_with(container_port=8080)

    @patch('database.remote_mcp_db.get_mcp_records_by_container_port')
    def test_port_in_use(self, mock_get):
        mock_get.return_value = [{"mcp_id": 1}]
        result = check_container_port_conflict_records(8080)
        self.assertFalse(result)


class TestCheckRuntimeHostPortAvailable(unittest.TestCase):
    """Test check_runtime_host_port_available"""

    @patch('backend.services.remote_mcp_service.socket.has_ipv6', False)
    @patch('socket.socket')
    @patch('socket.getaddrinfo')
    def test_port_available(self, mock_getaddrinfo, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1  # Non-zero = not in use
        mock_socket_cls.return_value = mock_sock

        result = check_runtime_host_port_available(8080)
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.socket.has_ipv6', False)
    @patch('socket.socket')
    @patch('socket.getaddrinfo', side_effect=OSError("no route"))
    def test_port_available_no_docker_host(self, mock_getaddrinfo, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1
        mock_socket_cls.return_value = mock_sock

        result = check_runtime_host_port_available(8080)
        self.assertTrue(result)

    def test_port_in_use_connect(self):
        # Simulate port in use: mock the entire socket module inside remote_mcp_service
        mock_socket_module = MagicMock()
        mock_socket_module.has_ipv6 = False
        mock_socket_module.AF_INET = 2
        mock_socket_module.SOCK_STREAM = 1
        mock_socket_module.SOL_SOCKET = 1
        mock_socket_module.SO_REUSEADDR = 2

        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0  # Zero = port in use
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_socket_module.socket.return_value = mock_sock
        mock_socket_module.getaddrinfo.side_effect = OSError("no route")

        with patch.object(remote_service, 'socket', mock_socket_module):
            result = check_runtime_host_port_available(8080)
            self.assertFalse(result)


class TestCheckContainerPortConflict(unittest.TestCase):
    """Test check_container_port_conflict"""

    @patch('backend.services.remote_mcp_service.check_container_port_conflict_records', return_value=True)
    @patch('backend.services.remote_mcp_service.check_runtime_host_port_available', return_value=True)
    def test_port_available(self, mock_runtime, mock_records):
        result = check_container_port_conflict(port=8080)
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.check_container_port_conflict_records', return_value=False)
    @patch('backend.services.remote_mcp_service.check_runtime_host_port_available', return_value=True)
    def test_record_conflict(self, mock_runtime, mock_records):
        result = check_container_port_conflict(port=8080)
        self.assertFalse(result)

    @patch('backend.services.remote_mcp_service.check_container_port_conflict_records', return_value=True)
    @patch('backend.services.remote_mcp_service.check_runtime_host_port_available', return_value=False)
    def test_runtime_conflict(self, mock_runtime, mock_records):
        result = check_container_port_conflict(port=8080)
        self.assertFalse(result)


class TestSuggestContainerPort(unittest.TestCase):
    """Test suggest_container_port"""

    @patch('backend.services.remote_mcp_service.random.randint', return_value=5000)
    @patch('backend.services.remote_mcp_service.check_container_port_conflict', return_value=True)
    def test_success_first_try(self, mock_check, mock_randint):
        result = suggest_container_port()
        self.assertEqual(result, 5000)

    @patch('backend.services.remote_mcp_service.random.randint', side_effect=[5000, 5001, 5002])
    @patch('backend.services.remote_mcp_service.check_container_port_conflict', side_effect=[False, False, True])
    def test_success_after_retries(self, mock_check, mock_randint):
        result = suggest_container_port()
        self.assertEqual(result, 5002)
        self.assertEqual(mock_check.call_count, 3)

    @patch('backend.services.remote_mcp_service.random.randint', return_value=5000)
    @patch('backend.services.remote_mcp_service.check_container_port_conflict', return_value=False)
    def test_no_available_port(self, mock_check, mock_randint):
        with self.assertRaises(McpPortConflictError):
            suggest_container_port()


# ============================================================================
# mcp_server_health
# ============================================================================

class TestMcpServerHealth(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_success(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('http://test-server')
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_fail_connection(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('http://test-server')
        self.assertFalse(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_exception(self, mock_client_cls):
        mock_client_cls.side_effect = Exception('Connection failed')
        with self.assertRaises(MCPConnectionError):
            await mcp_server_health('http://test-server')

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_authorization_token(self, mock_client_cls):
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('http://test-server', authorization_token='Bearer token123')
        self.assertTrue(result)
        call_args = mock_client_cls.call_args
        transport = call_args[1]['transport']
        self.assertIsInstance(transport, StreamableHttpTransport)
        self.assertEqual(transport.headers, {"Authorization": "Bearer token123"})

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_sse_url(self, mock_client_cls):
        from fastmcp.client.transports import SSETransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('http://test-server/sse', authorization_token='token123')
        self.assertTrue(result)
        call_args = mock_client_cls.call_args
        transport = call_args[1]['transport']
        self.assertIsInstance(transport, SSETransport)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_mcp_url(self, mock_client_cls):
        from fastmcp.client.transports import StreamableHttpTransport
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('http://test-server/mcp')
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_url_whitespace(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client_cls.return_value = mock_client
        result = await mcp_server_health('  http://test-server/mcp  ')
        self.assertTrue(result)


# ============================================================================
# add_remote_mcp_server_list
# ============================================================================

class TestAddRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_success(self, mock_check_name, mock_health, mock_create):
        mock_check_name.return_value = False
        mock_health.return_value = True
        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        mock_check_name.assert_called_once_with(mcp_name='name', tenant_id='tid')
        mock_health.assert_called_once_with(remote_mcp_server='http://srv', authorization_token=None)
        mock_create.assert_called_once()

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_name_exists(self, mock_check_name):
        mock_check_name.return_value = True
        with self.assertRaises(MCPNameIllegal):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_health_fail(self, mock_check_name, mock_health):
        mock_check_name.return_value = False
        mock_health.return_value = False
        with self.assertRaises(MCPConnectionError):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_success_with_authorization_token(self, mock_check_name, mock_health, mock_create):
        mock_check_name.return_value = False
        mock_health.return_value = True
        await add_remote_mcp_server_list(
            'tid', 'uid', 'http://srv', 'name',
            container_id='container-123', authorization_token='Bearer token123',
        )
        create_call_kwargs = mock_create.call_args[1]
        self.assertEqual(create_call_kwargs['mcp_data']['authorization_token'], 'Bearer token123')
        self.assertEqual(create_call_kwargs['mcp_data']['container_id'], 'container-123')


# ============================================================================
# add_mcp_service (NEW)
# ============================================================================

class TestAddMcpService(unittest.IsolatedAsyncioTestCase):
    """Test add_mcp_service - the unified MCP service creation function"""

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_url_based_disabled(self, mock_check_name, mock_health, mock_create):
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=['tag1'], authorization_token=None, container_config=None,
            registry_json=None, enabled=False,
        )
        mock_create.assert_called_once()
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['mcp_name'], 'test-svc')
        self.assertEqual(call_data['enabled'], False)
        self.assertIsNone(call_data['status'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_url_based_enabled(self, mock_check_name, mock_health, mock_create):
        mock_check_name.return_value = False
        mock_health.return_value = True
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=None, authorization_token='tok', container_config=None,
            registry_json=None, enabled=True,
        )
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertTrue(call_data['status'])

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_enabled_name_conflict(self, mock_check_name, mock_health):
        mock_check_name.return_value = True
        with self.assertRaises(MCPNameIllegal):
            await add_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', server_url='http://srv/mcp',
                tags=None, authorization_token=None, container_config=None,
                registry_json=None, enabled=True,
            )

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_enabled_health_fail(self, mock_check_name):
        mock_check_name.return_value = False
        with patch('backend.services.remote_mcp_service.mcp_server_health', return_value=False):
            with self.assertRaises(MCPConnectionError):
                await add_mcp_service(
                    tenant_id='tid', user_id='uid', name='test-svc',
                    description='desc', source='local', server_url='http://srv/mcp',
                    tags=None, authorization_token=None, container_config=None,
                    registry_json=None, enabled=True,
                )

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    async def test_add_container_based(self, mock_create):
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=None, authorization_token=None,
            container_config={"mcpServers": {"s": {"command": "echo"}}},
            registry_json=None, enabled=False, container_id='cid', container_port=8080,
        )
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertEqual(call_data['container_id'], 'cid')
        self.assertEqual(call_data['container_port'], 8080)
        self.assertIsNotNone(call_data['config_json'])

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    async def test_add_container_null_config(self, mock_create):
        """container_config=None + container_id=None should result in config_json=None"""
        await add_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', server_url='http://srv/mcp',
            tags=None, authorization_token=None,
            container_config=None, container_id=None, container_port=None,
            registry_json=None, enabled=False,
        )
        call_data = mock_create.call_args[1]['mcp_data']
        self.assertIsNone(call_data['config_json'])
        self.assertIsNone(call_data['container_id'])


# ============================================================================
# add_container_mcp_service (NEW)
# ============================================================================

class TestAddContainerMcpService(unittest.IsolatedAsyncioTestCase):
    """Test add_container_mcp_service"""

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
    async def test_success(self, mock_check_name, mock_port_check, mock_mgr_cls, mock_add):
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container = AsyncMock(return_value={
            "container_id": "cid", "mcp_url": "http://localhost:8080/mcp",
            "host_port": 8080, "container_name": "test-svc-xyz",
        })
        mock_mgr_cls.return_value = mock_mgr

        result = await add_container_mcp_service(
            tenant_id='tid', user_id='uid', name='test-svc',
            description='desc', source='local', tags=[],
            authorization_token='tok', registry_json=None,
            port=8080, mcp_config=self._make_mcp_config(),
        )
        self.assertEqual(result['container_id'], 'cid')
        self.assertEqual(result['mcp_url'], 'http://localhost:8080/mcp')
        mock_add.assert_called_once()

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_name_conflict(self, mock_check_name):
        mock_check_name.return_value = True
        with self.assertRaises(McpNameConflictError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=self._make_mcp_config(),
            )

    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_port_conflict(self, mock_check_name, mock_port_check):
        mock_check_name.return_value = False
        mock_port_check.return_value = False
        with self.assertRaises(McpPortConflictError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=self._make_mcp_config(),
            )

    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_empty_mcp_servers(self, mock_check_name, mock_port_check):
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        cfg = MCPConfigRequest(mcpServers={})
        with self.assertRaises(McpValidationError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=cfg,
            )

    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_docker_command_rejected(self, mock_check_name, mock_port_check):
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        cfg = self._make_mcp_config(command="docker")
        with self.assertRaises(McpValidationError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=cfg,
            )

    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_empty_command(self, mock_check_name, mock_port_check):
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        cfg = self._make_mcp_config(command="")
        with self.assertRaises(McpValidationError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=cfg,
            )

    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_container_port_conflict')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_container_start_failure(self, mock_check_name, mock_port_check, mock_mgr_cls):
        mock_check_name.return_value = False
        mock_port_check.return_value = True
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container = AsyncMock(side_effect=MCPContainerError("start failed"))
        mock_mgr_cls.return_value = mock_mgr

        with self.assertRaises(MCPContainerError):
            await add_container_mcp_service(
                tenant_id='tid', user_id='uid', name='test-svc',
                description='desc', source='local', tags=[],
                authorization_token=None, registry_json=None,
                port=8080, mcp_config=self._make_mcp_config(),
            )


# ============================================================================
# update_remote_mcp_server_list
# ============================================================================

class MockMCPUpdateRequest:
    def __init__(self, current_service_name, current_mcp_url, new_service_name, new_mcp_url, new_authorization_token=None):
        self.current_service_name = current_service_name
        self.current_mcp_url = current_mcp_url
        self.new_service_name = new_service_name
        self.new_mcp_url = new_mcp_url
        self.new_authorization_token = new_authorization_token


class TestUpdateRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.update_mcp_record_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_success(self, mock_check_name, mock_health, mock_update_record):
        mock_check_name.side_effect = [True, False]
        mock_health.return_value = True
        update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://new.url")
        await update_remote_mcp_server_list(update_data, 'tid', 'uid')
        mock_update_record.assert_called_once()

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_current_name_not_exist(self, mock_check_name):
        mock_check_name.return_value = False
        update_data = MockMCPUpdateRequest("noexist", "http://old.url", "new", "http://new.url")
        with self.assertRaises(MCPNameIllegal):
            await update_remote_mcp_server_list(update_data, 'tid', 'uid')

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_new_name_exists(self, mock_check_name, mock_health):
        mock_check_name.side_effect = [True, True]
        update_data = MockMCPUpdateRequest("old", "http://old.url", "existing", "http://new.url")
        with self.assertRaises(MCPNameIllegal):
            await update_remote_mcp_server_list(update_data, 'tid', 'uid')

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_update_health_fail(self, mock_check_name, mock_health):
        mock_check_name.side_effect = [True, False]
        mock_health.return_value = False
        update_data = MockMCPUpdateRequest("old", "http://old.url", "new", "http://unreachable.url")
        with self.assertRaises(MCPConnectionError):
            await update_remote_mcp_server_list(update_data, 'tid', 'uid')


# ============================================================================
# update_mcp_service (NEW)
# ============================================================================

class TestUpdateMcpService(unittest.TestCase):
    """Test update_mcp_service"""

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_success(self, mock_get, mock_update):
        mock_get.return_value = {"mcp_id": 1, "source": "local", "config_json": None}
        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='new-name', description='desc',
            server_url='http://new.url', authorization_token='tok',
            tags=['a', 'b'],
        )
        mock_update.assert_called_once()

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            update_mcp_service(
                tenant_id='tid', user_id='uid', mcp_id=999,
                new_name='x', description='d', server_url='u',
                authorization_token=None, tags=None,
            )

    @patch('backend.services.remote_mcp_service.update_mcp_record_manage_fields_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    def test_update_container_record_preserves_config(self, mock_get, mock_update):
        mock_get.return_value = {
            "mcp_id": 1, "source": "local",
            "config_json": {"mcpServers": {}}, "container_id": "cid",
        }
        update_mcp_service(
            tenant_id='tid', user_id='uid', mcp_id=1,
            new_name='new-name', description='d',
            server_url='http://u', authorization_token=None, tags=None,
        )
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs['config_json'], {"mcpServers": {}})


# ============================================================================
# update_mcp_service_enabled (NEW - most complex function)
# ============================================================================

class TestUpdateMcpServiceEnabled(unittest.IsolatedAsyncioTestCase):
    """Test update_mcp_service_enabled - enable/disable lifecycle"""

    def _make_record(self, **overrides):
        base = {
            "mcp_id": 1, "mcp_name": "test-svc", "mcp_server": "http://srv/mcp",
            "container_id": None, "container_port": None, "config_json": None,
            "authorization_token": None, "enabled": False, "source": "local",
        }
        base.update(overrides)
        return base

    # --- Non-container: enable ---

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_non_container_enable_success(self, mock_records, mock_get, mock_health, mock_status, mock_enabled):
        mock_get.return_value = self._make_record()
        mock_records.return_value = []
        mock_health.return_value = True
        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)
        mock_status.assert_called_once()
        mock_enabled.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', enabled=True)

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    async def test_non_container_enable_health_fail(self, mock_status, mock_records, mock_get, mock_health):
        mock_get.return_value = self._make_record()
        mock_records.return_value = []
        mock_health.return_value = False
        with self.assertRaises(MCPConnectionError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

    # --- Non-container: disable ---

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_non_container_disable(self, mock_get, mock_enabled):
        mock_get.return_value = self._make_record()
        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=False)
        mock_enabled.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', enabled=False)

    # --- Container: enable (rebuild) ---

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_rebuild_success(self, mock_records, mock_get, mock_mgr_cls, mock_health, mock_cont_fields, mock_enabled):
        mock_get.return_value = self._make_record(
            container_port=8080,
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

        mock_mgr.start_mcp_container.assert_called_once()
        mock_cont_fields.assert_called_once()
        mock_enabled.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', enabled=True)

    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_missing_port(self, mock_records, mock_get, mock_mgr_cls):
        mock_get.return_value = self._make_record(
            container_port=None,
            config_json={"mcpServers": {"s": {"command": "echo"}}},
        )
        mock_records.return_value = []
        with self.assertRaises(McpValidationError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_missing_config(self, mock_records, mock_get):
        # Must have container_id or config_json for _is_container_record to return True
        mock_get.return_value = self._make_record(container_id="cid", config_json=None)
        mock_records.return_value = []
        with self.assertRaises(McpValidationError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_container_enable_health_fail_cleans_up(self, mock_records, mock_get, mock_mgr_cls, mock_health, mock_cont_fields):
        mock_get.return_value = self._make_record(
            container_port=8080,
            config_json={"mcpServers": {"s": {"command": "echo", "args": [], "env": {}}}},
        )
        mock_records.return_value = []
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container = AsyncMock(return_value={
            "container_id": "cid", "mcp_url": "http://localhost:8080/mcp", "host_port": 8080,
        })
        mock_mgr.stop_mcp_container = AsyncMock(return_value=True)
        mock_mgr_cls.return_value = mock_mgr
        mock_health.return_value = False

        with self.assertRaises(MCPConnectionError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)
        # Should have attempted cleanup
        mock_mgr.stop_mcp_container.assert_called_once()

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_enable_name_conflict_with_other_enabled(self, mock_records, mock_get):
        mock_get.return_value = self._make_record(mcp_name="duplicate")
        mock_records.return_value = [
            {"mcp_id": 2, "mcp_name": "duplicate", "enabled": True},
        ]
        with self.assertRaises(McpNameConflictError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=True)

    # --- Container: disable ---

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_container_disable_success(self, mock_get, mock_mgr_cls, mock_cont_fields, mock_enabled):
        mock_get.return_value = self._make_record(
            container_id="old-cid", container_port=8080, mcp_server="http://old/mcp",
            config_json={"mcpServers": {"test": {"command": "echo test"}}},
        )
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(return_value=True)
        mock_mgr_cls.return_value = mock_mgr

        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=False)

        mock_mgr.stop_mcp_container.assert_called_once_with("old-cid")
        mock_cont_fields.assert_called_once()
        call_kwargs = mock_cont_fields.call_args[1]
        self.assertIsNone(call_kwargs['container_id'])
        self.assertEqual(call_kwargs['container_port'], 8080)
        self.assertIsNone(call_kwargs['status'])
        mock_enabled.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', enabled=False)

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_container_disable_no_container_id(self, mock_get, mock_mgr_cls, mock_cont_fields, mock_enabled):
        mock_get.return_value = self._make_record(container_id=None, container_port=8080)
        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=False)
        mock_mgr_cls.assert_not_called()
        mock_enabled.assert_called_once()

    @patch('backend.services.remote_mcp_service.update_mcp_record_enabled_by_id')
    @patch('backend.services.remote_mcp_service.update_mcp_record_container_fields_by_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_container_disable_stop_fails_still_disables(self, mock_get, mock_mgr_cls, mock_cont_fields, mock_enabled):
        mock_get.return_value = self._make_record(container_id="cid", container_port=8080)
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(side_effect=Exception("stop failed"))
        mock_mgr_cls.return_value = mock_mgr

        # Should not raise - stop failure is logged but doesn't block disable
        await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=1, enabled=False)
        mock_enabled.assert_called_once()

    # --- Not found ---

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await update_mcp_service_enabled(tenant_id='tid', user_id='uid', mcp_id=999, enabled=True)


# ============================================================================
# delete_mcp_service (NEW)
# ============================================================================

class TestDeleteMcpService(unittest.IsolatedAsyncioTestCase):
    """Test delete_mcp_service"""

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_id')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_delete_url_based(self, mock_get, mock_delete):
        mock_get.return_value = {"mcp_id": 1, "container_id": None}
        await delete_mcp_service(tenant_id='tid', user_id='uid', mcp_id=1)
        mock_delete.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid')

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_delete_container_based(self, mock_get, mock_mgr_cls, mock_delete):
        mock_get.return_value = {"mcp_id": 1, "container_id": "cid"}
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(return_value=True)
        mock_mgr_cls.return_value = mock_mgr
        await delete_mcp_service(tenant_id='tid', user_id='uid', mcp_id=1)
        mock_mgr.stop_mcp_container.assert_called_once_with(container_id="cid")
        mock_delete.assert_called_once()

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_id')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_delete_container_stop_fails_still_deletes(self, mock_get, mock_mgr_cls, mock_delete):
        mock_get.return_value = {"mcp_id": 1, "container_id": "cid"}
        mock_mgr = MagicMock()
        mock_mgr.stop_mcp_container = AsyncMock(side_effect=Exception("stop failed"))
        mock_mgr_cls.return_value = mock_mgr
        await delete_mcp_service(tenant_id='tid', user_id='uid', mcp_id=1)
        mock_delete.assert_called_once()

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_delete_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await delete_mcp_service(tenant_id='tid', user_id='uid', mcp_id=999)


# ============================================================================
# check_mcp_service_health (NEW)
# ============================================================================

class TestCheckMcpServiceHealth(unittest.IsolatedAsyncioTestCase):
    """Test check_mcp_service_health"""

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_healthy(self, mock_get, mock_health, mock_status):
        mock_get.return_value = {"mcp_server": "http://srv/mcp", "authorization_token": "tok"}
        mock_health.return_value = True
        result = await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)
        self.assertEqual(result, "healthy")
        mock_status.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', status=True)

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_unhealthy(self, mock_get, mock_health, mock_status):
        mock_get.return_value = {"mcp_server": "http://srv/mcp", "authorization_token": None}
        mock_health.return_value = False
        with self.assertRaises(MCPConnectionError):
            await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)
        mock_status.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', status=False)

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_empty_server_url(self, mock_get):
        mock_get.return_value = {"mcp_server": "", "authorization_token": None}
        with self.assertRaises(McpValidationError):
            await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)

    @patch('backend.services.remote_mcp_service.update_mcp_record_status_by_id')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_health_exception_updates_status(self, mock_get, mock_health, mock_status):
        mock_get.return_value = {"mcp_server": "http://srv/mcp", "authorization_token": "tok"}
        mock_health.side_effect = MCPConnectionError("timeout")
        with self.assertRaises(MCPConnectionError):
            await check_mcp_service_health(tenant_id='tid', user_id='uid', mcp_id=1)
        mock_status.assert_called_once_with(mcp_id=1, tenant_id='tid', user_id='uid', status=False)


# ============================================================================
# list_mcp_service_tools_by_id (NEW)
# ============================================================================

class TestListMcpServiceToolsById(unittest.IsolatedAsyncioTestCase):
    """Test list_mcp_service_tools_by_id"""

    @patch('backend.services.remote_mcp_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_success(self, mock_get, mock_get_tools):
        mock_get.return_value = {"mcp_name": "svc", "mcp_server": "http://srv/mcp"}
        mock_tool = MagicMock()
        mock_tool.__dict__ = {"name": "tool1", "description": "desc"}
        mock_get_tools.return_value = [mock_tool]
        result = await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "tool1")

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_missing_fields(self, mock_get):
        mock_get.return_value = {"mcp_name": None, "mcp_server": None}
        with self.assertRaises(McpValidationError):
            await list_mcp_service_tools_by_id(tenant_id='tid', mcp_id=1)


# ============================================================================
# delete_mcp_by_container_id
# ============================================================================

class TestDeleteMcpByContainerId(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_container_id')
    async def test_delete_by_container_id_success(self, mock_delete):
        await delete_mcp_by_container_id(tenant_id='tid', user_id='uid', container_id='container-123')
        mock_delete.assert_called_once_with(container_id='container-123', tenant_id='tid', user_id='uid')

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_container_id')
    async def test_delete_by_container_id_db_error(self, mock_delete):
        from sqlalchemy.exc import SQLAlchemyError
        mock_delete.side_effect = SQLAlchemyError("Database error")
        with self.assertRaises(SQLAlchemyError):
            await delete_mcp_by_container_id(tenant_id='tid', user_id='uid', container_id='container-123')


# ============================================================================
# get_remote_mcp_server_list
# ============================================================================

class TestGetRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_list(self, mock_get):
        mock_get.return_value = [
            {"mcp_name": "n1", "mcp_server": "u1", "status": True},
            {"mcp_name": "n2", "mcp_server": "u2", "status": False}
        ]
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["remote_mcp_server_name"], "n1")

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_empty(self, mock_get):
        mock_get.return_value = []
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(result, [])

    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_list_permission_by_creator(self, mock_get, mock_get_user_tenant):
        mock_get_user_tenant.return_value = {"user_role": "USER"}
        mock_get.return_value = [
            {"mcp_name": "n1", "mcp_server": "u1", "status": True, "created_by": "user123"},
        ]
        result = await get_remote_mcp_server_list('tid', user_id="user123")
        self.assertEqual(result[0]["permission"], "EDIT")


# ============================================================================
# check_mcp_health_and_update_db
# ============================================================================

class TestCheckMcpHealthAndUpdateDb(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.get_mcp_authorization_token_by_name_and_url')
    async def test_check_health_success(self, mock_get_token, mock_health, mock_update):
        mock_get_token.return_value = 'Bearer token123'
        mock_health.return_value = True
        await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')
        mock_update.assert_called_once()


# ============================================================================
# get_mcp_record_by_id
# ============================================================================

class TestGetMcpRecordById(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_get_mcp_record_success(self, mock_get_record):
        mock_get_record.return_value = {
            "mcp_name": "test-service", "mcp_server": "http://test.com/mcp",
            "authorization_token": "Bearer token123",
        }
        result = await get_mcp_record_by_id(mcp_id=1, tenant_id="tenant123")
        self.assertIsNotNone(result)
        self.assertEqual(result["mcp_name"], "test-service")

    @patch('backend.services.remote_mcp_service.get_mcp_record_by_id_and_tenant')
    async def test_get_mcp_record_not_found(self, mock_get_record):
        mock_get_record.return_value = None
        result = await get_mcp_record_by_id(mcp_id=999, tenant_id="tenant123")
        self.assertIsNone(result)


# ============================================================================
# upload_and_start_mcp_image
# ============================================================================

class TestUploadAndStartMcpImage(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.add_remote_mcp_server_list')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    @patch('tempfile.NamedTemporaryFile')
    async def test_upload_success(self, mock_temp_file, mock_check_name, mock_mgr_cls, mock_add_server):
        mock_temp_file_obj = MagicMock()
        mock_temp_file_obj.__enter__.return_value = mock_temp_file_obj
        mock_temp_file_obj.__exit__.return_value = None
        mock_temp_file_obj.name = "/tmp/test.tar"
        mock_temp_file.return_value = mock_temp_file_obj
        mock_mgr = MagicMock()
        mock_mgr.start_mcp_container_from_tar = AsyncMock(return_value={
            "container_id": "cid", "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020", "status": "started", "container_name": "test",
        })
        mock_mgr_cls.return_value = mock_mgr
        mock_check_name.return_value = False

        result = await upload_and_start_mcp_image(
            tenant_id="tenant123", user_id="user456", file_content=b"fake",
            filename="test.tar", port=5020, service_name="test-service",
            env_vars='{"NODE_ENV": "production"}',
        )
        self.assertEqual(result["status"], "success")

    async def test_upload_invalid_file_type(self):
        with self.assertRaises(ValueError):
            await upload_and_start_mcp_image(
                tenant_id="t", user_id="u", file_content=b"c",
                filename="test.txt", port=5020,
            )

    async def test_upload_file_too_large(self):
        large = b"x" * (1024 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            await upload_and_start_mcp_image(
                tenant_id="t", user_id="u", file_content=large,
                filename="large.tar", port=5020,
            )


# ============================================================================
# attach_mcp_container_permissions
# ============================================================================

class TestAttachMcpContainerPermissions(unittest.TestCase):

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    def test_empty_containers(self, mock_get_records):
        result = attach_mcp_container_permissions(containers=[], tenant_id='tid', user_id='uid')
        self.assertEqual(result, [])

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    def test_no_user_id_all_read(self, mock_get_records):
        mock_get_records.return_value = []
        containers = [{"container_id": "c1", "name": "container1"}]
        result = attach_mcp_container_permissions(containers=containers, tenant_id='tid', user_id=None)
        self.assertEqual(result[0]["permission"], "READ_ONLY")

    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    def test_admin_user_all_edit(self, mock_get_records, mock_get_user_tenant):
        mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
        mock_get_records.return_value = []
        containers = [{"container_id": "c1", "name": "container1"}]
        result = attach_mcp_container_permissions(containers=containers, tenant_id='tid', user_id='admin')
        self.assertEqual(result[0]["permission"], "EDIT")

    @patch('backend.services.remote_mcp_service.get_user_tenant_by_user_id')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    def test_regular_user_own_container_edit(self, mock_get_records, mock_get_user_tenant):
        mock_get_user_tenant.return_value = {"user_role": "USER"}
        mock_get_records.return_value = [{"container_id": "c1", "created_by": "user123"}]
        containers = [{"container_id": "c1", "name": "container1"}]
        result = attach_mcp_container_permissions(containers=containers, tenant_id='tid', user_id='user123')
        self.assertEqual(result[0]["permission"], "EDIT")


# ============================================================================
# Integration Scenarios
# ============================================================================

class TestIntegrationScenarios(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_full_lifecycle(self, mock_check_name, mock_health, mock_get, mock_create):
        mock_check_name.return_value = False
        mock_health.return_value = True
        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

        mock_get.return_value = [{"mcp_name": "name", "mcp_server": "http://srv", "status": True}]
        list_result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(list_result), 1)
        self.assertEqual(list_result[0]["remote_mcp_server_name"], "name")

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_duplicate_name_scenario(self, mock_check_name):
        mock_check_name.return_value = True
        with self.assertRaises(MCPNameIllegal):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv1', 'duplicate_name')


if __name__ == '__main__':
    unittest.main()
