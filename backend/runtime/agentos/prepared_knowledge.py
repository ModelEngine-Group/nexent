# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the prepared knowledge-search scope and build Runtime's SDK tool."""

import logging

from fastapi import HTTPException

from contracts.agentos import KnowledgeSearchBinding
from contracts.constants import environment
from infrastructure.agent_model_config import model_record_revision, normalize_model_revision
from infrastructure.knowledge_search import embedding_adapter_spec, knowledge_search_revision
from infrastructure.model_adapter import build_adapter_fresh
from infrastructure.rdb.knowledge_search_records import read_knowledge_search_actor, read_knowledge_search_records
from infrastructure.rdb.model_records import get_model_by_model_id
from infrastructure.vdb.client import create_elasticsearch_core
from nexent.core.agents.agent_model import ToolConfig
from permissions.dac import resolve_knowledge_permissions

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


def _authorize_indexes(binding, actor):
    names = [reference.index_name for reference in binding.allowed]
    if (len(set(names)) != len(names) or not set(names) <= set(binding.index_names)
            or not set(binding.display_name_to_index.values()) <= set(binding.index_names)):
        raise ValueError("Knowledge search scope does not match configured indexes")
    if not names:
        if binding.embedding or binding.reranker or binding.default_reranker:
            raise ValueError("An empty knowledge scope cannot bind models")
        return []
    if binding.embedding is None or ((binding.reranker or binding.default_reranker)
                                    and not (binding.rerank and binding.rerank_model_name)):
        raise ValueError("Knowledge search model bindings do not match the tool settings")

    rows = read_knowledge_search_records(actor.tenant_id, names)
    by_name = {row["index_name"]: row for row in rows}
    if len(rows) != len(by_name) or any(
        ref.index_name not in by_name or by_name[ref.index_name]["knowledge_id"] != ref.knowledge_id
        for ref in binding.allowed
    ):
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_KNOWLEDGE_NOT_FOUND"})

    membership, groups = read_knowledge_search_actor(actor.user_id)
    if membership and membership.get("tenant_id") not in {None, "", actor.tenant_id}:
        raise HTTPException(status_code=403, detail={"code": "AGENTOS_KNOWLEDGE_FORBIDDEN"})
    permissions = resolve_knowledge_permissions(
        rows, actor.user_id, actor.tenant_id, membership, groups, speed_mode=environment.IS_SPEED_MODE,
    )
    if any(permissions.get(name) is None for name in names):
        raise HTTPException(status_code=403, detail={"code": "AGENTOS_KNOWLEDGE_FORBIDDEN"})
    first = by_name[names[0]]
    if (first["tenant_id"] != actor.tenant_id or first.get("embedding_model_id") != binding.embedding.model_id
            or any(knowledge_search_revision(by_name[ref.index_name]) != ref.revision for ref in binding.allowed)):
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_KNOWLEDGE_REVISION_MISMATCH"})
    return names


def materialize_knowledge_search(bindings, actor):
    if not bindings:
        return {}
    if len(bindings) != 1 or bindings[0].version != "1" or bindings[0].credential_ref is not None:
        raise ValueError("Unsupported knowledge search tool binding")
    binding = KnowledgeSearchBinding.model_validate(bindings[0].parameters)
    allowed = _authorize_indexes(binding, actor)
    embedding = _load_model(binding.embedding, actor.tenant_id, {"embedding", "multi_embedding"})
    adapter = None
    if embedding is not None:
        config, modality, slot = embedding_adapter_spec(embedding)
        adapter = build_adapter_fresh(config, modality, slot, None)
    tool = ToolConfig(
        class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local", usage=binding.usage,
        **binding.description.model_dump(),
        params=binding.model_dump(include={"index_names", "top_k", "search_mode", "rerank", "rerank_model_name"}),
        metadata={
            "allowed_index_names": allowed,
            "document_paths": binding.document_paths,
            "display_name_to_index_map": binding.display_name_to_index,
            "embedding_model": adapter,
            "rerank_model": _reranker(binding, actor.tenant_id),
            "vdb_core": create_elasticsearch_core(host=environment.ES_HOST, api_key=environment.ES_API_KEY) if allowed else None,
        },
    )
    return {tool.name: tool}
