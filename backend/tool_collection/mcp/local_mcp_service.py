from fastmcp import FastMCP

from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2A_WRAPPER_NAME,
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
_search_installed_mcp_tool = local_mcp_service.tool(
    _search_installed_mcp_tools,
    name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
    description=(
        "Search the current tenant's installed and available MCP tools using keywords. "
        "Returns a structured JSON observation ordered by relevance. "
        "Call the tool as `result = search_installed_mcp_tools(...)`, then use "
        "`print(result)` to preserve the returned JSON unchanged in execution logs."
    ),
    meta={"nexent_internal": True},
)
_nl2a_wrapper_tool = local_mcp_service.tool(
    _nl2a_wrapper,
    name=NL2A_WRAPPER_NAME,
    description=(
        "Build one NL2Agent output from subtype-specific parameters. Always pass "
        "`subtype`. For `local_mcp_recommendation`, also pass `search_result` and "
        "`selected_tool_ids`. For `agent_draft`, pass the agent draft fields. Call "
        "the tool as `result = nl2a_wrapper(...)`, then use `print(result)`."
    ),
    meta={"nexent_internal": True},
)


def get_nl2agent_mcp_tool_descriptions() -> dict[str, str]:
    """Return descriptions from the registered NL2Agent MCP tools."""
    return {
        SEARCH_INSTALLED_MCP_TOOLS_NAME: _search_installed_mcp_tool.description,
        NL2A_WRAPPER_NAME: _nl2a_wrapper_tool.description,
    }


@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"
