# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the prepared knowledge-search scope and build Runtime's SDK tool."""

import asyncio
import logging

from contracts.agentos import KNOWLEDGE_TOOL_BINDING_PREFIX, KnowledgeSearchBinding
from contracts.agentos_knowledge import (
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeUpstreamError
from fastapi import HTTPException
from nexent.core.agents.contracts.config import ToolConfig
from runtime.knowledge_base.composition import default_service
from runtime.knowledge_base.sdk_tool import RuntimeKnowledgeTool
from runtime.knowledge_base.search import KnowledgeSearchService
from runtime.knowledge_base.tool_search import KnowledgeToolSearch
from runtime.knowledge_images import KnowledgeImageFilter

from infrastructure.agent_model_config import (
    model_record_revision,
    normalize_model_revision,
)
from infrastructure.model_adapter import build_adapter_fresh
from infrastructure.rdb.model_records import get_model_by_model_id

logger = logging.getLogger(__name__)


def _load_model(reference, tenant_id, modalities):
    if reference is None:
        return None
    record = get_model_by_model_id(reference.model_id, tenant_id)
    if not record or record.get("tenant_id") != tenant_id or record.get("delete_flag") != "N":
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_KNOWLEDGE_MODEL_NOT_FOUND"})
    if record["model_type"] not in modalities or model_record_revision(record) != normalize_model_revision(reference.revision):
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_KNOWLEDGE_MODEL_REVISION_MISMATCH"})
    return record


def _reranker(binding, tenant_id):
    selected = _load_model(binding.reranker, tenant_id, {"rerank"})
    if selected is not None:
        try:
            return build_adapter_fresh(selected, "rerank", "rerank", tenant_id)
        except Exception:
            logger.warning("Unable to initialize the named evaluation reranker", exc_info=True)
    default = _load_model(binding.default_reranker, tenant_id, {"rerank"})
    return build_adapter_fresh(default, "rerank", "rerank", tenant_id) if default is not None else None


def _current_grant(binding, actor, client):
    """Preparation runs on a managed worker; the AgentOS client bounds and closes HTTP."""
    return asyncio.run(client.authorize_knowledge_search(
        KnowledgeSearchAuthorization(knowledge_ids=[ref.knowledge_id for ref in binding.allowed]),
        actor.user_id, actor.tenant_id))


def _authorize_binding(binding, actor, client):
    names = [reference.index_name for reference in binding.allowed]
    if (len(set(names)) != len(names) or not set(names) <= set(binding.index_names)
            or not set(binding.display_name_to_index.values()) <= set(binding.index_names)):
        raise ValueError("Knowledge search scope does not match configured indexes")
    if binding.file_refs is not None and any(ref.knowledge_id not in {kb.knowledge_id for kb in binding.allowed}
                                             for ref in binding.file_refs):
        raise ValueError("Knowledge files exceed the authorized scope")
    if not names:
        if binding.embedding_models or binding.reranker or binding.default_reranker:
            raise ValueError("An empty knowledge scope cannot bind models")
        return None
    if set(binding.embedding_models) != set(names) or ((binding.reranker or binding.default_reranker)
                                                     and not (binding.rerank and binding.rerank_model_name)):
        raise ValueError("Knowledge search model bindings do not match the tool settings")
    try:
        grant = _current_grant(binding, actor, client)
    except RuntimeUpstreamError as error:
        if error.status_code in {403, 404}:
            raise HTTPException(status_code=error.status_code, detail={"code": (
                "AGENTOS_KNOWLEDGE_FORBIDDEN" if error.status_code == 403 else "AGENTOS_KNOWLEDGE_NOT_FOUND")}) from error
        raise
    if (any(g.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID} for g in grant.knowledge_bases)
        or [(g.knowledge_id, g.collection) for g in grant.knowledge_bases] != [
        (ref.knowledge_id, ref.index_name) for ref in binding.allowed
    ]):
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_KNOWLEDGE_NOT_FOUND"})
    if any(g.revision != ref.revision or g.embedding_model_id != binding.embedding_models[ref.index_name].model_id
           for ref, g in zip(binding.allowed, grant.knowledge_bases, strict=True)):
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_KNOWLEDGE_REVISION_MISMATCH"})
    return grant


def materialize_knowledge_search(bindings, actor):
    prepared = []
    seen = set()
    for reference in bindings:
        if reference.version != "2" or reference.credential_ref is not None or reference.tool_id in seen:
            raise ValueError("Unsupported knowledge search tool binding")
        if reference.tool_id == "knowledge_base_search":
            catalog_name = reference.tool_id
        elif reference.tool_id.startswith(KNOWLEDGE_TOOL_BINDING_PREFIX):
            catalog_name = reference.tool_id.removeprefix(KNOWLEDGE_TOOL_BINDING_PREFIX)
            if not catalog_name:
                raise ValueError("A knowledge binding requires its catalog name")
        else:
            raise ValueError("Unsupported knowledge search tool binding")
        seen.add(reference.tool_id)
        prepared.append((reference.tool_id, catalog_name, KnowledgeSearchBinding.model_validate(reference.parameters)))
    return {
        tool_id: _materialize_knowledge_search_tool(binding, actor, catalog_name)
        for tool_id, catalog_name, binding in prepared
    }


def _materialize_knowledge_search_tool(binding, actor, catalog_name):
    service = default_service()
    grant = _authorize_binding(binding, actor, service.client)
    allowed = [resource.collection for resource in grant.knowledge_bases] if grant is not None else []
    for ref in binding.embedding_models.values():
        _load_model(ref, actor.tenant_id, {"embedding", "multi_embedding"})
    reranker = binding.reranker or binding.default_reranker
    if reranker is not None:
        _load_model(reranker, actor.tenant_id, {"rerank"})
    resources = [(resource, ModelVersion(**binding.embedding_models[resource.collection].model_dump()))
                 for resource in grant.knowledge_bases] if grant is not None else []
    backend = KnowledgeToolSearch(KnowledgeSearchService(service.client, service.models), actor, resources,
                                  file_refs=binding.file_refs)
    return ToolConfig(
        class_name="KnowledgeBaseSearchTool", name=catalog_name, source="local", usage=binding.usage,
        **binding.description.model_dump(),
        params=binding.model_dump(include={"index_names", "top_k", "search_mode"}),
        metadata={
            "image_filterer": KnowledgeImageFilter(actor, service.client),
            "allowed_index_names": allowed,
            "display_name_to_index_map": binding.display_name_to_index,
            "knowledge_searcher": RuntimeKnowledgeTool(backend, rerank_model=(
                ModelVersion(**reranker.model_dump()) if reranker is not None else None)),
        },
    )
