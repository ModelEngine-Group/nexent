# 后端测试

本指南涵盖了 Nexent 中使用的全面后端测试框架，包括 API 测试、服务层测试和工具函数测试。

## 测试结构

后端测试按以下结构组织：

```
test/backend/
├── app/                    # API 端点测试
│   ├── test_agent_app.py
│   ├── test_base_app.py
│   ├── test_config_sync_app.py
│   ├── test_conversation_management_app.py
│   ├── test_data_process_app.py
│   ├── test_elasticsearch_app.py
│   ├── test_file_management_app.py
│   ├── test_image_app.py
│   ├── test_knowledge_app.py
│   ├── test_knowledge_summary_app.py
│   ├── test_me_model_managment_app.py
│   ├── test_model_managment_app.py
│   ├── test_prompt_app.py
│   └── test_remote_mcp_app.py
├── services/              # 服务层测试
│   ├── test_agent_service.py
│   ├── test_conversation_management_service.py
│   ├── test_data_process_service.py
│   ├── test_elasticsearch_service.py
│   ├── test_file_management_service.py
│   ├── test_image_service.py
│   ├── test_knowledge_service.py
│   ├── test_knowledge_summary_service.py
│   ├── test_model_management_service.py
│   ├── test_prompt_service.py
│   └── test_remote_mcp_service.py
├── utils/                 # 工具函数测试
│   ├── test_langchain_utils.py
│   └── test_prompt_template_utils.py
└── run_all_test.py       # 后端测试运行器
```

## 运行后端测试

### 完整的后端测试套件

```bash
# 从项目根目录
python test/backend/run_all_test.py

# 从 test/backend 目录
cd test/backend
python run_all_test.py
```

### 单个测试类别

```bash
# 运行所有 API 测试
python -m pytest test/backend/app/ -v

# 运行所有服务测试
python -m pytest test/backend/services/ -v

# 运行所有工具测试
python -m pytest test/backend/utils/ -v
```

### 特定测试文件

```bash
# 运行特定 API 测试
python -m pytest test/backend/app/test_agent_app.py -v

# 运行特定服务测试
python -m pytest test/backend/services/test_agent_service.py -v

# 运行特定工具测试
python -m pytest test/backend/utils/test_langchain_utils.py -v
```

## API 测试

API 测试使用 FastAPI 的 TestClient 来模拟 HTTP 请求，而无需运行实际服务器。

### 测试设置模式

```python
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# 动态确定后端路径
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# 在导入模块之前设置依赖项补丁
patches = [
    patch('botocore.client.BaseClient._make_api_call', return_value={}),
    patch('backend.database.client.MinioClient', MagicMock()),
    patch('backend.database.client.db_client', MagicMock()),
    patch('backend.utils.auth_utils.get_current_user_id', 
          MagicMock(return_value=('test_user', 'test_tenant'))),
    patch('httpx.AsyncClient', MagicMock())
]

# 启动所有补丁
for p in patches:
    p.start()

# 应用补丁后导入模块
from backend.apps.agent_app import router

# 创建测试应用
app = FastAPI()
app.include_router(router)
client = TestClient(app)
```

### API 测试示例

```python
class TestAgentApp(unittest.TestCase):
    
    def setUp(self):
        # 设置测试客户端和通用模拟
        pass
    
    def test_create_agent_success(self):
        """测试成功的智能体创建"""
        # 设置
        agent_data = {
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent"
        }
        
        # 执行
        response = client.post("/agents", json=agent_data)
        
        # 断言
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json())
        self.assertEqual(response.json()["name"], "Test Agent")
    
    def test_create_agent_invalid_data(self):
        """测试使用无效数据的智能体创建"""
        # 设置
        invalid_data = {"name": ""}  # 缺少必需字段
        
        # 执行
        response = client.post("/agents", json=invalid_data)
        
        # 断言
        self.assertEqual(response.status_code, 422)  # 验证错误
```

## 服务层测试

服务层测试专注于业务逻辑和数据处理，无需 HTTP 开销。

### 服务测试模式

```python
class TestAgentService(unittest.TestCase):
    
    @patch("backend.database.agent_db.save_agent")
    @patch("backend.utils.auth_utils.get_current_user_id")
    async def test_create_agent_success(self, mock_get_user, mock_save_agent):
        # 设置
        mock_get_user.return_value = ("user123", "tenant456")
        mock_save_agent.return_value = {"id": 1, "name": "Test Agent"}
        
        # 执行
        result = await create_agent(
            name="Test Agent",
            description="A test agent",
            system_prompt="You are a test agent"
        )
        
        # 断言
        mock_save_agent.assert_called_once()
        self.assertEqual(result["name"], "Test Agent")
        self.assertIn("id", result)
```

### 模拟数据库操作

```python
@patch("backend.database.agent_db.query_agent_by_id")
@patch("backend.database.agent_db.update_agent")
async def test_update_agent_success(self, mock_update, mock_query):
    # 设置
    mock_query.return_value = {"id": 1, "name": "Old Name"}
    mock_update.return_value = {"id": 1, "name": "New Name"}
    
    # 执行
    result = await update_agent(agent_id=1, name="New Name")
    
    # 断言
    mock_update.assert_called_once_with(agent_id=1, name="New Name")
    self.assertEqual(result["name"], "New Name")
```

## 工具函数测试

工具函数在隔离环境中测试，使用模拟的依赖项。

### 工具测试示例

```python
class TestLangchainUtils(unittest.TestCase):
    
    @patch("langchain.llms.openai.OpenAI")
    def test_create_llm_instance(self, mock_openai):
        # 设置
        mock_openai.return_value = MagicMock()
        
        # 执行
        llm = create_llm_instance(model_name="gpt-3.5-turbo")
        
        # 断言
        mock_openai.assert_called_once()
        self.assertIsNotNone(llm)
```

## 测试异步代码

后端测试处理同步和异步代码：

### 异步测试模式

```python
class TestAsyncService(unittest.TestCase):
    
    @patch("backend.database.agent_db.async_query")
    async def test_async_operation(self, mock_async_query):
        # 设置
        mock_async_query.return_value = {"result": "success"}
        
        # 执行
        result = await async_operation()
        
        # 断言
        self.assertEqual(result["result"], "success")
        mock_async_query.assert_called_once()
```

## 错误处理测试

全面测试错误处理：

```python
def test_api_error_handling(self):
    """测试 API 错误响应"""
    # 设置 - 模拟服务抛出异常
    with patch('backend.services.agent_service.create_agent') as mock_service:
        mock_service.side_effect = Exception("Database error")
        
        # 执行
        response = client.post("/agents", json={"name": "Test"})
        
        # 断言
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())
```

## 身份验证和授权测试

彻底测试安全相关功能：

```python
def test_authentication_required(self):
    """测试端点需要身份验证"""
    # 执行 - 没有身份验证头
    response = client.get("/agents")
    
    # 断言
    self.assertEqual(response.status_code, 401)

def test_tenant_isolation(self):
    """测试用户只能访问其租户的数据"""
    # 设置 - 模拟身份验证返回不同租户
    with patch('backend.utils.auth_utils.get_current_user_id') as mock_auth:
        mock_auth.return_value = ("user1", "tenant1")
        
        # 执行
        response = client.get("/agents")
        
        # 断言 - 验证应用了租户过滤
        # 这将检查服务层是否按租户过滤
```

## 覆盖率分析

后端测试生成详细的覆盖率报告：

### 覆盖率命令

```bash
# 生成覆盖率报告
python -m pytest test/backend/ --cov=backend --cov-report=html --cov-report=xml

# 在终端中查看覆盖率
python -m pytest test/backend/ --cov=backend --cov-report=term-missing
```

### 覆盖率目标

- **API 端点**：90%+ 覆盖率
- **服务层**：85%+ 覆盖率
- **工具函数**：80%+ 覆盖率
- **错误处理**：关键路径 100% 覆盖率

## 测试数据管理

### 固定装置和测试数据

```python
class TestWithFixtures(unittest.TestCase):
    
    def setUp(self):
        """设置测试数据和模拟"""
        self.test_agent = {
            "id": 1,
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent"
        }
        
        self.test_user = ("user123", "tenant456")
    
    def tearDown(self):
        """测试后清理"""
        # 如果需要，重置任何全局状态
        pass
```

## 性能测试

后端测试包括性能考虑：

```python
def test_api_response_time(self):
    """测试 API 响应时间在可接受的时间限制内"""
    import time
    
    start_time = time.time()
    response = client.get("/agents")
    end_time = time.time()
    
    # 断言响应时间小于 100ms
    self.assertLess(end_time - start_time, 0.1)
    self.assertEqual(response.status_code, 200)
```

## 后端测试最佳实践

1. **模拟外部依赖**：始终模拟数据库、外部 API 和服务
2. **测试成功和失败**：覆盖所有可能的代码路径
3. **使用描述性测试名称**：清楚说明每个测试验证的内容
4. **保持测试独立**：每个测试都应该能够独立运行
5. **测试边缘情况**：包括边界条件和错误场景
6. **维护测试数据**：使用一致、真实的测试数据
7. **记录复杂测试**：为复杂的测试场景添加注释
8. **定期覆盖率审查**：监控并随时间改进覆盖率

这个全面的后端测试框架确保所有后端功能在部署前都经过彻底验证，保持高代码质量和可靠性。 