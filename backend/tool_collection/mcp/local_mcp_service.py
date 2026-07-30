from fastmcp import FastMCP

from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2A_WRAPPER_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    register_nl2agent_mcp_tools,
)

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
    NL2A_WRAPPER_NAME: NL2A_WRAPPER_NAME,
}

# Create MCP server
local_mcp_service = FastMCP("local")
register_nl2agent_mcp_tools(local_mcp_service)


@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"
