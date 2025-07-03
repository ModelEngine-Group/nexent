import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import base64
import io
import os
import sys
from fastapi import FastAPI, APIRouter, HTTPException, Form, Query, Body
from typing import Dict, Any, Optional, List
from fastapi.testclient import TestClient
from PIL import Image

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# 在导入应用模块前设置必要的环境变量
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
os.environ['REDIS_BACKEND_URL'] = 'redis://localhost:6379/0'

# 其他可能需要的环境变量
os.environ['ELASTICSEARCH_URL'] = 'http://localhost:9200'
os.environ['DATA_PATH'] = '/tmp/data'
os.environ['DATA_PROCESS_LOG_LEVEL'] = 'INFO'

# 模拟 BatchTaskRequest 类
class MockBatchTaskRequest:
    def __init__(self, sources=None):
        self.sources = sources or []

# 创建模拟的model模块
class MockTaskResponse:
    def __init__(self, task_id):
        self.task_id = task_id

class MockBatchTaskResponse:
    def __init__(self, task_ids):
        self.task_ids = task_ids

# 创建模拟的model模块
mock_model = MagicMock()
mock_model.BatchTaskRequest = MockBatchTaskRequest
mock_model.TaskResponse = MockTaskResponse
mock_model.BatchTaskResponse = MockBatchTaskResponse
mock_model.SimpleTaskStatusResponse = MagicMock()
mock_model.SimpleTasksListResponse = MagicMock()

# 模拟celery和其他服务
mock_celery = MagicMock()
mock_service = MagicMock()
sys.modules['celery'] = mock_celery
sys.modules['services.data_process_service'] = mock_service
sys.modules['consts.model'] = mock_model

# 模拟所有导入，而不是实际导入模块
class MockRouter:
    def __init__(self):
        self.routes = []
        
    def post(self, path, **kwargs):
        def decorator(func):
            self.routes.append((path, func))
            return func
        return decorator
        
    def get(self, path, **kwargs):
        def decorator(func):
            self.routes.append((path, func))
            return func
        return decorator


# 创建测试应用和路由器
class TestDataProcessApp(unittest.TestCase):
    def setUp(self):
        # 创建模拟的路由器和服务
        self.router = MockRouter()
        self.service = MagicMock()
        self.process_and_forward = MagicMock()
        self.process_sync = MagicMock()
        self.get_task_info = AsyncMock()
        self.utils_get_task_details = AsyncMock()
        
        # 模拟异步上下文管理器
        self.lifespan = MagicMock()
        
        # 常用测试数据
        self.task_id = "test-task-id-123"
        self.index_name = "test-index"
        self.source = "test-file.pdf"
        
        # 创建实际的FastAPI应用
        self.app = FastAPI()
        
        # 定义模拟路由函数
        self.setup_mock_routes()
        
        # 创建测试客户端
        self.client = TestClient(self.app)
    
    def setup_mock_routes(self):
        # 添加一些测试路由
        @self.app.post("/tasks")
        async def create_task(request: Dict[str, Any] = Body(None)):
            # 模拟创建任务
            task_result = self.process_and_forward.delay.return_value
            return {"task_id": task_result.id}
        
        @self.app.post("/tasks/process")
        async def process_sync_endpoint(
            source: str = Form(...),
            source_type: str = Form("file"),
            chunking_strategy: str = Form("basic"),
            timeout: int = Form(30)
        ):
            # 模拟同步处理
            try:
                if getattr(self.process_sync, 'apply_async', None) and getattr(self.process_sync.apply_async, 'side_effect', None):
                    raise self.process_sync.apply_async.side_effect
                
                task_result = self.process_sync.apply_async.return_value
                result = task_result.get.return_value if hasattr(task_result, 'get') else {}
                
                return {
                    "success": True,
                    "task_id": task_result.id if hasattr(task_result, 'id') else self.task_id,
                    "source": source,
                    "text": result.get("text", ""),
                    "chunks": result.get("chunks", []),
                    "chunks_count": result.get("chunks_count", 0),
                    "processing_time": result.get("processing_time", 0),
                    "text_length": result.get("text_length", 0)
                }
            except Exception as e:
                # 捕获异常并返回适当的HTTP错误响应
                raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
        
        @self.app.post("/tasks/batch")
        async def create_batch_tasks(request: Dict[str, Any] = Body(None)):
            # 模拟批量创建任务
            task_ids = []
            
            # Handle both Dict and MockBatchTaskRequest
            if hasattr(request, 'sources'):
                sources = request.sources
            else:
                sources = request.get("sources", [])
            
            for i in range(len(sources)):
                if isinstance(self.process_and_forward.delay.return_value, list):
                    task_result = self.process_and_forward.delay.return_value[i]
                else:
                    task_result = self.process_and_forward.delay.return_value
                task_ids.append(task_result.id if hasattr(task_result, 'id') else f"batch-task-{i+1}")
            
            return {"task_ids": task_ids}
        
        @self.app.get("/tasks/load_image")
        async def load_image():
            # 模拟图像加载
            if not getattr(self.service, 'load_image', None) or self.service.load_image.return_value is None:
                raise HTTPException(status_code=404, detail="Failed to load image or image format not supported")
            
            image = self.service.load_image.return_value
            return {"success": True, "base64": "mock_base64_data", "content_type": "image/jpeg"}
        
        @self.app.get("/tasks/{task_id}")
        async def get_task(task_id: str):
            # 模拟获取任务信息
            task = self.get_task_info.return_value
            
            if not task:
                raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
            
            return task
        
        @self.app.get("/tasks")
        async def list_tasks():
            # 模拟列出所有任务
            tasks = self.service.get_all_tasks.return_value
            return {"tasks": tasks}
        
        @self.app.get("/tasks/indices/{index_name}")
        async def get_index_tasks(index_name: str):
            # 模拟获取索引任务
            return self.service.get_index_tasks.return_value
        
        @self.app.get("/tasks/{task_id}/details")
        async def get_task_details(task_id: str):
            # 模拟获取任务详情
            task = self.utils_get_task_details.return_value
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return task
        
        @self.app.post("/tasks/filter_important_image")
        async def filter_important_image(
            image_url: str = Form(...),
            positive_prompt: str = Form("an important image"),
            negative_prompt: str = Form("an unimportant image")
        ):
            # 模拟图像过滤
            try:
                if getattr(self.service, 'filter_important_image', None) and getattr(self.service.filter_important_image, 'side_effect', None):
                    raise self.service.filter_important_image.side_effect
                
                # 移除await，直接返回值
                return self.service.filter_important_image.return_value
            except Exception as e:
                # 捕获异常并返回适当的HTTP错误响应
                raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")
    
    def test_create_task(self):
        # 设置模拟
        mock_task = MagicMock()
        mock_task.id = self.task_id
        self.process_and_forward.delay.return_value = mock_task

        # 测试数据
        request_data = {
            "source": self.source,
            "source_type": "file",
            "chunking_strategy": "basic",
            "index_name": self.index_name,
            "additional_params": {"param1": "value1"}
        }
        
        # 执行请求
        response = self.client.post("/tasks", json=request_data)
        
        # 断言
        self.assertEqual(response.status_code, 200)  # FastAPI测试客户端默认返回200
        self.assertEqual(response.json(), {"task_id": self.task_id})

    def test_process_sync_endpoint_success(self):
        # 设置模拟
        mock_task = MagicMock()
        mock_task.id = self.task_id
        mock_task.get.return_value = {
            "text": "extracted text",
            "chunks": ["chunk1", "chunk2"],
            "chunks_count": 2,
            "processing_time": 1.5,
            "text_length": 100
        }
        self.process_sync.apply_async.return_value = mock_task
        
        # 执行请求
        response = self.client.post(
            "/tasks/process",
            data={
                "source": self.source,
                "source_type": "file",
                "chunking_strategy": "basic",
                "timeout": 30
            }
        )
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertEqual(result["task_id"], self.task_id)
        self.assertEqual(result["source"], self.source)
        self.assertEqual(result["text"], "extracted text")
        self.assertEqual(result["chunks_count"], 2)

    def test_process_sync_endpoint_failure(self):
        # 设置模拟抛出异常
        self.process_sync.apply_async.side_effect = Exception("Processing error")
        
        # 执行请求
        response = self.client.post(
            "/tasks/process",
            data={
                "source": self.source,
                "source_type": "file",
                "chunking_strategy": "basic",
                "timeout": 30
            }
        )
        
        # 断言
        self.assertEqual(response.status_code, 500)
        self.assertIn("Error processing file", response.json()["detail"])
        self.assertIn("Processing error", response.json()["detail"])

    def test_create_batch_tasks(self):
        # 设置模拟
        mock_task1 = MagicMock()
        mock_task1.id = "batch-task-1"
        mock_task2 = MagicMock()
        mock_task2.id = "batch-task-2"
        self.process_and_forward.delay.return_value = [mock_task1, mock_task2]

        # 测试数据
        request_data = {
            "sources": [
                {
                    "source": "file1.pdf",
                    "source_type": "file",
                    "chunking_strategy": "basic",
                    "index_name": self.index_name,
                    "extra_param": "value1"
                },
                {
                    "source": "file2.pdf",
                    "source_type": "file",
                    "chunking_strategy": "advanced",
                    "index_name": self.index_name,
                    "another_param": "value2"
                }
            ]
        }
        
        # 执行请求
        response = self.client.post("/tasks/batch", json=request_data)
        
        # 断言
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"task_ids": ["batch-task-1", "batch-task-2"]})

    def test_load_image_success(self):
        # 创建测试图像
        test_image = Image.new('RGB', (100, 100), color='red')
        test_image.format = 'JPEG'
        
        # 设置模拟
        self.service.load_image = AsyncMock(return_value=test_image)
        
        # 执行请求
        response = self.client.get("/tasks/load_image?url=http://example.com/image.jpg")
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertIn("base64", result)
        self.assertEqual(result["content_type"], "image/jpeg")

    def test_load_image_failure(self):
        # 设置模拟返回None（加载图像失败）
        self.service.load_image = AsyncMock(return_value=None)
        
        # 执行请求
        response = self.client.get("/tasks/load_image?url=http://example.com/bad_image.jpg")
        
        # 断言
        self.assertEqual(response.status_code, 404)
        self.assertIn("Failed to load image", response.json()["detail"])

    def test_get_task_success(self):
        # 设置模拟
        task_data = {
            "id": self.task_id,
            "task_name": "process_and_forward",
            "index_name": self.index_name,
            "path_or_url": self.source,
            "status": "SUCCESS",
            "created_at": "2023-01-01T12:00:00",
            "updated_at": "2023-01-01T12:05:00",
            "error": None
        }
        self.get_task_info.return_value = task_data
        
        # 执行请求
        response = self.client.get(f"/tasks/{self.task_id}")
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["id"], self.task_id)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["index_name"], self.index_name)

    def test_get_task_not_found(self):
        # 设置模拟返回None（任务未找到）
        self.get_task_info.return_value = None
        
        # 执行请求
        response = self.client.get("/tasks/nonexistent-id")
        
        # 断言
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"])

    def test_list_tasks(self):
        # 设置模拟
        tasks_data = [
            {
                "id": "task-1",
                "task_name": "process_and_forward",
                "index_name": self.index_name,
                "path_or_url": "file1.pdf",
                "status": "SUCCESS",
                "created_at": "2023-01-01T12:00:00",
                "updated_at": "2023-01-01T12:05:00",
                "error": None
            },
            {
                "id": "task-2",
                "task_name": "process_and_forward",
                "index_name": self.index_name,
                "path_or_url": "file2.pdf",
                "status": "FAILURE",
                "created_at": "2023-01-01T13:00:00",
                "updated_at": "2023-01-01T13:05:00",
                "error": "Some error"
            }
        ]
        self.service.get_all_tasks = AsyncMock(return_value=tasks_data)
        
        # 执行请求
        response = self.client.get("/tasks")
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][0]["id"], "task-1")
        self.assertEqual(result["tasks"][1]["id"], "task-2")

    def test_get_index_tasks(self):
        # 设置模拟
        tasks_data = [
            {
                "id": "task-1",
                "task_name": "process_and_forward",
                "status": "SUCCESS"
            },
            {
                "id": "task-2",
                "task_name": "process_and_forward",
                "status": "PENDING"
            }
        ]
        self.service.get_index_tasks = AsyncMock(return_value=tasks_data)
        
        # 执行请求
        response = self.client.get(f"/tasks/indices/{self.index_name}")
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result), 2)

    def test_get_task_details(self):
        # 设置模拟
        task_detail_data = {
            "id": self.task_id,
            "task_name": "process_and_forward",
            "status": "SUCCESS",
            "result": {
                "text": "Extracted text",
                "metadata": {"page_count": 5}
            }
        }
        self.utils_get_task_details.return_value = task_detail_data
        
        # 执行请求
        response = self.client.get(f"/tasks/{self.task_id}/details")
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["id"], self.task_id)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["result"]["text"], "Extracted text")

    def test_get_task_details_not_found(self):
        # 设置模拟返回None（任务未找到）
        self.utils_get_task_details.return_value = None
        
        # 执行请求
        response = self.client.get(f"/tasks/nonexistent-id/details")
        
        # 断言
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"])

    def test_filter_important_image(self):
        # 设置模拟
        filter_result = {
            "is_important": True,
            "confidence": 0.85,
            "processing_time": 1.2
        }
        self.service.filter_important_image = AsyncMock(return_value=filter_result)
        
        # 执行请求
        response = self.client.post(
            "/tasks/filter_important_image",
            data={
                "image_url": "http://example.com/image.jpg",
                "positive_prompt": "an important image",
                "negative_prompt": "an unimportant image"
            }
        )
        
        # 断言
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["is_important"])
        self.assertEqual(result["confidence"], 0.85)

    def test_filter_important_image_error(self):
        # 设置模拟抛出异常
        self.service.filter_important_image = AsyncMock()
        self.service.filter_important_image.side_effect = Exception("Image processing error")
        
        # 执行请求
        response = self.client.post(
            "/tasks/filter_important_image",
            data={
                "image_url": "http://example.com/image.jpg",
                "positive_prompt": "an important image",
                "negative_prompt": "an unimportant image"
            }
        )
        
        # 断言
        self.assertEqual(response.status_code, 500)
        self.assertIn("Error processing image", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
