import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from pydantic import ValidationError

from agents.nl2agent_agent import (
    GeneratedAgentDraft,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SearchInstalledMcpToolsErrorObservation,
    SearchInstalledMcpToolsObservation,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
}

# Create MCP server
local_mcp_service = FastMCP("local")


@local_mcp_service.tool(
    name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
    description=(
        "Search the current tenant's installed and available MCP tools using a complete agent draft. "
        "Returns a structured JSON observation ordered by relevance."
    ),
    meta={"nexent_internal": True},
)
async def search_installed_mcp_tools(draft: dict[str, Any]) -> str:
    """Search safe MCP tool metadata for the tenant in the current request."""

    try:
        validated_draft = GeneratedAgentDraft.model_validate(draft)
    except ValidationError:
        return SearchInstalledMcpToolsErrorObservation(
            code="invalid_draft"
        ).model_dump_json()

    try:
        # Keep NL2Agent runtime dependencies out of the MCP server startup path.
        from services.nl2agent_service import search_installed_mcp_tools_for_tenant

        authorization = get_http_request().headers.get("Authorization")
        _, tenant_id = get_current_user_id(authorization)
        recommendations = search_installed_mcp_tools_for_tenant(
            tenant_id=tenant_id,
            draft=validated_draft,
        )
    except Exception:
        logger.exception("Failed to search installed MCP tools from local MCP service")
        return SearchInstalledMcpToolsErrorObservation(
            code="tool_search_failed"
        ).model_dump_json()

    return SearchInstalledMcpToolsObservation(
        recommendation_count=len(recommendations),
        recommendations=recommendations,
    ).model_dump_json()


@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"
