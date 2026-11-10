# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rebuild pinned MCP tool and connection configuration from authorized records."""

import hmac
import json
from urllib.parse import quote, urljoin

from contracts.constants import environment
from nexent.core.agents.agent_model import ToolConfig

LOCAL_MCP_NAME = "outer-apis"


def get_tenant_local_mcp_server(tenant_id: str) -> str:
    """Return the tenant-scoped SSE endpoint for built-in/API-converted tools."""
    if not tenant_id:
        raise ValueError("tenant_id is required for the local MCP endpoint")
    return urljoin(
        environment.LOCAL_MCP_SERVER.rstrip("/") + "/",
        f"mcp/{quote(str(tenant_id), safe='')}/sse",
    )


def build_mcp_tool(row: dict) -> ToolConfig:
    configured = row["instance_params"] or {}
    parameters = {
        param["name"]: configured[param["name"]] if configured.get(param["name"]) is not None else param.get("default")
        for param in row["params"]
    }
    return ToolConfig(
        class_name=row["class_name"], name=row["name"], description=row["description"],
        inputs=row["inputs"], output_type=row["output_type"], params=parameters, source="mcp", usage=row["usage"],
    )


def select_mcp_server(records: list[dict], usage: str, tenant_id: str) -> tuple[int | None, dict]:
    local_url = get_tenant_local_mcp_server(tenant_id) if environment.LOCAL_MCP_SERVER else None
    if usage == LOCAL_MCP_NAME:
        if local_url is None:
            raise LookupError("Local MCP server is not configured")
        server_id, url = None, local_url
        headers = {"X-Tenant-ID": tenant_id, "X-Nexent-Internal-Token": environment.TOKEN}
    else:
        matches = [record for record in records if record["mcp_name"] == usage]
        if len(matches) != 1 or matches[0]["enabled"] is False:
            raise LookupError("MCP server is not available")
        record = matches[0]
        server_id, url = record["mcp_id"], record["mcp_server"]
        headers = {"Authorization": record["authorization_token"]} if record["authorization_token"] else {}
        if isinstance(record["custom_headers"], dict):
            headers.update(record["custom_headers"])

    if not url or (server_id is not None and url == local_url) or any(
        record["mcp_server"] == url and record["mcp_id"] != server_id for record in records
    ):
        raise ValueError("Ambiguous MCP endpoint")
    host = {"url": url, "transport": "sse" if url.endswith("/sse") else "streamable-http"}
    if headers:
        host["headers"] = headers
    return server_id, host


def mcp_binding_identity(row: dict) -> int | list[int | str]:
    if "workbench_skill_ids" in row:
        return ["workbench", row["tool_id"], *row["workbench_skill_ids"]]
    if "skill_instance_ids" in row:
        return [row["tool_id"], *row["skill_instance_ids"]]
    return row["tool_instance_id"]


def mcp_execution_revision(tenant_id: str, agent_id: int, version_no: int, binding_identity: int | list[int | str],
                           tool: ToolConfig, origin_name: str, server_id: int | None, host: dict) -> str:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/mcp-execution/v1", "sha256")
    values = [tenant_id, agent_id, version_no, binding_identity, tool.model_dump(mode="json"), origin_name, server_id, host]
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()
