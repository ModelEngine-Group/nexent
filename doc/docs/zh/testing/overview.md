# 测试概览

Nexent 提供了一个全面的测试框架，确保所有组件的代码质量和可靠性。本指南涵盖了项目中使用的测试策略、工具和最佳实践。

## 测试理念

我们的测试方法建立在四个核心原则之上：

1. **隔离单元**：模拟所有外部依赖
2. **控制环境**：设置精确的测试条件
3. **测试接口**：专注于输入和输出
4. **验证行为**：检查结果和交互

这确保了测试的可靠性、快速性，并且不会影响真实的系统或数据。

## 测试框架

项目使用以下测试工具组合：

- **pytest**：核心测试框架，用于测试发现和执行（pytest only，不使用 unittest 组织新测试）
- **pytest-asyncio**：异步测试支持（`test/pytest.ini` 已配置 `asyncio_mode = auto`，异步测试函数会被自动识别，也可显式使用 `@pytest.mark.asyncio`）
- **pytest-mock / unittest.mock**：用于模拟依赖项和隔离组件（在导入处使用全限定路径打补丁）
- **TestClient** from FastAPI：用于测试 API 端点而无需运行实际服务器
- **pytest-cov + coverage**：用于代码覆盖率分析和报告

## 测试结构

```
test/
├── backend/                # 后端测试（apps、services、database、agents、utils 等）
├── sdk/                    # SDK 测试
├── ext_components/         # 扩展组件测试（如 aidp）
├── common/                 # 公共测试工具与 mock
├── stress/                 # 压力测试脚本
├── conftest.py             # 全局 fixtures
├── pytest.ini              # pytest 配置
└── run_all_test.py         # 主测试运行器
```

## 主要特性

- 🔍 **自动发现测试文件** - 自动查找所有 `test_*.py` 文件（覆盖 `test/backend`、`test/sdk`、`test/ext_components`）
- 📊 **覆盖率报告** - 生成控制台、HTML 和 XML 格式的覆盖率报告
- 🧵 **并行执行** - 通过 `NEXENT_PYTEST_WORKERS` 控制并发工作进程数（默认 auto）
- ⏱️ **超时保护** - 通过 `NEXENT_PYTEST_FILE_TIMEOUT` 限制单文件执行时间（默认 600 秒）
- ✅ **详细输出** - 显示每个测试文件的运行状态和结果
- 🚫 **完全隔离** - 从不接触真实的外部服务
- ⚡ **快速执行** - 无网络延迟或外部服务处理时间

## 运行测试

### 快速开始

```bash
# 激活后端虚拟环境后，在项目根运行所有测试并生成覆盖率报告
source backend/.venv/bin/activate
python test/run_all_test.py
```

### 后端测试

```bash
# 仅运行后端测试（通过目标路径环境变量）
NEXENT_PYTEST_TARGETS=test/backend python test/run_all_test.py
```

### 单个测试文件

```bash
# 运行特定测试文件
python -m pytest test/backend/services/test_agent_service.py -v
```

## 输出文件

测试完成后，您将在 `test/` 目录下找到：

- `test/coverage_html/` - 详细的 HTML 格式覆盖率报告
- `test/coverage.xml` - XML 格式覆盖率报告（用于 CI/CD）
- `test/.coverage` - 覆盖率数据文件
- 包含详细测试结果和覆盖率统计的控制台输出

## 测试策略

### 1. 依赖隔离

在导入之前模拟外部模块以避免真实连接：

- 模拟数据库连接
- 模拟 ElasticSearch 和其他外部服务
- 测试期间不执行实际的数据库操作
- 模拟 HTTP 客户端以防止网络调用

### 2. 基于模拟的测试

- 使用 FastAPI 的 TestClient 模拟 HTTP 请求
- 使用模拟对象拦截外部服务调用
- 不发生实际的网络连接或端口绑定
- 模拟身份验证函数以返回可预测的测试值

### 3. 测试组织

- 测试统一使用 pytest 组织（函数或类风格），异步测试使用 `@pytest.mark.asyncio` 或依赖 `asyncio_mode = auto`
- 每个 API 端点或函数都有多个测试用例（成功、失败、异常场景）
- 应用全面的补丁来隔离被测试的代码
- 测试遵循清晰的设置-执行-断言模式

### 4. API 测试

- 测试 API 端点的正确响应代码、负载结构和错误处理
- 涵盖同步和异步端点
- 通过专门的测试用例测试流式响应
- 彻底测试身份验证和授权

## 模块补丁技术

测试套件中使用的关键技术是在导入之前修补模块。这可以防止任何真实的外部服务连接。

### 示例：导入前补丁

```python
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

# 现在在应用所有补丁后导入模块
from apps.file_management_app import router
```

### 这种方法的优势

1. **完全隔离**：从不接触真实的外部服务
2. **无副作用**：测试无法修改生产数据库或服务
3. **更快的测试**：无网络延迟或外部服务处理时间
4. **可预测的结果**：测试使用受控的模拟数据以获得一致的结果
5. **无端口绑定**：FastAPI 应用程序从不绑定到真实的网络端口

## 测试示例

以下是测试结构化的详细示例（pytest 风格，mock 使用函数被引用处的模块全限定路径，确保对已导入的引用生效；底层依赖需在导入前打补丁，见上文"模块补丁技术"）：

```python
from unittest.mock import MagicMock, patch

import pytest

from apps.tool_config_app import list_tools_api


@pytest.mark.asyncio
@patch("apps.tool_config_app.get_current_user_id")
@patch("apps.tool_config_app.list_all_tools")
async def test_list_tools_api_success(mock_list_all_tools, mock_get_current_user_id):
    # 设置
    mock_get_current_user_id.return_value = ("user123", "tenant456")
    expected_tools = [{"id": 1, "name": "Tool1"}, {"id": 2, "name": "Tool2"}]
    mock_list_all_tools.return_value = expected_tools

    # 执行
    result = await list_tools_api(authorization="Bearer fake_token")

    # 断言
    mock_get_current_user_id.assert_called_once_with("Bearer fake_token")
    mock_list_all_tools.assert_called_once_with(tenant_id="tenant456", labels=None)
    assert result == expected_tools
```

## 覆盖率报告

测试套件生成全面的覆盖率报告：

- **控制台输出**：逐行覆盖率详细信息
- **HTML 报告**：`coverage_html/` 中的详细覆盖率报告
- **XML 报告**：用于 CI/CD 集成的覆盖率数据
- **摘要统计**：总体覆盖率百分比和缺失行

## 示例输出

```
============================================================
Test Summary
============================================================
PASSED - test/backend/services/test_agent_service.py
PASSED - test/backend/services/test_conversation_management_service.py
PASSED - test/backend/services/test_knowledge_summary_service.py

Test Results:
  Total Tests: 96
  Passed: 96
  Failed: 0
  Pass Rate: 100.0%

Total Coverage: 86.5%
HTML coverage report generated in: test\coverage_html
XML coverage report generated: test\coverage.xml
```

## 依赖项

测试运行器启动时会检查所需依赖（不会自动安装），缺失时会退出并提示安装命令：

- `pytest-cov` - 用于 pytest 覆盖率集成
- `coverage` - 用于代码覆盖率分析
- `pytest-asyncio` - 用于异步测试执行

## 最佳实践

1. **始终在导入模块之前模拟外部依赖**
2. **使用描述性的测试名称**来解释正在测试的内容
3. **遵循设置-执行-断言模式**以获得清晰的测试结构
4. **测试成功和失败场景**以获得全面的覆盖率
5. **保持测试独立** - 每个测试都应该能够独立运行
6. **使用有意义的模拟数据**来代表真实世界的场景
7. **用清晰的注释记录复杂的测试场景**

这个测试框架确保所有代码更改在部署前都经过彻底验证，在整个 Nexent 平台中保持高代码质量和可靠性。