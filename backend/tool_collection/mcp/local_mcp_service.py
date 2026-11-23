from fastmcp import FastMCP

from tool_collection.mcp.nl2agent_mcp_service import nl2agent_mcp_service
from tool_collection.mcp.nl2agent_mcp_tools import NL2A_MCP_TOOL_NAMES

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    name: name
    for name in NL2A_MCP_TOOL_NAMES
}

# Create MCP server
local_mcp_service = FastMCP("local")
local_mcp_service.mount(
    nl2agent_mcp_service,
    nl2agent_mcp_service.name,
)


@local_mcp_service.tool(
    name="test_tool_name",
    description="test_tool_description",
)
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"
