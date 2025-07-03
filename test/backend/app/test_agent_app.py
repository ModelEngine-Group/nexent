import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Mock external dependencies before importing the modules that use them
sys.modules['database.client'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['agents.create_agent_info'] = MagicMock()
sys.modules['nexent.core.agents.run_agent'] = MagicMock()

# Now it's safe to import the modules we need to test
from fastapi.testclient import TestClient
from fastapi import HTTPException
from fastapi import FastAPI
from backend.apps.agent_app import router

# Create FastAPI app for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestAgentApp(unittest.TestCase):
    def setUp(self):
        self.mock_auth_header = {"Authorization": "Bearer test_token"}
        self.mock_conversation_id = 123
        
    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    @patch("backend.apps.agent_app.submit")
    async def test_agent_run_api_success(self, mock_submit, mock_get_user_info, mock_agent_run, 
                                 mock_agent_run_manager, mock_create_run_info):
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        mock_agent_run.return_value = AsyncMock(__aiter__=AsyncMock(return_value=["chunk1", "chunk2"]))
        
        # Test the endpoint
        response = client.post(
            "/agent/run",
            json={
                "agent_id": "test_agent",
                "conversation_id": self.mock_conversation_id,
                "query": "test query",
                "history": [],
                "minio_files": [],
                "is_debug": False
            },
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_agent_run_manager.register_agent_run.assert_called_once()
        mock_submit.assert_called()
        mock_agent_run_manager.unregister_agent_run.assert_called_once_with(self.mock_conversation_id)

    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    @patch("backend.apps.agent_app.submit")
    async def test_agent_run_api_debug_mode(self, mock_submit, mock_get_user_info, mock_agent_run, 
                                   mock_agent_run_manager, mock_create_run_info):
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        mock_agent_run.return_value = AsyncMock(__aiter__=AsyncMock(return_value=["chunk1", "chunk2"]))
        
        # Test the endpoint in debug mode
        response = client.post(
            "/agent/run",
            json={
                "agent_id": "test_agent",
                "conversation_id": self.mock_conversation_id,
                "query": "test query",
                "history": [],
                "minio_files": [],
                "is_debug": True
            },
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_submit.assert_not_called()
        mock_agent_run_manager.unregister_agent_run.assert_called_once_with(self.mock_conversation_id)

    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    async def test_agent_run_api_exception(self, mock_get_user_info, mock_agent_run, 
                                  mock_agent_run_manager, mock_create_run_info):
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        mock_agent_run.return_value = AsyncMock(__aiter__=AsyncMock(side_effect=Exception("Test error")))
        
        # Test the endpoint with exception
        response = client.post(
            "/agent/run",
            json={
                "agent_id": "test_agent",
                "conversation_id": self.mock_conversation_id,
                "query": "test query",
                "history": [],
                "minio_files": [],
                "is_debug": False
            },
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent run error: Test error", response.text)

    @patch("backend.apps.agent_app.agent_run_manager")
    def test_agent_stop_api_success(self, mock_agent_run_manager):
        # Setup mocks
        mock_agent_run_manager.stop_agent_run.return_value = True
        
        # Test the endpoint
        response = client.get(f"/agent/stop/{self.mock_conversation_id}")
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_agent_run_manager.stop_agent_run.assert_called_once_with(self.mock_conversation_id)
        self.assertIn("success", response.json()["status"])

    @patch("backend.apps.agent_app.agent_run_manager")
    def test_agent_stop_api_not_found(self, mock_agent_run_manager):
        # Setup mocks
        mock_agent_run_manager.stop_agent_run.return_value = False
        
        # Test the endpoint
        response = client.get(f"/agent/stop/{self.mock_conversation_id}")
        
        # Assertions
        self.assertEqual(response.status_code, 404)
        mock_agent_run_manager.stop_agent_run.assert_called_once_with(self.mock_conversation_id)
        self.assertIn("no running agent found", response.json()["detail"])

    @patch("backend.apps.agent_app.config_manager")
    def test_reload_config(self, mock_config_manager):
        # Setup mocks
        mock_config_manager.force_reload.return_value = {"status": "reloaded"}
        
        # Test the endpoint
        response = client.post("/agent/reload_config")
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_config_manager.force_reload.assert_called_once()
        self.assertEqual(response.json(), {"status": "reloaded"})

    @patch("backend.apps.agent_app.list_main_agent_info_impl")
    def test_list_main_agent_info_api_success(self, mock_list_main_agent):
        # Setup mocks
        mock_list_main_agent.return_value = [{"agent_id": "agent1"}, {"agent_id": "agent2"}]
        
        # Test the endpoint
        response = client.get("/agent/list", headers=self.mock_auth_header)
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_list_main_agent.assert_called_once_with(self.mock_auth_header["Authorization"])
        self.assertEqual(len(response.json()), 2)

    @patch("backend.apps.agent_app.list_main_agent_info_impl")
    def test_list_main_agent_info_api_exception(self, mock_list_main_agent):
        # Setup mocks
        mock_list_main_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.get("/agent/list", headers=self.mock_auth_header)
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent list error", response.json()["detail"])

    @patch("backend.apps.agent_app.get_agent_info_impl")
    def test_search_agent_info_api_success(self, mock_get_agent_info):
        # Setup mocks
        mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}
        
        # Test the endpoint
        response = client.post(
            "/agent/search_info",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_get_agent_info.assert_called_once_with(123, self.mock_auth_header["Authorization"])
        self.assertEqual(response.json()["agent_id"], 123)

    @patch("backend.apps.agent_app.get_agent_info_impl")
    def test_search_agent_info_api_exception(self, mock_get_agent_info):
        # Setup mocks
        mock_get_agent_info.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.post(
            "/agent/search_info",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent search info error", response.json()["detail"])

    @patch("backend.apps.agent_app.get_creating_sub_agent_info_impl")
    def test_get_creating_sub_agent_info_api_success(self, mock_get_creating_agent):
        # Setup mocks
        mock_get_creating_agent.return_value = {"agent_id": 456}
        
        # Test the endpoint
        response = client.post(
            "/agent/get_creating_sub_agent_id",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_get_creating_agent.assert_called_once_with(123, self.mock_auth_header["Authorization"])
        self.assertEqual(response.json()["agent_id"], 456)

    @patch("backend.apps.agent_app.get_creating_sub_agent_info_impl")
    def test_get_creating_sub_agent_info_api_exception(self, mock_get_creating_agent):
        # Setup mocks
        mock_get_creating_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.post(
            "/agent/get_creating_sub_agent_id",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent create error", response.json()["detail"])

    @patch("backend.apps.agent_app.update_agent_info_impl")
    def test_update_agent_info_api_success(self, mock_update_agent):
        # Setup mocks
        mock_update_agent.return_value = None
        
        # Test the endpoint
        response = client.post(
            "/agent/update",
            json={"agent_id": 123, "name": "Updated Agent"},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_update_agent.assert_called_once()
        self.assertEqual(response.json(), {})

    @patch("backend.apps.agent_app.update_agent_info_impl")
    def test_update_agent_info_api_exception(self, mock_update_agent):
        # Setup mocks
        mock_update_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.post(
            "/agent/update",
            json={"agent_id": 123, "name": "Updated Agent"},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent update error", response.json()["detail"])

    @patch("backend.apps.agent_app.delete_agent_impl")
    def test_delete_agent_api_success(self, mock_delete_agent):
        # Setup mocks
        mock_delete_agent.return_value = None
        
        # Test the endpoint
        response = client.request(
            "DELETE",
            "/agent",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_delete_agent.assert_called_once_with(123, self.mock_auth_header["Authorization"])
        self.assertEqual(response.json(), {})

    @patch("backend.apps.agent_app.delete_agent_impl")
    def test_delete_agent_api_exception(self, mock_delete_agent):
        # Setup mocks
        mock_delete_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.request(
            "DELETE",
            "/agent",
            json={"agent_id": 123},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent delete error", response.json()["detail"])

    @patch("backend.apps.agent_app.export_agent_impl")
    async def test_export_agent_api_success(self, mock_export_agent):
        # Setup mocks
        mock_export_agent.return_value = '{"agent_id": "test_agent", "name": "Test Agent"}'
        
        # Test the endpoint
        response = client.post(
            "/agent/export",
            json={"agent_id": "test_agent"},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_export_agent.assert_called_once_with("test_agent", self.mock_auth_header["Authorization"])
        self.assertEqual(response.json()["code"], 0)
        self.assertEqual(response.json()["message"], "success")

    @patch("backend.apps.agent_app.export_agent_impl")
    async def test_export_agent_api_exception(self, mock_export_agent):
        # Setup mocks
        mock_export_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.post(
            "/agent/export",
            json={"agent_id": "test_agent"},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent export error", response.json()["detail"])

    @patch("backend.apps.agent_app.import_agent_impl")
    def test_import_agent_api_success(self, mock_import_agent):
        # Setup mocks
        mock_import_agent.return_value = None
        
        # Test the endpoint
        response = client.post(
            "/agent/import",
            json={
                "agent_id": 123,
                "agent_info": {
                    "name": "Imported Agent",
                    "description": "Test description",
                    "business_description": "Test business",
                    "model_name": "gpt-4",
                    "max_steps": 10,
                    "provide_run_summary": True,
                    "prompt": "Test prompt",
                    "enabled": True,
                    "tools": [],
                    "managed_agents": []
                }
            },
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_import_agent.assert_called_once()
        args, kwargs = mock_import_agent.call_args
        self.assertEqual(args[0], 123)
        self.assertEqual(args[2], self.mock_auth_header["Authorization"])
        self.assertEqual(args[1].name, "Imported Agent")
        self.assertEqual(args[1].description, "Test description")
        self.assertEqual(args[1].business_description, "Test business")
        self.assertEqual(args[1].model_name, "gpt-4")
        self.assertEqual(args[1].max_steps, 10)
        self.assertEqual(args[1].provide_run_summary, True)
        self.assertEqual(args[1].prompt, "Test prompt")
        self.assertEqual(args[1].enabled, True)
        self.assertEqual(args[1].tools, [])
        self.assertEqual(args[1].managed_agents, [])
        self.assertEqual(response.json(), {})

    @patch("backend.apps.agent_app.import_agent_impl")
    def test_import_agent_api_exception(self, mock_import_agent):
        # Setup mocks
        mock_import_agent.side_effect = Exception("Test error")
        
        # Test the endpoint
        response = client.post(
            "/agent/import",
            json={
                "agent_id": 123,
                "agent_info": {
                    "name": "Imported Agent",
                    "description": "Test description",
                    "business_description": "Test business",
                    "model_name": "gpt-4",
                    "max_steps": 10,
                    "provide_run_summary": True,
                    "prompt": "Test prompt",
                    "enabled": True,
                    "tools": [],
                    "managed_agents": []
                }
            },
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Agent import error", response.json()["detail"])

    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    @patch("backend.apps.agent_app.submit")
    async def test_agent_run_api_streaming_response(self, mock_submit, mock_get_user_info, mock_agent_run, 
                               mock_agent_run_manager, mock_create_run_info):
        """详细测试agent_run_api函数的StreamingResponse和异步生成部分"""
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        
        # 模拟异步生成器返回多个块
        chunks = ["chunk1", "chunk2", "chunk3"]
        async def mock_aiter():
            for chunk in chunks:
                yield chunk
                
        mock_agent_run.return_value.__aiter__.return_value = mock_aiter()
        
        # 创建测试客户端
        test_client = TestClient(app)
        
        # 发送请求但不等待完成响应（因为我们需要手动迭代流式响应）
        with test_client.stream("POST", 
            "/agent/run",
            json={
                "agent_id": 123,
                "conversation_id": 456,
                "query": "test streaming",
                "history": [],
                "minio_files": [],
                "is_debug": False
            },
            headers=self.mock_auth_header
        ) as response:
            # 验证响应状态码
            self.assertEqual(response.status_code, 200)
            
            # 验证响应头
            self.assertEqual(response.headers["Content-Type"], "text/event-stream")
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            self.assertEqual(response.headers["Connection"], "keep-alive")
            
            # 收集流式响应内容
            content = ""
            for line in response.iter_lines():
                if line:
                    content += line.decode() + "\n"
            
            # 验证内容包含所有块
            for chunk in chunks:
                self.assertIn(f"data: {chunk}", content)
        
        # 验证非调试模式下的行为
        mock_submit.assert_called()
        mock_agent_run_manager.register_agent_run.assert_called_once()
        mock_agent_run_manager.unregister_agent_run.assert_called_once_with(456)
    
    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    @patch("backend.apps.agent_app.submit")
    async def test_agent_run_api_streaming_exception(self, mock_submit, mock_get_user_info, mock_agent_run, 
                                mock_agent_run_manager, mock_create_run_info):
        """测试agent_run_api函数中的异常处理流程"""
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        
        # 模拟异步生成器抛出异常
        async def mock_aiter_with_exception():
            yield "chunk1"  # 先产生一个正常块
            raise Exception("Stream error")  # 然后抛出异常
                
        mock_agent_run.return_value.__aiter__.return_value = mock_aiter_with_exception()
        
        # 创建测试客户端
        test_client = TestClient(app)
        
        # 测试异常处理
        with test_client.stream("POST", 
            "/agent/run",
            json={
                "agent_id": 123,
                "conversation_id": 789,
                "query": "test exception",
                "history": [],
                "minio_files": [],
                "is_debug": False
            },
            headers=self.mock_auth_header
        ) as response:
            # 验证初始状态码是200（连接成功建立）
            self.assertEqual(response.status_code, 200)
            
            # 收集流式响应内容
            content = ""
            try:
                for line in response.iter_lines():
                    if line:
                        content += line.decode() + "\n"
            except Exception:
                # 预期会发生异常
                pass
                
            # 验证第一个块能正确传输
            self.assertIn("data: chunk1", content)
        
        # 验证清理逻辑即使在异常情况下也会执行
        mock_agent_run_manager.unregister_agent_run.assert_called_once_with(789)

    @patch("backend.apps.agent_app.create_agent_run_info")
    @patch("backend.apps.agent_app.agent_run_manager")
    @patch("backend.apps.agent_app.agent_run")
    @patch("backend.apps.agent_app.get_current_user_info")
    @patch("backend.apps.agent_app.submit")
    async def test_agent_run_api_chunked_streaming(self, mock_submit, mock_get_user_info, mock_agent_run, 
                                mock_agent_run_manager, mock_create_run_info):
        """详细测试agent_run_api函数对不同大小块的处理"""
        # Setup mocks
        mock_get_user_info.return_value = ("user_id", "email", "en")
        mock_create_run_info.return_value = AsyncMock()
        
        # 模拟异步生成器返回不同大小的块
        chunks = ["small", "medium_sized_chunk", "this_is_a_very_large_chunk_to_test_buffer_handling"*5]
        async def mock_aiter():
            for chunk in chunks:
                yield chunk
                
        mock_agent_run.return_value.__aiter__.return_value = mock_aiter()
        
        # 创建测试客户端
        test_client = TestClient(app)
        
        # 发送请求
        with test_client.stream("POST", 
            "/agent/run",
            json={
                "agent_id": 123,
                "conversation_id": 101,
                "query": "test different chunks",
                "history": [],
                "minio_files": [],
                "is_debug": True  # 这次使用调试模式
            },
            headers=self.mock_auth_header
        ) as response:
            # 验证响应状态码
            self.assertEqual(response.status_code, 200)
            
            # 收集流式响应内容
            content = ""
            for line in response.iter_lines():
                if line:
                    content += line.decode() + "\n"
            
            # 验证内容包含所有块
            for chunk in chunks:
                self.assertIn(f"data: {chunk}", content)
        
        # 验证调试模式下的行为
        mock_submit.assert_not_called()  # 调试模式下不保存对话
        mock_agent_run_manager.register_agent_run.assert_called_once()
        mock_agent_run_manager.unregister_agent_run.assert_called_once_with(101)

    @patch("backend.apps.agent_app.export_agent_impl")
    async def test_export_agent_api_detailed(self, mock_export_agent):
        """详细测试export_agent_api函数，包括ConversationResponse构建"""
        # Setup mocks - 返回复杂的JSON数据
        agent_data = {
            "agent_id": 456,
            "name": "Complex Agent",
            "description": "Detailed testing",
            "tools": [{"id": 1, "name": "tool1"}, {"id": 2, "name": "tool2"}],
            "managed_agents": [789, 101],
            "other_fields": "some values"
        }
        mock_export_agent.return_value = agent_data
        
        # Test with complex data
        response = client.post(
            "/agent/export",
            json={"agent_id": 456},
            headers=self.mock_auth_header
        )
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        mock_export_agent.assert_called_once_with(456, self.mock_auth_header["Authorization"])
        
        # 验证ConversationResponse的正确构建
        response_data = response.json()
        self.assertEqual(response_data["code"], 0)
        self.assertEqual(response_data["message"], "success")
        self.assertEqual(response_data["data"], agent_data)

    @patch("backend.apps.agent_app.export_agent_impl")
    async def test_export_agent_api_empty_response(self, mock_export_agent):
        """测试export_agent_api处理空响应的情况"""
        # 设置mock返回空数据
        mock_export_agent.return_value = {}
        
        # 发送请求
        response = client.post(
            "/agent/export",
            json={"agent_id": 789},
            headers=self.mock_auth_header
        )
        
        # 验证
        self.assertEqual(response.status_code, 200)
        mock_export_agent.assert_called_once_with(789, self.mock_auth_header["Authorization"])
        
        # 验证空数据也能正确封装在ConversationResponse中
        response_data = response.json()
        self.assertEqual(response_data["code"], 0)
        self.assertEqual(response_data["message"], "success")
        self.assertEqual(response_data["data"], {})


if __name__ == "__main__":
    unittest.main()
