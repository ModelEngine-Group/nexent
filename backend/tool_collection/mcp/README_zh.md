# MCP 工具开发指南

本文档介绍如何向 Nexent 系统添加自定义 MCP 工具。

## 项目结构

```
backend/tool_collection/mcp/
└── local_mcp_service.py    # MCP 服务主文件
```

MCP 服务由 `backend/mcp_service.py` 加载，该文件会：
- 创建一个主 `nexent_mcp` 服务器
- 将本地 MCP 服务挂载到主服务器
- 通过 SSE 传输在 5011 端口暴露工具

## 如何添加新工具

### 步骤 1：创建新的服务文件

在 `mcp/` 目录下创建新文件（例如 `my_tools.py`）：

```python
from fastmcp import FastMCP

my_tools_service = FastMCP("my_tools")

@my_tools_service.tool(
    name="my_custom_tool",
    description="工具功能的描述"
)
async def my_custom_tool(param1: str, param2: int) -> str:
    """
    工具实现。

    参数:
        param1: 第一个参数描述
        param2: 第二个参数描述

    返回:
        结果描述
    """
    # 工具逻辑实现
    return f"结果: {param1}, {param2}"
```

### 步骤 2：在 mcp_service.py 中注册服务

打开 `backend/mcp_service.py` 并添加导入：

```python
from tool_collection.mcp.my_tools import my_tools_service
```

然后添加挂载调用（约第 73 行）：

```python
nexent_mcp.mount(my_tools_service.name, my_tools_service)
```

### 步骤 3：重启 MCP 服务器

MCP 服务运行在 Docker 容器中，需要重启以下容器使更改生效：

```bash
# 进入 docker 目录
cd docker

# 重启 MCP 相关容器
docker compose restart nexent-mcp

# 如果其他服务也需要更新，可以一起重启
docker compose restart nexent-config nexent-runtime nexent-northbound
```

**相关容器说明：**

| 容器名 | 端口 | 说明 |
|--------|------|------|
| `nexent-mcp` | 5011 | MCP 工具服务主容器 |
| `nexent-config` | 5010 | 配置服务 |
| `nexent-runtime` | 5014 | 运行时服务 |
| `nexent-northbound` | 5013 | 北向接口服务 |
| `nexent-data-process` | 5012 | 数据处理服务 |

**验证重启成功：**

```bash
# 查看容器状态
docker compose ps

# 查看 MCP 容器日志
docker compose logs -f nexent-mcp
```

## 工具定义指南

### 装饰器参数

| 参数 | 描述 |
|------|------|
| `name` | 工具的唯一标识符（推荐使用 snake_case） |
| `description` | 供 AI 代理阅读的人类可读描述 |

### 函数签名

- 所有参数和返回值都要使用类型提示
- I/O 操作使用异步函数
- 保持函数职责单一

### 支持的类型

| 类型 | Python 类型 |
|------|-------------|
| 字符串 | `str` |
| 整数 | `int` |
| 浮点数 | `float` |
| 布尔值 | `bool` |
| 数组 | `List[T]` |
| 对象 | `Dict[str, Any]` |

### 复杂类型示例

```python
from typing import List, Dict, Any

@my_tools_service.tool(
    name="process_items",
    description="处理列表中的项目"
)
async def process_items(
    items: List[str],
    options: Dict[str, Any]
) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        results.append({
            "item": item,
            "processed": True,
            "options": options
        })
    return results
```

## 最佳实践

1. **每个模块一个服务**：将相关工具分组到同一个服务中
2. **描述性命名**：使用清晰的动作导向名称，如 `get_user_data` 而非 `user`
3. **文档化参数**：包含说明每个参数的文档字符串
4. **错误处理**：让异常传播；MCP 框架会处理错误响应
5. **默认异步**：使用 `async def` 以获得更好的并发性

## 故障排除

### 工具不显示

1. 验证服务是否在 `mcp_service.py` 中正确导入
2. 检查 `mount()` 是否在导入后被调用
3. 确保 MCP 服务器已重启
4. 检查日志中是否有导入错误

### 类型错误

1. 验证所有函数参数都有类型提示
2. 确保返回类型与 MCP 协议兼容
3. 对灵活的对象参数使用 `Dict[str, Any]`

## 参考资料

- FastMCP 文档：https://fastmcp.readthedocs.io/
- MCP 协议：https://modelcontextprotocol.io/
