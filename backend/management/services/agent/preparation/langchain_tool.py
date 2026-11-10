# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export a LangChain tool reference without serializing its Python object."""

from contracts.agentos import LangChainToolBinding, ToolBinding
from infrastructure.langchain_plugins import build_langchain_tool, langchain_binding_revision
from nexent.core.agents.agent_model import ToolConfig


def export_langchain_tool(tool: ToolConfig, candidates, artifacts, agent_id, version_no, tenant_id) -> ToolBinding:
    matches = [row for row in candidates if row["name"] == tool.name]
    artifact = artifacts.get(tool.name)
    if len(matches) != 1 or artifact is None:
        raise ValueError("LangChain tool has no unambiguous instance and plugin")
    row = matches[0]
    persisted = build_langchain_tool(row)
    if persisted != tool:
        raise ValueError("LangChain tool differs from its persisted instance")
    filename, digest = artifact
    version = "2" if "skill_instance_ids" in row else "1"
    reference = LangChainToolBinding(
        binding_id=row["tool_id"] if version == "2" else row["tool_instance_id"], tool_name=tool.name,
        module_file=filename, module_revision=digest,
        revision=langchain_binding_revision((agent_id, version_no, tenant_id), row, persisted, filename, digest),
    )
    return ToolBinding(tool_id="langchain", version=version, parameters=reference.model_dump(mode="json"))
