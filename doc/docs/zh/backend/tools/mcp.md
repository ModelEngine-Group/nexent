# Model Context Protocol (MCP)

## 🌟 什么是 MCP？

Model Context Protocol (MCP) 是连接 AI 与外部系统（数据、工具、工作流）的开放标准，相当于 AI 的 "USB-C"。它让主机（如 Claude Desktop、Nexent）按统一协议发现并调用 MCP 服务器暴露的工具/资源。

## 🧭 MCP 能力

- **Tools**：可由 LLM 调用的函数（需用户授权）
- **Resources**：可读取的文件型数据
- **Prompts**：服务器可共享的模板
- 主机可通过标准协议连接本地或远程 MCP 服务器，自动发现能力

## 🌐 语言支持

MCP 协议支持多种编程语言：

- **Python** ⭐（推荐新手使用）
- **TypeScript**
- **Java**
- **Go**
- **Rust**
- 以及其他支持 MCP 协议的语言

我们推荐使用 **Python**，因为它语法简洁易学，拥有 FastMCP 等丰富框架支持，可以快速构建原型，且有数千个成熟的第三方库可用。

## 🚀 快速开始

### 📋 前置要求

在开始之前，请安装 FastMCP：

```bash
pip install fastmcp
```

### 📝 基础示例

创建一个简单的字符串处理 MCP 服务器：

```python
from fastmcp import FastMCP

# 创建MCP服务器实例
mcp = FastMCP(name="String MCP Server")

@mcp.tool(
    name="calculate_string_length",
    description="计算输入字符串的长度"
)
def calculate_string_length(text: str) -> int:
    return len(text)

@mcp.tool(
    name="to_uppercase",
    description="将字符串转换为大写"
)
def to_uppercase(text: str) -> str:
    return text.upper()

@mcp.tool(
    name="to_lowercase",
    description="将字符串转换为小写"
)
def to_lowercase(text: str) -> str:
    return text.lower()

if __name__ == "__main__":
    # 使用SSE协议启动服务
    mcp.run(transport="sse", port=8000)
```

### 🏃 运行服务器

保存代码为 `mcp_server.py`，然后运行：

```bash
python mcp_server.py
```

您将看到 MCP 服务器成功启动，服务地址为 `http://127.0.0.1:8000/sse`。

## 🔌 集成到 Nexent

MCP 服务器运行后，将其连接到 Nexent：

### 📍 步骤 1：启动 MCP 服务器

确保服务器正在运行，并记录其访问地址（例如 `http://127.0.0.1:8000/sse`）。

### ⚙️ 步骤 2：在 Nexent 中注册

1. 进入 **[智能体开发](../../user-guide/agent-development)** 页面
2. 在"选择Agent的工具"页签右侧，点击"**MCP配置**"
3. 在弹出的配置窗口中，输入服务器名称和服务器URL
   - ⚠️ **注意**：
     - 服务器名称只能包含英文字母、数字、下划线（`_`）和连字符（`-`），不能包含空格等其他字符
     - 如果使用 Docker 容器部署 Nexent，且 MCP 服务器运行在宿主机上，需要将 `127.0.0.1` 替换为 `host.docker.internal`（例如 `http://host.docker.internal:8000`）
4. 点击"**添加**"按钮完成配置

### 🎯 步骤 3：使用 MCP 工具

配置完成后，在创建或编辑智能体时，您可以在工具列表中找到并选择您添加的 MCP 工具。

## 🔧 高级用例

### 🌐 包装 REST API

将现有的 REST API 包装为 MCP 工具：

```python
from fastmcp import FastMCP
import requests

mcp = FastMCP("Course Statistics Server")

@mcp.tool(
    name="get_course_statistics",
    description="根据课程号获取某门课程的成绩统计信息（包含平均分、最高分、最低分等）"
)
def get_course_statistics(course_id: str) -> str:
    api_url = "https://your-school-api.com/api/courses/statistics"
    response = requests.get(api_url, params={"course_id": course_id})
    
    if response.status_code == 200:
        data = response.json()
        stats = data.get("statistics", {})
        return f"课程 {course_id} 成绩统计：\n平均分: {stats.get('average', 'N/A')}\n最高分: {stats.get('max', 'N/A')}\n最低分: {stats.get('min', 'N/A')}\n总人数: {stats.get('total_students', 'N/A')}"
    return f"API调用失败: {response.status_code}"

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
```

### 🏢 包装内部服务

集成本地业务逻辑：

```python
from fastmcp import FastMCP
from your_school_module import query_course_statistics

mcp = FastMCP("Course Statistics Server")

@mcp.tool(
    name="get_course_statistics",
    description="根据课程号获取某门课程的成绩统计信息（包含平均分、最高分、最低分等）"
)
def get_course_statistics(course_id: str) -> str:
    try:
        stats = query_course_statistics(course_id)
        return f"课程 {course_id} 成绩统计：\n平均分: {stats.get('average', 'N/A')}\n最高分: {stats.get('max', 'N/A')}\n最低分: {stats.get('min', 'N/A')}\n总人数: {stats.get('total_students', 'N/A')}"
    except Exception as e:
        return f"查询成绩统计时出错: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
```

## ✅ 最佳实践

- **日志记录**: stdio 传输避免 stdout 日志（不要 `print`），日志写入 stderr/文件。[日志说明](https://modelcontextprotocol.io/docs/develop/build-server#logging-in-mcp-servers)
- **文档规范**: 工具 docstring/类型要清晰，FastMCP 会据此生成 schema
- **错误处理**: 友好处理错误，返回可读文本
- **安全性**: 敏感信息放环境变量/密钥管理，不要硬编码

## 📚 相关资源

### 🐍 Python

- [FastMCP 文档](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK 仓库](https://github.com/modelcontextprotocol/python-sdk)

### 🔤 其他语言

- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk)
- [MCP Go SDK](https://github.com/modelcontextprotocol/go-sdk)
- [MCP Rust SDK](https://github.com/modelcontextprotocol/rust-sdk)

### 📖 官方文档

- [MCP 介绍](https://modelcontextprotocol.io/docs/getting-started/intro)
- [构建服务器指南](https://modelcontextprotocol.io/docs/develop/build-server)
- [SDK 文档](https://modelcontextprotocol.io/docs/sdk)
- [MCP 协议规范](https://modelcontextprotocol.io/)

### 🔗 相关指南

- [Nexent 智能体开发指南](../../user-guide/agent-development)
- [MCP 工具生态系统概览](../../mcp-ecosystem/overview)
- [MCP 推荐](../../mcp-ecosystem/mcp-recommendations)

## 🆘 获取帮助

如果在开发 MCP 服务器时遇到问题：

1. 查看 **[常见问题](../../quick-start/faq)**
2. 在 [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) 中提问
3. 参考 [ModelScope MCP Marketplace](https://www.modelscope.cn/mcp) 中的示例服务器
