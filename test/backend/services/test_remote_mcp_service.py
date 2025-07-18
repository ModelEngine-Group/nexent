import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.responses import JSONResponse

# mock MinioClient，防止其初始化真实连接
import sys
sys.modules['boto3'] = MagicMock()

# 需要测试的四个方法
with patch('backend.database.client.MinioClient', MagicMock()):
    from backend.services.remote_mcp_service import (
        mcp_server_health,
        add_remote_mcp_server_list,
        delete_remote_mcp_server_list,
        get_remote_mcp_server_list
    )

class TestMcpServerHealth(unittest.IsolatedAsyncioTestCase):
    """测试 mcp_server_health"""
    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_success(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = True
        mock_client_cls.return_value = mock_client
        resp = await mcp_server_health('http://test-server')
        self.assertIsInstance(resp, JSONResponse)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b'{"message":"Successfully connected to remote MCP server","status":"success"}')

    @patch('backend.services.remote_mcp_service.Client')
    async def test_health_fail(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.is_connected.return_value = False
        mock_client_cls.return_value = mock_client
        resp = await mcp_server_health('http://test-server')
        self.assertEqual(resp.status_code, 503)
        self.assertIn(b'Cannot connect to remote MCP server', resp.body)

    @patch('backend.services.remote_mcp_service.Client', side_effect=Exception('fail'))
    async def test_health_exception(self, mock_client_cls):
        resp = await mcp_server_health('http://test-server')
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b'Failed to add remote MCP proxy', resp.body)

class TestAddRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """测试 add_remote_mcp_server_list"""
    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_add_success(self, mock_health, mock_create):
        mock_health.return_value = JSONResponse(status_code=200, content={"message": "mock"})
        mock_create.return_value = True
        resp = await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertIsInstance(resp, JSONResponse)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Successfully added remote MCP proxy', resp.body)

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_add_health_fail(self, mock_health, mock_create):
        mock_health.return_value = JSONResponse(status_code=503, content={"message": "mock"})
        resp = await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertEqual(resp.status_code, 503)

    @patch('backend.services.remote_mcp_service.create_mcp_record')
    @patch('backend.services.remote_mcp_service.mcp_server_health')
    async def test_add_db_fail(self, mock_health, mock_create):
        mock_health.return_value = JSONResponse(status_code=200, content={"message": "mock"})
        mock_create.return_value = False
        resp = await add_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b'database error', resp.body)

class TestDeleteRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """测试 delete_remote_mcp_server_list"""
    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_success(self, mock_delete):
        mock_delete.return_value = True
        resp = await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertIsInstance(resp, JSONResponse)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Successfully added remote MCP proxy', resp.body)

    @patch('backend.services.remote_mcp_service.delete_mcp_record_by_name_and_url')
    async def test_delete_fail(self, mock_delete):
        mock_delete.return_value = False
        resp = await delete_remote_mcp_server_list('tid', 'uid', 'http://srv', 'name')
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b'Failed to delete remote MCP server', resp.body)

class TestGetRemoteMcpServerList(unittest.IsolatedAsyncioTestCase):
    """测试 get_remote_mcp_server_list"""
    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_list(self, mock_get):
        mock_get.return_value = [
            {"mcp_name": "n1", "mcp_server": "u1", "status": True},
            {"mcp_name": "n2", "mcp_server": "u2", "status": False}
        ]
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["remote_mcp_server_name"], "n1")
        self.assertEqual(result[1]["status"], False)

    @patch('backend.services.remote_mcp_service.get_mcp_records_by_tenant')
    async def test_get_empty(self, mock_get):
        mock_get.return_value = []
        result = await get_remote_mcp_server_list('tid')
        self.assertEqual(result, [])

if __name__ == '__main__':
    unittest.main()
