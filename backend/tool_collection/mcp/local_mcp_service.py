from fastmcp import FastMCP

from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_MCP_TOOL_META,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    nl2a_wrapper as _nl2a_wrapper,
    search_installed_mcp_tools as _search_installed_mcp_tools,
)

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
    NL2A_WRAPPER_NAME: NL2A_WRAPPER_NAME,
}

# Create MCP server
local_mcp_service = FastMCP("local")
local_mcp_service.tool(
    _search_installed_mcp_tools,
    name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
    description=SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
local_mcp_service.tool(
    _nl2a_wrapper,
    name=NL2A_WRAPPER_NAME,
    description=NL2A_WRAPPER_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)


@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"
