# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize MCP bindings for a prepared AgentOS execution."""

from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import MCPExecutionBinding, SkillDerivedMCPBinding
from contracts.errors.exceptions import ValidationError
from infrastructure.mcp_execution import build_mcp_tool, mcp_binding_identity, mcp_execution_revision, select_mcp_server
from infrastructure.rdb.mcp_execution_records import (
    read_bound_mcp_tools, read_mcp_execution_servers, read_skill_derived_mcp_tools,
)


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
        keys = [
            ("explicit", binding.instance_id) if isinstance(binding, MCPExecutionBinding) else ("skill", binding.tool_id)
            for binding in bindings
        ]
        if len(set(keys)) != len(keys) or len({binding.tool_name for binding in bindings}) != len(bindings):
            raise ValueError("Duplicate MCP tool")
        tenant_id = self.actor.tenant_id
        scope = (resource.agent_id, resource.version_no, tenant_id)
        direct_names = [binding.tool_name for binding in bindings if isinstance(binding, MCPExecutionBinding)]
        derived_names = [binding.tool_name for binding in bindings if isinstance(binding, SkillDerivedMCPBinding)]
        rows = {("explicit", row["tool_instance_id"]): row for row in (
            read_bound_mcp_tools(*scope, direct_names) if direct_names else ()
        )}
        if derived_names:
            try:
                derived = read_skill_derived_mcp_tools(*scope, derived_names)
            except ValidationError as exc:
                raise HTTPException(status_code=409, detail={"code": "AGENTOS_MCP_REVISION_MISMATCH"}) from exc
            rows.update({("skill", row["tool_id"]): row for row in derived})
        skill_ids = {ref.instance_id for ref in resource.skill_refs}
        if self._servers is None:
            self._servers = read_mcp_execution_servers(tenant_id)

        tools = []
        for key, binding in zip(keys, bindings):
            row = rows.get(key)
            if row is None or row["name"] != binding.tool_name:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_MCP_TOOL_NOT_FOUND"})
            if key[0] == "skill" and not set(row["skill_instance_ids"]) <= skill_ids:
                raise HTTPException(status_code=409, detail={"code": "AGENTOS_MCP_REVISION_MISMATCH"})
            tool = build_mcp_tool(row)
            origin_name = row["origin_name"] or tool.class_name
            try:
                server_id, host = select_mcp_server(self._servers, tool.usage, tenant_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_MCP_SERVER_NOT_FOUND"}) from exc
            revision = mcp_execution_revision(
                tenant_id, resource.agent_id, resource.version_no, mcp_binding_identity(row),
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
        if binding.credential_ref is not None:
            raise ValueError("Unsupported MCP tool binding")
        if binding.version == "1":
            return MCPExecutionBinding.model_validate(binding.parameters)
        if binding.version == "2":
            return SkillDerivedMCPBinding.model_validate(binding.parameters)
        raise ValueError("Unsupported MCP tool binding")
