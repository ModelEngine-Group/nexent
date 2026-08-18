from fastmcp import FastMCP

from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_MCP_TOOL_META,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_DESCRIPTION,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_INSTALLED_RESOURCES_NAME,
    nl2a_wrapper as _nl2a_wrapper,
    recommend_resources as _recommend_resources,
    save_agent_draft_fields as _save_agent_draft_fields,
    search_installed_mcp_tools as _search_installed_mcp_tools,
    search_installed_resources as _search_installed_resources,
)

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME: SEARCH_INSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME: RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME: SAVE_AGENT_DRAFT_FIELDS_NAME,
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
    _search_installed_resources,
    name=SEARCH_INSTALLED_RESOURCES_NAME,
    description=SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
local_mcp_service.tool(
    _recommend_resources,
    name=RECOMMEND_RESOURCES_NAME,
    description=RECOMMEND_RESOURCES_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
local_mcp_service.tool(
    _save_agent_draft_fields,
    name=SAVE_AGENT_DRAFT_FIELDS_NAME,
    description=SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
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
