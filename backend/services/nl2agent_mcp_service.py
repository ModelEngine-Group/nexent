"""MCP installation and tool-binding operations for NL2AGENT drafts."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from consts.exceptions import AgentRunException
from consts.model import ToolInstanceInfoRequest


@dataclass(frozen=True)
class McpBindingDependencies:
    """Persistence operations required to resolve MCP tool binding."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    get_mcp_record: Callable[..., Dict[str, Any] | None]
    query_tools_by_ids: Callable[..., List[Dict[str, Any]]]
    bind_tool: Callable[..., Any]
    find_mcp_workflow_by_id: Callable[..., tuple[str, Dict[str, Any]]]
    update_mcp_workflow: Callable[..., Any]


async def bind_mcp_tools(
    dependencies: McpBindingDependencies,
    *,
    agent_id: int,
    mcp_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Bind user-selected tools belonging to an installed MCP."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    if not tool_ids:
        raise AgentRunException("Select at least one discovered MCP tool to bind.")
    record = dependencies.get_mcp_record(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise AgentRunException("Installed MCP not found.")
    rows = dependencies.query_tools_by_ids(tool_ids) if tool_ids else []
    valid = {
        int(row["tool_id"]): row
        for row in rows
        if row.get("author") == tenant_id
        and row.get("source") == "mcp"
        and row.get("usage") == record.get("mcp_name")
    }
    if set(map(int, tool_ids)) != set(valid):
        raise AgentRunException("One or more tools do not belong to the selected MCP.")
    for tool_id in valid:
        dependencies.bind_tool(
            ToolInstanceInfoRequest(
                tool_id=tool_id,
                agent_id=agent_id,
                params={},
                enabled=True,
                version_no=0,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=0,
        )
    recommendation_id, _ = dependencies.find_mcp_workflow_by_id(
        tenant_id,
        agent_id,
        mcp_id,
    )
    dependencies.update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        status="tools_bound",
        bound_tool_ids=sorted(valid),
    )
    return {
        "agent_id": agent_id,
        "mcp_id": mcp_id,
        "bound_tool_ids": sorted(valid),
    }


async def skip_mcp_tool_binding(
    dependencies: McpBindingDependencies,
    *,
    agent_id: int,
    mcp_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Resolve an installed MCP without binding discovered tools."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    if not dependencies.get_mcp_record(mcp_id=mcp_id, tenant_id=tenant_id):
        raise AgentRunException("Installed MCP not found.")
    recommendation_id, workflow = dependencies.find_mcp_workflow_by_id(
        tenant_id,
        agent_id,
        mcp_id,
    )
    if workflow.get("status") != "connected":
        raise AgentRunException("MCP tool binding is already resolved.")
    dependencies.update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        status="binding_skipped",
        bound_tool_ids=[],
    )
    return {
        "agent_id": agent_id,
        "mcp_id": mcp_id,
        "status": "binding_skipped",
    }
