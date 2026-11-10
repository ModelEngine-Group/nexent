# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export enabled SDK tool references from an authorized Agent configuration."""

from contracts.agentos import SkillDerivedLocalToolBinding, StoredLocalToolBinding, ToolBinding
from infrastructure.local_tool_execution import build_local_tool, local_tool_rerank_name, local_tool_revision
from management.services.agent.preparation.knowledge_search import _rerank_bindings
from nexent.core.agents.agent_model import ToolConfig


def export_local_tool(
    tool: ToolConfig, candidates: list[dict], agent_id: int, version_no: int, tenant_id: str, language: str,
) -> ToolBinding:
    matches = [row for row in candidates if row["name"] == tool.name]
    if len(matches) != 1:
        raise ValueError("Local SDK tool does not have one enabled instance")
    row = matches[0]
    persisted = build_local_tool(row, language, tool.description_zh, tool.inputs)
    if persisted != tool:
        raise ValueError("Local SDK tool differs from its persisted instance")
    rerank_name = local_tool_rerank_name(persisted)
    selected, default = _rerank_bindings(tenant_id, rerank_name) if rerank_name else (None, None)
    options = {
        "revision": local_tool_revision(tenant_id, agent_id, version_no, row, persisted),
        "description_zh": persisted.description_zh,
        "inputs": persisted.inputs,
        "reranker": selected,
        "default_reranker": default,
    }
    if "skill_instance_ids" in row:
        binding = SkillDerivedLocalToolBinding(tool_id=row["tool_id"], **options)
        version = "2"
    else:
        binding = StoredLocalToolBinding(instance_id=row["tool_instance_id"], **options)
        version = "1"
    return ToolBinding(tool_id=persisted.name, version=version, parameters=binding.model_dump(mode="json"))
