import logging
import re
import unicodedata

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from agents.nl2agent_agent import (
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


def _prepare_search_keywords(keywords: list[str]) -> list[str] | None:
    """Validate and de-duplicate keyword input while preserving its order."""

    if not 1 <= len(keywords) <= 10:
        return None

    prepared_keywords: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        stripped_keyword = keyword.strip()
        if not stripped_keyword or len(stripped_keyword) > 100:
            return None

        normalized_keyword = unicodedata.normalize(
            "NFKC", stripped_keyword
        ).casefold()
        normalized_keyword = re.sub(r"\s+", " ", normalized_keyword)
        if normalized_keyword in seen:
            continue

        seen.add(normalized_keyword)
        prepared_keywords.append(stripped_keyword)

    return prepared_keywords


@local_mcp_service.tool(
    name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
    description=(
        "Search the current tenant's installed and available MCP tools using keywords. "
        "Returns a structured JSON observation ordered by relevance."
    ),
    meta={"nexent_internal": True},
)
async def search_installed_mcp_tools(keywords: list[str]) -> str:
    """Search safe MCP tool metadata for the tenant in the current request."""

    prepared_keywords = _prepare_search_keywords(keywords)
    if prepared_keywords is None:
        return SearchInstalledMcpToolsErrorObservation(
            code="invalid_keywords"
        ).model_dump_json()

    try:
        # Keep NL2Agent runtime dependencies out of the MCP server startup path.
        from services.nl2agent_service import search_installed_mcp_tools_by_query

        authorization = get_http_request().headers.get("Authorization")
        _, tenant_id = get_current_user_id(authorization)
        recommendations = search_installed_mcp_tools_by_query(
            tenant_id=tenant_id,
            query_text=" ".join(prepared_keywords),
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
