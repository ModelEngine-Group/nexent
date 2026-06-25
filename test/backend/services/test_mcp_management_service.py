"""
Unit tests for backend/services/mcp_management_service.py
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Mock all database dependencies before imports
# Create proper mock package hierarchy
db_client_mock = MagicMock()
db_client_mock.get_db_session = MagicMock()
db_client_mock.as_dict = MagicMock()
db_client_mock.filter_property = MagicMock()
db_client_mock.MinioClient = MagicMock()

# Mock database.client at all possible import paths
sys.modules['database.client'] = db_client_mock
sys.modules['backend.database.client'] = db_client_mock

# Mock database submodules
sys.modules['database.community_mcp_db'] = MagicMock()
sys.modules['database.remote_mcp_db'] = MagicMock()
sys.modules['database.db_models'] = MagicMock()
sys.modules['database.user_tenant_db'] = MagicMock()

# Also mock backend.database submodules
sys.modules['backend.database.community_mcp_db'] = sys.modules['database.community_mcp_db']
sys.modules['backend.database.remote_mcp_db'] = sys.modules['database.remote_mcp_db']
sys.modules['backend.database.db_models'] = sys.modules['database.db_models']
sys.modules['backend.database.user_tenant_db'] = sys.modules['database.user_tenant_db']

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import real exception classes - use same path as source code
from consts.exceptions import McpNotFoundError, McpValidationError

from backend.services.mcp_management_service import (
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    publish_community_mcp_service,
    update_community_mcp_service,
    delete_community_mcp_service,
    list_my_community_mcp_services,
    list_registry_mcp_services,
)


class TestListCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.get_mcp_community_records')
    async def test_list_empty(self, mock_get):
        """Test listing community services returns empty result."""
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}
        result = await list_community_mcp_services(limit=30)
        self.assertEqual(result["count"], 0)

    @patch('backend.services.mcp_management_service.get_mcp_community_records')
    async def test_list_with_items(self, mock_get):
        """Test listing community services with items returns mapped result."""
        mock_get.return_value = {
            "count": 2, "nextCursor": None,
            "items": [
                {"community_id": 1, "mcp_name": "svc1", "version": "1.0",
                 "description": "d", "transport_type": "url",
                 "mcp_server": "http://srv", "config_json": None,
                 "registry_json": None, "tags": ["a"],
                 "create_time": "t", "update_time": "t"},
            ],
        }
        result = await list_community_mcp_services()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "svc1")


class TestListCommunityMcpTagStats(unittest.TestCase):

    @patch('backend.services.mcp_management_service.get_mcp_community_tag_stats')
    def test_list_tag_stats(self, mock_get):
        """Test community tag statistics retrieval."""
        mock_get.return_value = [{"tag": "python", "count": 5}]
        result = list_community_mcp_tag_stats()
        self.assertEqual(len(result), 1)


class TestPublishCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.create_mcp_community_record')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_success(self, mock_get, mock_create):
        """Test successful publishing of a local MCP service to community."""
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "version": "1.0", "tags": ["a"],
            "registry_json": None, "config_json": None,
        }
        mock_create.return_value = 42
        result = await publish_community_mcp_service(tenant_id="tid", user_id="uid", mcp_id=1)
        self.assertEqual(result, 42)

    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_not_found(self, mock_get):
        """Test publishing fails when source MCP record is not found."""
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await publish_community_mcp_service(tenant_id="tid", user_id="uid", mcp_id=999)


class TestUpdateCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.update_mcp_community_record_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_community_record_by_id_and_tenant')
    async def test_update_success(self, mock_get, mock_update):
        """Test successful community MCP service update."""
        mock_get.return_value = {"community_id": 1, "config_json": None, "registry_json": None}
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", community_id=1,
            name="new", description="d", tags=["a"], version="2.0", registry_json=None,
        )
        mock_update.assert_called_once()

    @patch('backend.services.mcp_management_service.get_mcp_community_record_by_id_and_tenant')
    async def test_update_not_found(self, mock_get):
        """Test update fails when community record is not found."""
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await update_community_mcp_service(
                tenant_id="tid", user_id="uid", community_id=999,
                name="x", description="d", tags=[], version="1.0", registry_json=None,
            )


class TestDeleteCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.delete_mcp_community_record_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_community_record_by_id_and_tenant')
    async def test_delete_success(self, mock_get, mock_delete):
        """Test successful deletion of a community MCP service."""
        mock_get.return_value = {"community_id": 1}
        await delete_community_mcp_service(tenant_id="tid", user_id="uid", community_id=1)
        mock_delete.assert_called_once()

    @patch('backend.services.mcp_management_service.get_mcp_community_record_by_id_and_tenant')
    async def test_delete_not_found(self, mock_get):
        """Test deletion fails when community record is not found."""
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await delete_community_mcp_service(tenant_id="tid", user_id="uid", community_id=999)


class TestListMyCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.list_mcp_community_records_by_tenant')
    async def test_list_empty(self, mock_list):
        """Test listing current user's published services returns empty."""
        mock_list.return_value = []
        result = await list_my_community_mcp_services(tenant_id="tid")
        self.assertEqual(result["count"], 0)


class TestListRegistryMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.aiohttp.ClientSession')
    async def test_list_success(self, mock_session_cls):
        """Test successful registry service listing via HTTP."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"servers": [{"name": "s1"}], "metadata": {}})
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session

        result = await list_registry_mcp_services()
        self.assertEqual(len(result["servers"]), 1)

    @patch('backend.services.mcp_management_service.aiohttp.ClientSession')
    async def test_list_error(self, mock_session_cls):
        """Test registry listing raises RuntimeError on HTTP error status."""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session

        with self.assertRaises(RuntimeError):
            await list_registry_mcp_services()


if __name__ == '__main__':
    unittest.main()
