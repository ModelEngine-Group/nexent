# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rebuild signed SDK tool instances without accepting connection parameters."""

import logging
from hmac import compare_digest

from fastapi import HTTPException

from contracts.agentos import AgentResource, SkillDerivedLocalToolBinding, StoredLocalToolBinding
from contracts.constants import environment
from contracts.errors.exceptions import ValidationError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.ind_aidp_images import create_ind_aidp_image_url_builder
from infrastructure.local_tool_execution import (
    LOCAL_RERANK_TOOL_CLASSES, LOCAL_SDK_TOOL_CLASSES, build_local_tool, local_tool_rerank_name, local_tool_revision,
)
from infrastructure.rdb.local_tool_records import read_bound_local_tools, read_skill_derived_local_tools
from infrastructure.shared_aidp_tool import restrict_aidp_access
from nexent.core.agents.agent_model import ToolConfig
from runtime.agentos.prepared_knowledge import _reranker


logger = logging.getLogger(__name__)


def _aidp_access_metadata(tool: ToolConfig, actor: ServicePrincipal) -> dict:
    from ext_components.aidp.services.aidp_access_service import resolve_current_aidp_access

    params = tool.params
    try:
        snapshot = resolve_current_aidp_access(
            server_url=params["server_url"], api_key=params["api_key"], user_id=actor.user_id,
            tenant_id=actor.tenant_id, aidp_tenant_id=params["tenant_id"],
        )
    except Exception as exc:
        logger.warning("AIDP access snapshot lookup failed (%s)", type(exc).__name__)
        snapshot = None
    return restrict_aidp_access(params["kds_list"], snapshot)


def materialize_local_tools(resource: AgentResource, actor: ServicePrincipal, language: str) -> dict[str, ToolConfig]:
    references = {}
    schemas = {"1": StoredLocalToolBinding, "2": SkillDerivedLocalToolBinding}
    for binding in resource.tools:
        if binding.tool_id not in LOCAL_SDK_TOOL_CLASSES:
            continue
        if binding.version not in schemas or binding.credential_ref is not None or binding.tool_id in references:
            raise ValueError("Unsupported local SDK tool binding")
        if binding.tool_id == "ind_aidp_search" and binding.version != "1":
            raise ValueError("Independent AIDP image proxy requires an explicit tool instance")
        references[binding.tool_id] = schemas[binding.version].model_validate(binding.parameters)
    if not references:
        return {}

    scope = (resource.agent_id, resource.version_no, actor.tenant_id)
    direct_names = [name for name, ref in references.items() if isinstance(ref, StoredLocalToolBinding)]
    derived_names = [name for name, ref in references.items() if isinstance(ref, SkillDerivedLocalToolBinding)]
    direct = read_bound_local_tools(*scope, direct_names) if direct_names else []
    try:
        derived = read_skill_derived_local_tools(*scope, derived_names) if derived_names else []
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH"}) from exc
    by_instance = {(row["tool_instance_id"], row["name"]): row for row in direct}
    by_tool = {(row["tool_id"], row["name"]): row for row in derived}
    skill_ids = {ref.instance_id for ref in resource.skill_refs} if derived_names else set()
    tools = {}
    for name, reference in references.items():
        if isinstance(reference, StoredLocalToolBinding):
            row = by_instance.get((reference.instance_id, name))
        else:
            row = by_tool.get((reference.tool_id, name))
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_LOCAL_TOOL_NOT_FOUND"})
        if isinstance(reference, SkillDerivedLocalToolBinding) and not set(row["skill_instance_ids"]) <= skill_ids:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH"})
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
        elif name == "ind_aidp_search":
            tool.metadata = {"image_url_builder": create_ind_aidp_image_url_builder(
                agent_id=resource.agent_id, version_no=resource.version_no, tenant_id=actor.tenant_id,
                tool_id=row["tool_id"], aidp_tenant_id=tool.params.get("tenant_id") or "aidp",
            )}
        elif name == "aidp_search":
            tool.params.update(
                server_url=environment.AIDP_SERVER_URL, api_key=environment.AIDP_API_KEY, tenant_id=environment.AIDP_TENANT_ID,
            )
            tool.metadata = _aidp_access_metadata(tool, actor)
        tools[name] = tool
    return tools
