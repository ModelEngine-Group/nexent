# MCP Tools Development Guide

This document explains how to add custom MCP tools to the Nexent system.

## Project Structure

```
backend/tool_collection/mcp/
└── local_mcp_service.py    # Main MCP service file
```

The MCP service is loaded by `backend/mcp_service.py`, which:
- Creates a main `nexent_mcp` server
- Mounts the local MCP service to it
- Exposes tools via SSE transport on port 5011

## How to Add a New Tool

### Step 1: Create a new service file

Create a new file in the `mcp/` directory (e.g., `my_tools.py`):

```python
from fastmcp import FastMCP

my_tools_service = FastMCP("my_tools")

@my_tools_service.tool(
    name="my_custom_tool",
    description="Description of what this tool does"
)
async def my_custom_tool(param1: str, param2: int) -> str:
    """
    Tool implementation.

    Args:
        param1: First parameter description
        param2: Second parameter description

    Returns:
        Result description
    """
    # Your tool logic here
    return f"Result: {param1}, {param2}"
```

### Step 2: Register the service in mcp_service.py

Open `backend/mcp_service.py` and add the import:

```python
from tool_collection.mcp.my_tools import my_tools_service
```

Then add the mount call (around line 73):

```python
nexent_mcp.mount(my_tools_service.name, my_tools_service)
```

### Step 3: Restart the MCP Server

The MCP service runs in Docker containers. You need to restart the relevant containers for changes to take effect:

```bash
# Navigate to docker directory
cd docker

# Restart MCP-related container
docker compose restart nexent-mcp

# If other services need updates, restart them together
docker compose restart nexent-config nexent-runtime nexent-northbound
```

**Related containers:**

| Container | Port | Description |
|-----------|------|-------------|
| `nexent-mcp` | 5011 | MCP tools service main container |
| `nexent-config` | 5010 | Config service |
| `nexent-runtime` | 5014 | Runtime service |
| `nexent-northbound` | 5013 | Northbound API service |
| `nexent-data-process` | 5012 | Data processing service |

**Verify restart success:**

```bash
# Check container status
docker compose ps

# View MCP container logs
docker compose logs -f nexent-mcp
```

## Tool Definition Guidelines

### Decorator Parameters

| Parameter | Description |
|-----------|-------------|
| `name` | Unique identifier for the tool (snake_case recommended) |
| `description` | Human-readable description for AI agents |

### Function Signature

- Use type hints for all parameters and return values
- Use async functions for I/O operations
- Keep functions focused and single-purpose

### Supported Types

| Type | Python Type |
|------|-------------|
| String | `str` |
| Integer | `int` |
| Float | `float` |
| Boolean | `bool` |
| Array | `List[T]` |
| Object | `Dict[str, Any]` |

### Example with Complex Types

```python
from typing import List, Dict, Any

@my_tools_service.tool(
    name="process_items",
    description="Process a list of items"
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

## Best Practices

1. **One service per module**: Group related tools in the same service
2. **Descriptive names**: Use clear, action-oriented names like `get_user_data` not `user`
3. **Document parameters**: Include docstrings explaining each parameter
4. **Error handling**: Let exceptions propagate; the MCP framework handles error responses
5. **Async by default**: Use `async def` for better concurrency

## Troubleshooting

### Tools not appearing

1. Verify the service is properly imported in `mcp_service.py`
2. Check that `mount()` is called after import
3. Ensure the MCP server was restarted
4. Check logs for import errors

### Type errors

1. Verify all function parameters have type hints
2. Ensure return types are compatible with MCP protocol
3. Use `Dict[str, Any]` for flexible object parameters

## Reference

- FastMCP Documentation: https://fastmcp.readthedocs.io/
- MCP Protocol: https://modelcontextprotocol.io/
