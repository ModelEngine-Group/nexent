# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reconstruct authorized LangChain tools from pinned deployment plugins."""

from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import AgentResource, LangChainToolBinding
from contracts.errors.exceptions import ValidationError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.langchain_plugins import (
    build_langchain_tool, langchain_binding_revision, load_langchain_plugin,
    read_bound_langchain_tools, read_skill_derived_langchain_tools,
)
from nexent.core.agents.agent_model import ToolConfig


def materialize_langchain_tools(resource: AgentResource, actor: ServicePrincipal) -> list[ToolConfig]:
    references = []
    for binding in resource.tools:
        if binding.tool_id == "langchain":
            if binding.version not in {"1", "2"} or binding.credential_ref is not None:
                raise ValueError("Unsupported LangChain tool binding")
            references.append((binding.version, LangChainToolBinding.model_validate(binding.parameters)))
    if not references:
        return []
    if len({reference.tool_name for _, reference in references}) != len(references):
        raise ValueError("Duplicate LangChain tool binding")

    scope = (resource.agent_id, resource.version_no, actor.tenant_id)
    explicit_names = [ref.tool_name for version, ref in references if version == "1"]
    derived_names = [ref.tool_name for version, ref in references if version == "2"]
    direct = read_bound_langchain_tools(*scope, explicit_names) if explicit_names else []
    try:
        derived = read_skill_derived_langchain_tools(*scope, derived_names) if derived_names else []
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_LANGCHAIN_REVISION_MISMATCH"}) from exc
    rows = {("1", row["tool_instance_id"], row["name"]): row for row in direct}
    rows.update({("2", row["tool_id"], row["name"]): row for row in derived})
    skill_ids = {ref.instance_id for ref in resource.skill_refs} if derived_names else set()
    tools = []
    loaded = {}
    for version, reference in references:
        row = rows.get((version, reference.binding_id, reference.tool_name))
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_LANGCHAIN_TOOL_NOT_FOUND"})
        if version == "2" and not set(row["skill_instance_ids"]) <= skill_ids:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_LANGCHAIN_REVISION_MISMATCH"})
        try:
            tool = build_langchain_tool(row)
            revision = langchain_binding_revision(scope, row, tool, reference.module_file, reference.module_revision)
            if not compare_digest(revision, reference.revision):
                raise ValueError("LangChain tool revision changed")
            plugin_key = (reference.module_file, reference.module_revision)
            if plugin_key not in loaded:
                loaded[plugin_key] = load_langchain_plugin(*plugin_key)
            tool.metadata = loaded[plugin_key][tool.name]
        except (FileNotFoundError, LookupError) as exc:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_LANGCHAIN_TOOL_NOT_FOUND"}) from exc
        except (TypeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_LANGCHAIN_REVISION_MISMATCH"}) from exc
        tools.append(tool)
    return tools
