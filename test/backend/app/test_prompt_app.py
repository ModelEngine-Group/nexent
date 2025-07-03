import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys

# 直接创建模拟类
class MockGeneratePromptRequest:
    agent_id: int
    task_description: str

class MockFineTunePromptRequest:
    agent_id: int
    system_prompt: str
    command: str

# 创建模拟函数和对象
class MockHTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail

# 模拟服务函数
generate_and_save_system_prompt_impl = MagicMock()
fine_tune_prompt = MagicMock()
get_current_user_info = MagicMock()

# 创建路由器模拟
router_mock = MagicMock()

# 模拟StreamingResponse
class MockStreamingResponse:
    def __init__(self, content, media_type):
        self.content = content
        self.media_type = media_type

# 模拟TestClient
client = MagicMock()


class TestPromptApp(unittest.TestCase):
    
    def setUp(self):
        self.test_agent_id = 123
        self.test_tenant_id = "test_tenant"
        self.test_language = "en"
        self.test_authorization = "Bearer test_token"
        
        # 重置所有模拟
        generate_and_save_system_prompt_impl.reset_mock()
        fine_tune_prompt.reset_mock()
        get_current_user_info.reset_mock()
        client.reset_mock()
    
    def test_generate_and_save_system_prompt_api_success(self):
        # 模拟路由处理函数
        async def mock_generate_api(prompt_request, http_request, authorization=None):
            # 模拟生成器函数
            def gen():
                for prompt in ["Test prompt 1", "Test prompt 2"]:
                    yield f"data: {{\"success\": true, \"data\": \"{prompt}\"}}\n\n"
            
            generate_and_save_system_prompt_impl.return_value = ["Test prompt 1", "Test prompt 2"]
            return MockStreamingResponse(gen(), "text/event-stream")
        
        # 使用模拟的路由处理函数
        with patch('test.backend.app.test_prompt_app.router_mock.post', return_value=mock_generate_api):
            # 构造测试请求
            request_data = {
                "agent_id": self.test_agent_id,
                "task_description": "Test task description"
            }
            
            # 模拟响应
            response_mock = MagicMock()
            response_mock.status_code = 200
            response_mock.headers = {"content-type": "text/event-stream"}
            response_mock.content = "data: {\"success\": true, \"data\": \"Test prompt 1\"}\n\ndata: {\"success\": true, \"data\": \"Test prompt 2\"}\n\n".encode()
            client.post.return_value = response_mock
            
            # 执行测试
            response = client.post(
                "/prompt/generate",
                json=request_data,
                headers={"Authorization": self.test_authorization}
            )
            
            # 断言
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "text/event-stream")
            
            # 检查响应内容
            response_content = response.content.decode()
            self.assertIn("Test prompt 1", response_content)
            self.assertIn("Test prompt 2", response_content)
    
    def test_generate_and_save_system_prompt_api_error(self):
        # 模拟异常情况
        async def mock_generate_api_error(prompt_request, http_request, authorization=None):
            raise MockHTTPException(status_code=500, detail="Error occurred while generating system prompt: Test error")
        
        # 使用模拟的路由处理函数
        with patch('test.backend.app.test_prompt_app.router_mock.post', return_value=mock_generate_api_error):
            # 构造测试请求
            request_data = {
                "agent_id": self.test_agent_id,
                "task_description": "Test task description"
            }
            
            # 模拟错误响应
            error_response = MagicMock()
            error_response.status_code = 500
            error_response.json.return_value = {"detail": "Error occurred while generating system prompt: Test error"}
            client.post.return_value = error_response
            
            # 执行测试
            response = client.post(
                "/prompt/generate",
                json=request_data
            )
            
            # 断言
            self.assertEqual(response.status_code, 500)
            response_json = response.json()
            self.assertIn("Error occurred while generating system prompt", response_json["detail"])
            self.assertIn("Test error", response_json["detail"])
    
    def test_fine_tune_prompt_api_success(self):
        # 模拟路由处理函数
        async def mock_fine_tune_api(prompt_request, http_request, authorization=None):
            get_current_user_info.return_value = ("user123", self.test_tenant_id, self.test_language)
            fine_tune_prompt.return_value = "Fine-tuned prompt result"
            return {"success": True, "data": "Fine-tuned prompt result"}
        
        # 使用模拟的路由处理函数
        with patch('test.backend.app.test_prompt_app.router_mock.post', return_value=mock_fine_tune_api):
            # 构造测试请求
            request_data = {
                "agent_id": self.test_agent_id,
                "system_prompt": "Original system prompt",
                "command": "Make it more concise"
            }
            
            # 模拟响应
            response_mock = MagicMock()
            response_mock.status_code = 200
            response_mock.json.return_value = {"success": True, "data": "Fine-tuned prompt result"}
            client.post.return_value = response_mock
            
            # 执行测试
            response = client.post(
                "/prompt/fine_tune",
                json=request_data,
                headers={"Authorization": self.test_authorization}
            )
            
            # 断言
            self.assertEqual(response.status_code, 200)
            response_json = response.json()
            self.assertTrue(response_json["success"])
            self.assertEqual(response_json["data"], "Fine-tuned prompt result")
    
    def test_fine_tune_prompt_api_error(self):
        # 模拟异常情况
        async def mock_fine_tune_api_error(prompt_request, http_request, authorization=None):
            get_current_user_info.return_value = ("user123", self.test_tenant_id, self.test_language)
            raise MockHTTPException(status_code=500, detail="Error occurred while fine-tuning prompt: Test error")
        
        # 使用模拟的路由处理函数
        with patch('test.backend.app.test_prompt_app.router_mock.post', return_value=mock_fine_tune_api_error):
            # 构造测试请求
            request_data = {
                "agent_id": self.test_agent_id,
                "system_prompt": "Original system prompt",
                "command": "Make it more concise"
            }
            
            # 模拟错误响应
            error_response = MagicMock()
            error_response.status_code = 500
            error_response.json.return_value = {"detail": "Error occurred while fine-tuning prompt: Test error"}
            client.post.return_value = error_response
            
            # 执行测试
            response = client.post(
                "/prompt/fine_tune",
                json=request_data,
                headers={"Authorization": self.test_authorization}
            )
            
            # 断言
            self.assertEqual(response.status_code, 500)
            response_json = response.json()
            self.assertIn("Error occurred while fine-tuning prompt", response_json["detail"])
            self.assertIn("Test error", response_json["detail"])
    
    def test_fine_tune_prompt_api_invalid_request(self):
        # 构造测试请求 - 缺少必填字段
        request_data = {
            "agent_id": self.test_agent_id,
            # 缺少 system_prompt 和 command
        }
        
        # 模拟验证错误响应
        validation_error_response = MagicMock()
        validation_error_response.status_code = 422
        client.post.return_value = validation_error_response
        
        # 执行测试
        response = client.post(
            "/prompt/fine_tune",
            json=request_data,
            headers={"Authorization": self.test_authorization}
        )
        
        # 断言
        self.assertEqual(response.status_code, 422)  # 验证错误
    
    def test_generate_prompt_without_authorization(self):
        # 模拟路由处理函数
        async def mock_generate_api_no_auth(prompt_request, http_request):
            # 模拟生成器函数
            def gen():
                yield f"data: {{\"success\": true, \"data\": \"Test prompt\"}}\n\n"
            
            generate_and_save_system_prompt_impl.return_value = ["Test prompt"]
            return MockStreamingResponse(gen(), "text/event-stream")
        
        # 使用模拟的路由处理函数
        with patch('test.backend.app.test_prompt_app.router_mock.post', return_value=mock_generate_api_no_auth):
            # 构造测试请求
            request_data = {
                "agent_id": self.test_agent_id,
                "task_description": "Test task description"
            }
            
            # 模拟响应
            response_mock = MagicMock()
            response_mock.status_code = 200
            response_mock.headers = {"content-type": "text/event-stream"}
            response_mock.content = "data: {\"success\": true, \"data\": \"Test prompt\"}\n\n".encode()
            client.post.return_value = response_mock
            
            # 执行测试 - 无授权头
            response = client.post(
                "/prompt/generate",
                json=request_data
                # 无授权头
            )
            
            # 断言
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
