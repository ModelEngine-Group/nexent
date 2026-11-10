# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize MCP bindings for a prepared AgentOS execution."""

from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import MCPExecutionBinding
from infrastructure.mcp_execution import build_mcp_tool, mcp_execution_revision, select_mcp_server
from infrastructure.rdb.mcp_execution_records import read_bound_mcp_tools, read_mcp_execution_servers


class PreparedMCP:
    def __init__(self, actor):
        self.actor = actor
        self.hosts = {}
        self._servers = None
        self._tool_servers = {}

    def materialize(self, resource):
        bindings = [
            self._reference(binding) for binding in resource.tools if binding.tool_id == "mcp"
        ]
        if not bindings:
            return []
        if len({binding.instance_id for binding in bindings}) != len(bindings):
            raise ValueError("Duplicate MCP tool instance")
        tenant_id = self.actor.tenant_id
        rows = read_bound_mcp_tools(
            resource.agent_id, resource.version_no, tenant_id, [binding.tool_name for binding in bindings],
        )
        by_id = {row["tool_instance_id"]: row for row in rows}
        if self._servers is None:
            self._servers = read_mcp_execution_servers(tenant_id)

        tools = []
        for binding in bindings:
            row = by_id.get(binding.instance_id)
            if row is None or row["name"] != binding.tool_name:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_MCP_TOOL_NOT_FOUND"})
            tool = build_mcp_tool(row)
            origin_name = row["origin_name"] or tool.class_name
            try:
                server_id, host = select_mcp_server(self._servers, tool.usage, tenant_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_MCP_SERVER_NOT_FOUND"}) from exc
            revision = mcp_execution_revision(
                tenant_id, resource.agent_id, resource.version_no, binding.instance_id,
                tool, origin_name, server_id, host,
            )
            if server_id != binding.server_id or not compare_digest(revision, binding.revision):
                raise HTTPException(status_code=409, detail={"code": "AGENTOS_MCP_REVISION_MISMATCH"})
            target = (server_id, origin_name)
            if self._tool_servers.setdefault(tool.class_name, target) != target:
                raise ValueError("Ambiguous MCP callable")
            if server_id not in self.hosts:
                if server_id is None:
                    from backend.http.client import create_httpx_client

                    host["httpx_client_factory"] = create_httpx_client
                self.hosts[server_id] = {**host, "allowed_tools": {}}
            allowed = self.hosts[server_id]["allowed_tools"]
            if allowed.setdefault(origin_name, tool.class_name) != tool.class_name:
                raise ValueError("Ambiguous MCP tool name")
            tools.append(tool)
        return tools

    @staticmethod
    def _reference(binding):
        if binding.version != "1" or binding.credential_ref is not None:
            raise ValueError("Unsupported MCP tool binding")
        return MCPExecutionBinding.model_validate(binding.parameters)
