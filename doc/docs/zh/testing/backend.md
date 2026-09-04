# 后端测试

本指南涵盖了 Nexent 中使用的全面后端测试框架，包括 API 测试、服务层测试和工具函数测试。

## 测试结构

后端测试按以下结构组织：

```
test/backend/
├── adapters/              # 适配器测试（如 jiuwen_sdk_adapter）
├── agents/                # 智能体核心测试
│   ├── test_agent_run_manager.py
│   ├── test_create_agent_info.py
│   ├── test_nl2agent_agent.py
│   └── test_preprocess_manager.py
├── app/                   # API 端点测试
│   ├── test_agent_app.py
│   ├── test_conversation_management_app.py
│   ├── test_data_process_app.py
│   ├── test_file_management_app.py
│   ├── test_image_app.py
│   ├── test_knowledge_summary_app.py
│   ├── test_model_managment_app.py
│   ├── test_northbound_app.py
│   ├── test_prompt_app.py
│   ├── test_remote_mcp_app.py
│   └── ...
├── apps/                  # 补充 API 测试
│   ├── test_memory_dreaming_app.py
│   └── test_memory_record_app.py
├── consts/                # 常量与模型测试
├── data_process/          # 数据处理测试（Ray、Celery 任务）
├── database/              # 数据库访问层测试
├── middleware/            # 中间件测试
├── permissions/           # 权限（RBAC/DAC）测试
├── services/              # 服务层测试
│   ├── test_agent_service.py
│   ├── test_agent_version_service.py
│   ├── test_conversation_management_service.py
│   ├── test_data_process_service.py
│   ├── test_file_management_service.py
│   ├── test_image_service.py
│   ├── test_knowledge_summary_service.py
│   ├── test_memory_config_service.py
│   ├── test_model_management_service.py
│   ├── test_prompt_service.py
│   ├── test_remote_mcp_service.py
│   └── ...
├── utils/                 # 工具函数测试
│   ├── test_langchain_utils.py
│   ├── test_llm_utils.py
│   └── test_prompt_template_utils.py
└── test_*.py              # 根级集成类测试（LLM 集成、运行时服务等）
```

## 运行后端测试

### 完整的后端测试套件

```bash
# 激活后端虚拟环境后，从项目根目录运行全部测试（含覆盖率）
source backend/.venv/bin/activate
python test/run_all_test.py

# 仅运行后端测试
NEXENT_PYTEST_TARGETS=test/backend python test/run_all_test.py
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
from apps.agent_app import agent_config_router, agent_runtime_router

# 创建测试应用
app = FastAPI()
app.include_router(agent_config_router)
app.include_router(agent_runtime_router)
client = TestClient(app)
```

### API 测试示例

以下示例改编自真实的 `test/backend/app/test_agent_app.py`。补丁必须打在**引用处所在的模块**上（如 `apps.agent_app.get_current_user_id`），而不是函数原始定义处（`backend.utils.auth_utils.get_current_user_id`）；被 `await` 的异步服务函数需用 `AsyncMock` 模拟：

```python
from unittest.mock import AsyncMock


def test_search_agent_info_api_success(mocker):
    """测试成功的智能体信息查询"""
    # 设置 - 模拟身份认证与服务层返回
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}

    # 执行
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers={"Authorization": "Bearer test_token"}
    )

    # 断言
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with("Bearer test_token")
    # 未传 tenant_id 时回退到认证租户 ID，version_no 默认为 0
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 0, "user_id")
    assert response.json()["agent_id"] == 123
    assert response.json()["name"] == "Test Agent"
```

## 服务层测试

服务层测试专注于业务逻辑和数据处理，无需 HTTP 开销。

### 服务测试模式

以下示例改编自真实的 `test/backend/services/test_agent_service.py`。`get_agent_id_by_name` 内部调用从 `backend.database.agent_db` 导入到服务模块命名空间的 `search_agent_id_by_agent_name`，因此补丁目标为 `backend.services.agent_service.search_agent_id_by_agent_name`（引用处所在模块）：

```python
import pytest
from unittest.mock import patch

from services.agent_service import get_agent_id_by_name


@pytest.mark.asyncio
@patch("backend.services.agent_service.search_agent_id_by_agent_name")
async def test_get_agent_id_by_name(mock_search):
    """测试通过名称与租户解析智能体 ID"""
    # 测试成功路径
    mock_search.return_value = 1
    result = await get_agent_id_by_name("test_agent", "test_tenant")
    assert result == 1
    mock_search.assert_called_once_with("test_agent", "test_tenant")

    # 测试未找到路径
    mock_search.side_effect = Exception("Not found")
    with pytest.raises(Exception, match="agent not found"):
        await get_agent_id_by_name("test_agent", "test_tenant")
```

### 模拟数据库操作

`backend/database/` 层的函数通过 `get_db_session()` 上下文管理器获取会话。测试时可将该函数替换为模拟会话以隔离真实数据库（以下示例基于真实的 `search_agent_id_by_agent_name`）：

```python
import pytest
from unittest.mock import MagicMock

from database.agent_db import search_agent_id_by_agent_name


def test_search_agent_id_by_agent_name(mocker):
    """测试按名称与租户查询智能体 ID"""
    # 设置 - 模拟会话上下文及 query().filter().first() 查询链
    session = MagicMock()
    session.__enter__.return_value = session
    mocker.patch("database.agent_db.get_db_session", return_value=session)
    mock_agent = MagicMock()
    mock_agent.agent_id = 100
    session.query.return_value = session
    session.filter.return_value = session
    session.first.return_value = mock_agent

    # 执行
    result = search_agent_id_by_agent_name("Test Agent", "tenant456")

    # 断言
    assert result == 100
    session.query.assert_called_once()


def test_search_agent_id_by_agent_name_not_found(mocker):
    """测试未找到时抛出 ValueError"""
    # 设置 - 查询结果为空
    session = MagicMock()
    session.__enter__.return_value = session
    mocker.patch("database.agent_db.get_db_session", return_value=session)
    session.query.return_value = session
    session.filter.return_value = session
    session.first.return_value = None

    # 执行 & 断言
    with pytest.raises(ValueError, match="agent not found"):
        search_agent_id_by_agent_name("Missing Agent", "tenant456")
```

## 工具函数测试

工具函数在隔离环境中测试，使用模拟的依赖项。

### 工具测试示例

```python
from unittest.mock import MagicMock, patch

from utils.langchain_utils import discover_langchain_modules


def test_discover_langchain_modules():
    # 设置 - 模拟模块扫描，避免加载真实 langchain 依赖
    with patch("utils.langchain_utils._is_langchain_tool", return_value=True) as mock_check:
        # 执行
        tools = discover_langchain_modules("some_package")

        # 断言
        mock_check.assert_called()
        assert isinstance(tools, list)
```

## 测试异步代码

后端测试处理同步和异步代码。`test/pytest.ini` 配置了 `asyncio_mode = auto`，异步测试函数会被自动识别执行（也支持显式标注 `@pytest.mark.asyncio`）：

### 异步测试模式

被 `await` 的异步函数需要用 `AsyncMock` 模拟——`AsyncMock` 的返回值就是 `await` 表达式的结果（示例用法与真实 `test/backend/app/test_agent_app.py` 中的 `new_callable=AsyncMock` 一致）：

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_async_operation():
    """演示 AsyncMock 模拟被 await 的异步函数"""
    # 设置 - AsyncMock 的返回值即 await 表达式的结果
    mock_async_query = AsyncMock(return_value={"result": "success"})

    # 执行
    result = await mock_async_query()

    # 断言
    assert result["result"] == "success"
    mock_async_query.assert_awaited_once()
```

## 错误处理测试

全面测试错误处理。`search_agent_info_api` 捕获所有异常并映射为 HTTP 500，以下示例验证服务层异常被正确转换为错误响应：

```python
from unittest.mock import AsyncMock


def test_search_agent_info_api_error(mocker):
    """测试 API 错误响应（服务层异常 → HTTP 500）"""
    # 设置 - 模拟身份认证与异常的服务层返回
    mocker.patch("apps.agent_app.get_current_user_id",
                 return_value=("user_id", "auth_tenant_id"))
    mocker.patch(
        "apps.agent_app.get_agent_info_impl",
        new_callable=AsyncMock,
        side_effect=Exception("Database error"),
    )

    # 执行
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers={"Authorization": "Bearer test_token"}
    )

    # 断言 - search_agent_info_api 捕获异常并返回 500
    assert response.status_code == 500
    assert response.json() == {"detail": "Agent search info error."}
```

## 身份验证和授权测试

彻底测试安全相关功能：

### 认证失败 → 401

内部北向端点（`agent_runtime_router`，前缀同为 `/agent`）通过 `verify_internal_runtime_jwt` 校验内部 JWT，失败时映射为 401。示例改编自真实的 `test/backend/app/test_agent_app.py`：

```python
from consts.exceptions import UnauthorizedError


def test_authentication_required(mocker):
    """测试需要内部 JWT 的端点返回 401"""
    # 设置 - 模拟内部运行时 JWT 校验失败
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        side_effect=UnauthorizedError("Invalid internal runtime token"),
    )

    # 执行 - 访问北向停止端点
    response = client.post(
        "/agent/internal/northbound/stop/123",
        headers={"Authorization": "Bearer invalid"}
    )

    # 断言
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid internal runtime token"
```

### 租户隔离

`/agent/search_info` 支持显式 `tenant_id` 查询参数。示例改编自真实的 `test_search_agent_info_api_with_explicit_tenant_id`，验证显式租户会覆盖认证租户并传给服务层：

```python
from unittest.mock import AsyncMock


def test_tenant_isolation(mocker):
    """测试显式传入的 tenant_id 覆盖认证租户"""
    # 设置 - 认证租户与显式租户不同
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 456, "name": "Test Agent with Explicit Tenant",
    }

    # 执行 - 显式指定 tenant_id 查询参数
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 456},
        params={"tenant_id": "explicit_tenant_789"},
        headers={"Authorization": "Bearer test_token"}
    )

    # 断言 - 服务层收到的是显式租户而非认证租户
    assert response.status_code == 200
    mock_get_agent_info.assert_called_once_with(
        456, "explicit_tenant_789", 0, "user_id")
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
import pytest


@pytest.fixture
def test_agent():
    """设置测试数据"""
    return {
        "id": 1,
        "name": "Test Agent",
        "description": "A test agent",
        "system_prompt": "You are a test agent"
    }


@pytest.fixture
def test_user():
    """模拟用户与租户信息"""
    return ("user123", "tenant456")

def test_with_fixtures(test_agent, test_user):
    """在测试函数中直接注入 fixtures"""
    assert test_agent["id"] == 1
    assert test_user == ("user123", "tenant456")
```

## 性能测试

后端测试包括性能考虑：

```python
def test_get_agent_by_name_response_time(mocker):
    """测试 API 响应时间在可接受的时间限制内"""
    import time

    # 设置 - 模拟认证与按名称查询逻辑，避免真实数据库调用
    mocker.patch("apps.agent_app.get_current_user_id",
                 return_value=("user_id", "auth_tenant_id"))
    mocker.patch("apps.agent_app.get_agent_by_name_impl",
                 return_value={"agent_id": 1, "latest_version_no": 0})

    start_time = time.time()
    response = client.get(
        "/agent/by-name/TestAgent",
        headers={"Authorization": "Bearer test_token"}
    )
    end_time = time.time()

    # 断言响应时间小于 100ms
    assert end_time - start_time < 0.1
    assert response.status_code == 200
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