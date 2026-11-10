# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rebuild signed SDK tool instances without accepting connection parameters."""

from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import AgentResource, StoredLocalToolBinding
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.local_tool_execution import (
    LOCAL_RERANK_TOOL_CLASSES, LOCAL_SDK_TOOL_CLASSES, build_local_tool, local_tool_rerank_name, local_tool_revision,
)
from infrastructure.rdb.local_tool_records import read_bound_local_tools
from nexent.core.agents.agent_model import ToolConfig
from runtime.agentos.prepared_knowledge import _reranker


def materialize_local_tools(resource: AgentResource, actor: ServicePrincipal, language: str) -> dict[str, ToolConfig]:
    references = {}
    for binding in resource.tools:
        if binding.tool_id not in LOCAL_SDK_TOOL_CLASSES:
            continue
        if binding.version != "1" or binding.credential_ref is not None or binding.tool_id in references:
            raise ValueError("Unsupported local SDK tool binding")
        references[binding.tool_id] = StoredLocalToolBinding.model_validate(binding.parameters)
    if not references:
        return {}

    rows = read_bound_local_tools(resource.agent_id, resource.version_no, actor.tenant_id, list(references))
    by_instance = {(row["tool_instance_id"], row["name"]): row for row in rows}
    tools = {}
    for name, reference in references.items():
        row = by_instance.get((reference.instance_id, name))
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_LOCAL_TOOL_NOT_FOUND"})
        try:
            tool = build_local_tool(row, language, reference.description_zh, reference.inputs)
            revision = local_tool_revision(actor.tenant_id, resource.agent_id, resource.version_no, row, tool)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH"}) from exc
        if not compare_digest(revision, reference.revision):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH"})
        rerank_name = local_tool_rerank_name(tool)
        if not rerank_name and (reference.reranker or reference.default_reranker):
            raise ValueError("Unexpected local SDK tool reranker binding")
        if tool.class_name in LOCAL_RERANK_TOOL_CLASSES:
            tool.metadata = {"rerank_model": _reranker(reference, actor.tenant_id) if rerank_name else None}
        tools[name] = tool
    return tools
