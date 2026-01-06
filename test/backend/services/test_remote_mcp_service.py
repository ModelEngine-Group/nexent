import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import exception classes
from backend.consts.exceptions import MCPConnectionError, MCPNameIllegal

# Functions to test
from backend.services.remote_mcp_service import (
    mcp_server_health,
    add_remote_mcp_server_list,
    delete_remote_mcp_server_list,
    get_remote_mcp_server_list,
    check_mcp_health_and_update_db,
    delete_mcp_by_container_id,
    upload_and_start_mcp_image,
)
# Patch exception classes to ensure tests use correct exceptions
import backend.services.remote_mcp_service as remote_service
remote_service.MCPConnectionError = MCPConnectionError
remote_service.MCPNameIllegal = MCPNameIllegal

class TestMcpServerHealth(unittest.IsolatedAsyncioTestCase):
    """Test mcp_server_health"""
    
    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_success(self, mock_client_cls):
        """Test successful health check"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)  # Sync mock
        mock_client_cls.return_value = mock_client
        
        result = await mcp_server_health('http://test-server')
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_fail_connection(self, mock_client_cls):
        """Test connection failure"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=False)  # Sync mock
        mock_client_cls.return_value = mock_client
        
        result = await mcp_server_health('http://test-server')
        self.assertFalse(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_exception(self, mock_client_cls):
        """Test exception case"""
        mock_client_cls.side_effect = Exception('Connection failed')
        
        with self.assertRaises(MCPConnectionError) as context:
            await mcp_server_health('http://test-server')
        self.assertEqual(str(context.exception), "MCP connection failed")

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_https_url(self, mock_client_cls):
        """Test health check with HTTPS URL"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)  # Sync mock
        mock_client_cls.return_value = mock_client
        
        result = await mcp_server_health('https://secure-server.com')
        self.assertTrue(result)

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_with_port(self, mock_client_cls):
        """Test health check with URL containing port"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected = MagicMock(return_value=True)  # Sync mock
        mock_client_cls.return_value = mock_client
        
        result = await mcp_server_health('http://test-server:8080')
        self.assertTrue(result)

class TestAddRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """Test add_remote_mcp_server_list"""
    
    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_success(self, mock_check_name, mock_health, mock_create):
        """Test successful MCP server addition"""
        mock_check_name.return_value = False  # Name doesn't exist
        mock_health.return_value = True  # Health check passes
        
        # Should execute successfully without exception
        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        
        # Verify calls
        mock_check_name.assert_called_once_with(mcp_name='name', tenant_id='tid')
        mock_health.assert_called_once_with(remote_mcp_server='http://srv')
        mock_create.assert_called_once()

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_name_exists(self, mock_check_name):
        """Test MCP name already exists"""
        mock_check_name.return_value = True
        
        with self.assertRaises(MCPNameIllegal) as context:
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertEqual(str(context.exception), "MCP name already exists")

    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_health_fail(self, mock_check_name, mock_health):
        """Test health check failure"""
        mock_check_name.return_value = False
        mock_health.side_effect = MCPConnectionError("MCP connection failed")
        
        with self.assertRaises(MCPConnectionError):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_db_fail(self, mock_check_name, mock_health, mock_create):
        """Test database operation failure - exception should propagate from database layer"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_check_name.return_value = False
        mock_health.return_value = True
        mock_create.side_effect = SQLAlchemyError("Database error")
        
        with self.assertRaises(SQLAlchemyError):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_add_with_special_characters(self, mock_check_name, mock_health, mock_create):
        """Test server name with special characters"""
        mock_check_name.return_value = False
        mock_health.return_value = True
        
        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'test-server_123')
        # Verify successful execution without exception

class TestDeleteRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """Test delete_remote_mcp_server_list"""
    
    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_success(self, mock_delete):
        """Test successful deletion"""
        
        # Should execute successfully without exception
        await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        
        mock_delete.assert_called_once_with(
            mcp_name='name',
            mcp_server='http://srv',
            tenant_id='tid',
            user_id='uid'
        )

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_fail(self, mock_delete):
        """Test deletion failure - exception should propagate from database layer"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_delete.side_effect = SQLAlchemyError("Database error")
        
        with self.assertRaises(SQLAlchemyError):
            await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_nonexistent_server(self, mock_delete):
        """Test deletion of non-existent server - exception should propagate from database layer"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_delete.side_effect = SQLAlchemyError("Record not found")
        
        with self.assertRaises(SQLAlchemyError):
            await delete_remote_mcp_server_list('tid', 'uid', 'http://nonexistent', 'nonexistent')

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_with_special_characters(self, mock_delete):
        """Test deletion of server with special characters"""
        
        await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'test-server_123')
        # Verify successful execution

class TestGetRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """Test get_remote_mcp_server_list"""
    
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_list(self, mock_get):
        """Test getting server list"""
        mock_get.return_value = [
            {"mcp_name": "n1", "mcp_server": "u1", "status": True},
            {"mcp_name": "n2", "mcp_server": "u2", "status": False}
        ]
        
        result = await get_remote_mcp_server_list('tid')
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["remote_mcp_server_name"], "n1")
        self.assertEqual(result[0]["remote_mcp_server"], "u1")
        self.assertTrue(result[0]["status"])
        self.assertEqual(result[1]["remote_mcp_server_name"], "n2")
        self.assertFalse(result[1]["status"])

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_empty(self, mock_get):
        """Test getting empty list"""
        mock_get.return_value = []
        
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(result, [])

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_single_record(self, mock_get):
        """Test getting single record"""
        mock_get.return_value = [
            {"mcp_name": "single_server", "mcp_server": "http://single.com", "status": True}
        ]
        
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["remote_mcp_server_name"], "single_server")
        self.assertEqual(result[0]["remote_mcp_server"], "http://single.com")
        self.assertTrue(result[0]["status"])

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_large_list(self, mock_get):
        """Test getting large list of records"""
        large_list = []
        for i in range(100):
            large_list.append({
                "mcp_name": f"server_{i}",
                "mcp_server": f"http://server_{i}.com",
                "status": i % 2 == 0  # Alternating status
            })
        mock_get.return_value = large_list
        
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(result), 100)
        self.assertEqual(result[0]["remote_mcp_server_name"], "server_0")
        self.assertEqual(result[99]["remote_mcp_server_name"], "server_99")

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_with_special_characters(self, mock_get):
        """Test records with special characters"""
        mock_get.return_value = [
            {"mcp_name": "test-server_123", "mcp_server": "http://test-server.com:8080", "status": True}
        ]
        
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(result[0]["remote_mcp_server_name"], "test-server_123")
        self.assertEqual(result[0]["remote_mcp_server"], "http://test-server.com:8080")

class TestCheckMcpHealthAndUpdateDb(unittest.IsolatedAsyncioTestCase):
    """Test check_mcp_health_and_update_db"""
    
    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_check_health_success(self, mock_health, mock_update):
        """Test successful health check and update"""
        mock_health.return_value = True
        
        # Should execute successfully without exception
        await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')
        
        mock_health.assert_called_once_with(remote_mcp_server='http://srv')
        mock_update.assert_called_once_with(
            mcp_name='name',
            mcp_server='http://srv',
            tenant_id='tid',
            user_id='uid',
            status=True
        )

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_check_health_false(self, mock_health, mock_update):
        """Test health check failure - should raise MCPConnectionError when status is False"""
        mock_health.return_value = False
        
        with self.assertRaises(MCPConnectionError) as context:
            await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')
        
        self.assertEqual(str(context.exception), "MCP connection failed")
        mock_update.assert_called_once_with(
            mcp_name='name',
            mcp_server='http://srv',
            tenant_id='tid',
            user_id='uid',
            status=False
        )

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_update_db_fail(self, mock_health, mock_update):
        """Test database update failure - exception should propagate from database layer"""
        from sqlalchemy.exc import SQLAlchemyError
        
        mock_health.return_value = True
        mock_update.side_effect = SQLAlchemyError("Database error")
        
        with self.assertRaises(SQLAlchemyError):
            await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')

    @patch('backend.services.remote_mcp_service.update_mcp_status_by_name_and_url')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_health_check_exception(self, mock_health, mock_update):
        """Test health check exception - should catch exception, set status to False, and raise MCPConnectionError"""
        mock_health.side_effect = MCPConnectionError("Connection failed")
        
        # Should catch the exception from mcp_server_health, set status to False, and then raise MCPConnectionError
        with self.assertRaises(MCPConnectionError) as context:
            await check_mcp_health_and_update_db('http://srv', 'name', 'tid', 'uid')
        
        self.assertEqual(str(context.exception), "MCP connection failed")
        mock_health.assert_called_once_with(remote_mcp_server='http://srv')
        mock_update.assert_called_once_with(
            mcp_name='name',
            mcp_server='http://srv',
            tenant_id='tid',
            user_id='uid',
            status=False  # Should be False due to exception
        )


class TestDeleteMcpByContainerId(unittest.IsolatedAsyncioTestCase):
    """Test delete_mcp_by_container_id service helper"""

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_container_id')
    async def test_delete_by_container_id_success(self, mock_delete):
        """Test successful soft delete by container ID"""
        await delete_mcp_by_container_id(
            tenant_id='tid',
            user_id='uid',
            container_id='container-123',
        )

        mock_delete.assert_called_once_with(
            container_id='container-123',
            tenant_id='tid',
            user_id='uid',
        )

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_container_id')
    async def test_delete_by_container_id_db_error(self, mock_delete):
        """Test database error when deleting by container ID - should propagate"""
        from sqlalchemy.exc import SQLAlchemyError

        mock_delete.side_effect = SQLAlchemyError("Database error")

        with self.assertRaises(SQLAlchemyError):
            await delete_mcp_by_container_id(
                tenant_id='tid',
                user_id='uid',
                container_id='container-123',
            )

class TestIntegrationScenarios(unittest.IsolatedAsyncioTestCase):
    """Integration test scenarios"""
    
    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_full_lifecycle(self, mock_check_name, mock_health, mock_get, mock_delete, mock_create):
        """Test complete MCP server lifecycle"""
        # 1. Add server
        mock_check_name.return_value = False
        mock_health.return_value = True
        
        # Add server - should succeed without exception
        await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        
        # 2. Get server list
        mock_get.return_value = [{"mcp_name": "name", "mcp_server": "http://srv", "status": True}]
        list_result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(list_result), 1)
        self.assertEqual(list_result[0]["remote_mcp_server_name"], "name")
        
        # 3. Delete server
        await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_duplicate_name_scenario(self, mock_check_name):
        """Test duplicate name scenario"""
        mock_check_name.return_value = True
        
        with self.assertRaises(MCPNameIllegal):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv1', 'duplicate_name')
        
        with self.assertRaises(MCPNameIllegal):
            await add_remote_mcp_server_list('tid', 'uid', 'http://srv2', 'duplicate_name')

class TestUploadAndStartMcpImage(unittest.IsolatedAsyncioTestCase):
    """Test upload_and_start_mcp_image function"""

    @patch('backend.services.remote_mcp_service.add_remote_mcp_server_list')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    @patch('tempfile.NamedTemporaryFile')
    async def test_upload_success(self, mock_temp_file, mock_check_name, mock_container_manager_class, mock_add_server):
        """Test successful upload and container start"""
        # Mock tempfile
        mock_temp_file_obj = MagicMock()
        mock_temp_file_obj.__enter__.return_value = mock_temp_file_obj
        mock_temp_file_obj.__exit__.return_value = None
        mock_temp_file_obj.name = "/tmp/test.tar"
        mock_temp_file.return_value = mock_temp_file_obj

        # Mock container manager
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container_from_tar = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        mock_check_name.return_value = False
        mock_add_server.return_value = None

        result = await upload_and_start_mcp_image(
            tenant_id="tenant123",
            user_id="user456",
            file_content=b"fake tar content",
            filename="test.tar",
            port=5020,
            service_name="test-service",
            env_vars='{"NODE_ENV": "production"}'
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["service_name"], "test-service")
        self.assertEqual(result["mcp_url"], "http://localhost:5020/mcp")
        self.assertEqual(result["container_id"], "container-123")

        # Verify tempfile was created with correct parameters
        mock_temp_file.assert_called_once_with(delete=False, suffix='.tar')

        # Verify container manager was called
        mock_container_manager.start_mcp_container_from_tar.assert_called_once()
        call_kwargs = mock_container_manager.start_mcp_container_from_tar.call_args[1]
        self.assertEqual(call_kwargs["service_name"], "test-service")
        self.assertEqual(call_kwargs["tenant_id"], "tenant123")
        self.assertEqual(call_kwargs["user_id"], "user456")
        self.assertEqual(call_kwargs["host_port"], 5020)
        self.assertEqual(call_kwargs["env_vars"], {"NODE_ENV": "production"})

        # Verify MCP server was registered
        mock_add_server.assert_called_once()

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_upload_invalid_file_type(self, mock_check_name):
        """Test upload with invalid file type"""
        mock_check_name.return_value = False

        with self.assertRaises(ValueError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.txt",  # Not .tar
                port=5020
            )

        self.assertEqual(str(context.exception), "Only .tar files are allowed")

    async def test_upload_file_too_large(self):
        """Test upload with file exceeding size limit"""
        large_content = b"x" * (1024 * 1024 * 1024 + 1)  # Over 1GB

        with self.assertRaises(ValueError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=large_content,
                filename="large.tar",
                port=5020
            )

        self.assertEqual(str(context.exception), "File size exceeds 1GB limit")

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_upload_invalid_env_vars_json(self, mock_check_name):
        """Test upload with invalid JSON in env_vars"""
        mock_check_name.return_value = False

        with self.assertRaises(ValueError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.tar",
                port=5020,
                env_vars="invalid json {"
            )

        self.assertIn("Invalid environment variables format", str(context.exception))

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_upload_env_vars_not_dict(self, mock_check_name):
        """Test upload with environment variables that are not a JSON object"""
        mock_check_name.return_value = False

        with self.assertRaises(ValueError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.tar",
                port=5020,
                env_vars='["VAR1", "VAR2"]'  # Array instead of object
            )

        self.assertEqual(str(context.exception), "Invalid environment variables format: Environment variables must be a JSON object")

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_upload_auto_service_name(self, mock_check_name):
        """Test upload with auto-generated service name"""
        mock_check_name.return_value = False

        with patch('backend.services.remote_mcp_service.add_remote_mcp_server_list'), \
             patch('backend.services.remote_mcp_service.MCPContainerManager') as mock_container_manager_class, \
             patch('tempfile.NamedTemporaryFile') as mock_temp_file:

            # Mock tempfile
            mock_temp_file_obj = MagicMock()
            mock_temp_file_obj.__enter__.return_value = mock_temp_file_obj
            mock_temp_file_obj.__exit__.return_value = None
            mock_temp_file_obj.name = "/tmp/test.tar"
            mock_temp_file.return_value = mock_temp_file_obj

            # Mock container manager
            mock_container_manager = MagicMock()
            mock_container_manager_class.return_value = mock_container_manager
            mock_container_manager.start_mcp_container_from_tar = AsyncMock(return_value={
                "container_id": "container-123",
                "mcp_url": "http://localhost:5020/mcp",
                "host_port": "5020",
                "status": "started",
                "container_name": "my-image-user1234"
            })

            result = await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="my-image.tar",
                port=5020
                # No service_name provided - should auto-generate
            )

            # Should use filename without extension
            self.assertEqual(result["service_name"], "my-image")

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    async def test_upload_name_conflict(self, mock_check_name):
        """Test upload when MCP service name already exists"""
        mock_check_name.return_value = True  # Name already exists

        with self.assertRaises(MCPNameIllegal) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.tar",
                port=5020,
                service_name="existing-service"
            )

        self.assertEqual(str(context.exception), "MCP service name already exists")

    @patch('backend.services.remote_mcp_service.add_remote_mcp_server_list')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    @patch('tempfile.NamedTemporaryFile')
    async def test_upload_container_error(self, mock_temp_file, mock_check_name, mock_container_manager_class, mock_add_server):
        """Test upload when container startup fails"""
        from backend.consts.exceptions import MCPContainerError

        # Mock tempfile
        mock_temp_file_obj = MagicMock()
        mock_temp_file_obj.__enter__.return_value = mock_temp_file_obj
        mock_temp_file_obj.__exit__.return_value = None
        mock_temp_file_obj.name = "/tmp/test.tar"
        mock_temp_file.return_value = mock_temp_file_obj

        # Mock container manager to raise error
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container_from_tar = AsyncMock(
            side_effect=MCPContainerError("Container failed"))

        mock_check_name.return_value = False

        with self.assertRaises(MCPContainerError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.tar",
                port=5020
            )

        self.assertEqual(str(context.exception), "Container failed")

    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    async def test_upload_docker_unavailable(self, mock_container_manager_class, mock_check_name):
        """Test upload when Docker service is unavailable"""
        from backend.consts.exceptions import MCPContainerError

        mock_check_name.return_value = False  # Name doesn't exist
        mock_container_manager_class.side_effect = MCPContainerError("Docker unavailable")

        with self.assertRaises(MCPContainerError) as context:
            await upload_and_start_mcp_image(
                tenant_id="tenant123",
                user_id="user456",
                file_content=b"content",
                filename="test.tar",
                port=5020
            )

        self.assertEqual(str(context.exception), "Docker unavailable")

    @patch('backend.services.remote_mcp_service.add_remote_mcp_server_list')
    @patch('backend.services.remote_mcp_service.MCPContainerManager')
    @patch('backend.services.remote_mcp_service.check_mcp_name_exists')
    @patch('tempfile.NamedTemporaryFile')
    @patch('os.unlink', side_effect=OSError("Permission denied"))
    @patch('backend.services.remote_mcp_service.logger')
    async def test_upload_temp_file_cleanup_warning(self, mock_logger, mock_unlink, mock_temp_file, mock_check_name, mock_container_manager_class, mock_add_server):
        """Test upload with temporary file cleanup failure - should log warning but succeed"""
        # Mock tempfile
        mock_temp_file_obj = MagicMock()
        mock_temp_file_obj.__enter__.return_value = mock_temp_file_obj
        mock_temp_file_obj.__exit__.return_value = None
        mock_temp_file_obj.name = "/tmp/test.tar"
        mock_temp_file.return_value = mock_temp_file_obj

        # Mock container manager
        mock_container_manager = MagicMock()
        mock_container_manager_class.return_value = mock_container_manager
        mock_container_manager.start_mcp_container_from_tar = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        mock_check_name.return_value = False
        mock_add_server.return_value = None

        result = await upload_and_start_mcp_image(
            tenant_id="tenant123",
            user_id="user456",
            file_content=b"content",
            filename="test.tar",
            port=5020
        )

        # Should still succeed despite cleanup failure
        self.assertEqual(result["status"], "success")

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_call_args = mock_logger.warning.call_args[0][0]
        self.assertIn("Failed to clean up temporary file /tmp/test.tar", warning_call_args)


if __name__ == '__main__':
    unittest.main()
