# Model Context Protocol (MCP)

## 🌟 What is MCP?

Model Context Protocol (MCP) is an open standard for connecting AI apps to external systems (data, tools, workflows), similar to a "USB-C for AI." It standardizes how hosts (e.g., Claude Desktop, Nexent) discover and call tools/resources exposed by MCP servers.

## 🧭 What can MCP do?

- **Tools**: Functions callable by the LLM with user approval
- **Resources**: File-like data that clients can read
- **Prompts**: Reusable templates shared by servers
- Works over a simple protocol so hosts can connect to local or remote servers consistently

## 🌐 Language Support

The MCP protocol provides SDKs for multiple programming languages:

- **Python** ⭐ (recommended for beginners)
- **TypeScript**
- **Java**
- **Go**
- **Rust**
- Any other language that implements the MCP protocol

We recommend **Python** because it offers beginner-friendly syntax, rich ecosystem with frameworks like FastMCP, rapid prototyping capabilities, and thousands of mature libraries.

## 🚀 Quick Start

### 📋 Prerequisites

Install FastMCP before you start coding:

```bash
pip install fastmcp
```

### 📝 Basic Example

Create a simple string utility server with FastMCP:

```python
from fastmcp import FastMCP

# Create an MCP server instance
mcp = FastMCP(name="String MCP Server")

@mcp.tool(
    name="calculate_string_length",
    description="Calculate the length of a string"
)
def calculate_string_length(text: str) -> int:
    return len(text)

@mcp.tool(
    name="to_uppercase",
    description="Convert text to uppercase"
)
def to_uppercase(text: str) -> str:
    return text.upper()

@mcp.tool(
    name="to_lowercase",
    description="Convert text to lowercase"
)
def to_lowercase(text: str) -> str:
    return text.lower()

if __name__ == "__main__":
    # Start with SSE transport
    mcp.run(transport="sse", port=8000)
```

### 🏃 Run the Server

Save the code as `mcp_server.py` and execute:

```bash
python mcp_server.py
```

You should see the server start successfully with the endpoint `http://127.0.0.1:8000/sse`.

## 🔌 Integrate with Nexent

Once your MCP server is running, connect it to Nexent:

### 📍 Step 1: Start the MCP Server

Keep the server process running and note the endpoint (e.g., `http://127.0.0.1:8000/sse`).

### ⚙️ Step 2: Register in Nexent

1. Open the **[Agent Development](../../user-guide/agent-development)** page
2. On the "Select Agent Tools" tab, click **MCP Configuration** on the right
3. Enter the server name and server URL
   - ⚠️ **Important**:
     - Server name must contain only letters and digits (no spaces or symbols)
     - When Nexent runs inside Docker and MCP server runs on the host, replace `127.0.0.1` with `host.docker.internal` (e.g., `http://host.docker.internal:8000`)
4. Click **Add** to finish registration

### 🎯 Step 3: Use the MCP Tool

During agent creation or editing, the newly registered MCP tool appears in the tool list and can be attached to any agent.

## 🔧 Advanced Use Cases

### 🌐 Wrap a REST API

Expose existing REST APIs as MCP tools:

```python
from fastmcp import FastMCP
import requests

mcp = FastMCP("Course Statistics Server")

@mcp.tool(
    name="get_course_statistics",
    description="Get course statistics such as average, max, min, and total students"
)
def get_course_statistics(course_id: str) -> str:
    api_url = "https://your-school-api.com/api/courses/statistics"
    response = requests.get(api_url, params={"course_id": course_id})

    if response.status_code == 200:
        data = response.json()
        stats = data.get("statistics", {})
        return (
            f"Course {course_id} statistics:\n"
            f"Average: {stats.get('average', 'N/A')}\n"
            f"Max: {stats.get('max', 'N/A')}\n"
            f"Min: {stats.get('min', 'N/A')}\n"
            f"Total Students: {stats.get('total_students', 'N/A')}"
        )
    return f"API request failed: {response.status_code}"

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
```

### 🏢 Wrap an Internal Module

Integrate local business logic:

```python
from fastmcp import FastMCP
from your_school_module import query_course_statistics

mcp = FastMCP("Course Statistics Server")

@mcp.tool(
    name="get_course_statistics",
    description="Get course statistics such as average, max, min, and total students"
)
def get_course_statistics(course_id: str) -> str:
    try:
        stats = query_course_statistics(course_id)
        return (
            f"Course {course_id} statistics:\n"
            f"Average: {stats.get('average', 'N/A')}\n"
            f"Max: {stats.get('max', 'N/A')}\n"
            f"Min: {stats.get('min', 'N/A')}\n"
            f"Total Students: {stats.get('total_students', 'N/A')}"
        )
    except Exception as exc:
        return f"Failed to query statistics: {exc}"

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
```

## ✅ Best Practices

- **Logging**: For stdio transports, avoid stdout logging (no `print`); log to stderr/files. [Logging guidance](https://modelcontextprotocol.io/docs/develop/build-server#logging-in-mcp-servers)
- **Documentation**: Keep tool docstrings clear; FastMCP derives schema from type hints
- **Error Handling**: Handle errors gracefully and return user-friendly text
- **Security**: Do not hard-code secrets; load credentials from env/secret managers

## 📚 Resources

### 🐍 Python

- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK Repository](https://github.com/modelcontextprotocol/python-sdk)

### 🔤 Other Languages

- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk)
- [MCP Go SDK](https://github.com/modelcontextprotocol/go-sdk)
- [MCP Rust SDK](https://github.com/modelcontextprotocol/rust-sdk)

### 📖 Official Documentation

- [MCP Introduction](https://modelcontextprotocol.io/docs/getting-started/intro)
- [Build MCP Server Guide](https://modelcontextprotocol.io/docs/develop/build-server)
- [SDK Documentation](https://modelcontextprotocol.io/docs/sdk)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)

### 🔗 Related Guides

- [Nexent Agent Development Guide](../../user-guide/agent-development)
- [MCP Tool Ecosystem Overview](../../mcp-ecosystem/overview)
- [MCP Recommendations](../../mcp-ecosystem/mcp-recommendations)

## 🆘 Need Help?

If you run into issues while developing MCP servers:

1. Check the **[FAQ](../../quick-start/faq)**
2. Ask questions in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)
3. Review sample servers on the [ModelScope MCP Marketplace](https://www.modelscope.cn/mcp)
