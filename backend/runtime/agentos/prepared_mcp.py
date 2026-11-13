# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize MCP bindings for a prepared AgentOS execution."""

from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import MCPExecutionBinding, SkillDerivedMCPBinding
from contracts.errors.exceptions import ValidationError
from infrastructure.mcp_execution import (
    apply_mcp_argument_overrides, build_mcp_tool, mcp_binding_identity, mcp_execution_revision, select_mcp_server,
)
from infrastructure.rdb.mcp_execution_records import (
    read_bound_mcp_tools, read_mcp_execution_servers, read_skill_derived_mcp_tools,
)


class PreparedMCP:
    def __init__(self, actor):
        self.actor = actor
        self.hosts = {}
        self._servers = None
        self._tool_servers = {}

    def materialize(self, resource, *, workbench_tools=()):
        bindings = [
            (binding.version, self._reference(binding)) for binding in resource.tools if binding.tool_id == "mcp"
        ]
        if not bindings:
            return []
        keys = [
            (version, binding.instance_id if version == "1" else binding.tool_id)
            for version, binding in bindings
        ]
        if len(set(keys)) != len(keys) or len({binding.tool_name for _, binding in bindings}) != len(bindings):
            raise ValueError("Duplicate MCP tool")
        tenant_id = self.actor.tenant_id
        scope = (resource.agent_id, resource.version_no, tenant_id)
        direct_names = [binding.tool_name for version, binding in bindings if version == "1"]
        derived_names = [binding.tool_name for version, binding in bindings if version == "2"]
        rows = {("1", row["tool_instance_id"]): row for row in (
            read_bound_mcp_tools(*scope, direct_names) if direct_names else ()
        )}
        if derived_names:
            try:
                derived = read_skill_derived_mcp_tools(*scope, derived_names)
            except ValidationError as exc:
                raise HTTPException(status_code=409, detail={"code": "AGENTOS_MCP_REVISION_MISMATCH"}) from exc
            rows.update({("2", row["tool_id"]): row for row in derived})
        mounted = {("3", row["tool_id"]): row for row in workbench_tools if row["source"] == "mcp"}
        rows.update(mounted)
        skill_ids = {ref.instance_id for ref in resource.skill_refs}
        mounted_skill_ids = {ref.skill_id for ref in resource.workbench_skill_refs} if mounted else set()
        if self._servers is None:
            self._servers = read_mcp_execution_servers(tenant_id)

        tools = []
        for key, (version, binding) in zip(keys, bindings):
            row = rows.get(key)
            if row is None or row["name"] != binding.tool_name:
                raise HTTPException(status_code=404, detail={"code": "AGENTOS_MCP_TOOL_NOT_FOUND"})
            if (version == "2" and not set(row["skill_instance_ids"]) <= skill_ids
                    or version == "3" and not set(row["workbench_skill_ids"]) <= mounted_skill_ids):
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
            tools.append(apply_mcp_argument_overrides(tool, binding.argument_overrides))
        return tools

    @staticmethod
    def _reference(binding):
        if binding.credential_ref is not None:
            raise ValueError("Unsupported MCP tool binding")
        if binding.version == "1":
            return MCPExecutionBinding.model_validate(binding.parameters)
        if binding.version in {"2", "3"}:
            return SkillDerivedMCPBinding.model_validate(binding.parameters)
        raise ValueError("Unsupported MCP tool binding")
