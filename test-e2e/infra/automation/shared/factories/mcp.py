"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
import os
import uuid
from shared.http import MODEL_TIMEOUT
from shared.asset_registry import AssetDependencyError, register_asset, resolve_asset
from shared.factories.agent import _draft_agent


async def _ensure_mcp_agent(identity) -> int:
    """Create the controlled MCP service and its bound Agent through Nexent APIs."""
    existing = resolve_asset("agents", "mcp_id", required=False)
    if existing is not None:
        return int(existing)

    server_url = os.getenv("NEXENT_TEST_MCP_URL", "").strip()
    if not server_url:
        raise AssetDependencyError(
            "services", "controlled_mcp_url",
            dependency_case_id="D0-MCP",
            detail="NEXENT_TEST_MCP_URL is required for controlled MCP asset production",
        )

    service_name = f"d3-mcp-{uuid.uuid4().hex[:10]}"
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post("/mcp/add", json={
            "name": service_name,
            "server_url": server_url,
            "description": "D3 controlled MCP Agent asset",
            "source": "local",
            "tags": ["automation", "d3"],
            "enabled": True,
            "ingroup_permission": "PRIVATE",
            "shared_fields": {"server_url": False, "authorization_token": False},
            "skip_health_check": False,
        })
        assert_status(created, 200)
        listed = await api.get("/mcp/list")
        assert_status(listed, 200)
        records = listed.json().get("remote_mcp_server_list") or []
        record = next(
            (item for item in records
             if (item.get("remote_mcp_server_name") or item.get("name")) == service_name),
            None,
        )
        if not record:
            raise AssertionError(f"created MCP service {service_name!r} was not returned by /mcp/list")
        service_id = int(record["mcp_id"])
        register_asset('mcp','service_id',service_id,owner_case_id='CTR-028',cleanup={
            'service':'config','identity':identity.id,'method':'DELETE',
            'path':f'/mcp/{service_id}','allowed_statuses':[200,404]})
        register_asset('mcp','service_name',service_name,owner_case_id='CTR-028')
        refreshed = await api.post("/mcp/refresh-tools", params={"mcp_id": service_id})
        assert_status(refreshed, 200)
        scanned = await api.get("/tool/scan_tool")
        assert_status(scanned, 200)
        tools = await api.get("/tool/list")
        assert_status(tools, 200)

    tool = next(
        (item for item in tools.json()
         if item.get("source") == "mcp"
         and item.get("usage") == service_name
         and item.get("origin_name") == "deterministic_add"),
        None,
    )
    if not tool:
        raise AssertionError(f"controlled MCP tool for {service_name!r} was not registered")
    tool_id = int(tool.get("tool_id") or tool["id"])

    async with _draft_agent(
        identity,
        name_prefix="d3-mcp-agent",
        retain_for_batch=True,
        owner_case_id="CTR-028",
        registry_role="mcp",
        enabled_tool_ids=[tool_id],
    ) as (agent_id, _payload):
        register_asset(
            "agents", "mcp_outage_id", agent_id, owner_case_id="CTR-028",
        )
        return int(agent_id)


async def prepare_tool_agent(identity) -> int:
    """Bind a case-owned Agent to the controlled deterministic MCP tool."""
    agent_id = await _ensure_mcp_agent(identity)
    register_asset('agents', 'tool_id', agent_id, owner_case_id='LOCAL-TOOL-AGENT-PREP')
    return agent_id
