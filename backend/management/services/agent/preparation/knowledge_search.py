# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare the authorized knowledge search descriptor for AgentOS evaluation."""

import logging

from contracts.agentos import FileToolDescription, KnowledgeSearchBinding, KnowledgeSearchIndexBinding, RevisionedModelBinding
from contracts.errors.exceptions import ValidationError
from infrastructure.agent_model_config import model_record_revision
from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.rdb.knowledge_search_records import read_knowledge_search_records
from infrastructure.rdb.model_records import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.knowledge_base.permission import resolve_knowledge_base_permissions
from management.services.model.resolver import find_named_rerank_record

logger = logging.getLogger(__name__)
_SEARCH_PARAMS = {"index_names", "top_k", "search_mode", "rerank", "rerank_model_name", "document_paths"}


def _model_binding(record):
    if not record:
        return None
    return RevisionedModelBinding(model_id=record["model_id"], revision=model_record_revision(record))


def _rerank_bindings(tenant_id, model_name):
    try:
        selected = find_named_rerank_record(tenant_id, model_name)
    except Exception:
        logger.warning("Unable to resolve named rerank model for evaluation", exc_info=True)
        selected = None
    default = tenant_config_manager.get_model_config("RERANK_ID", tenant_id=tenant_id)
    if default.get("model_type") != "rerank":
        default = None
    return _model_binding(selected), _model_binding(default)


def prepare_knowledge_search(tool, user_id: str, tenant_id: str, document_paths) -> bool:
    """Resolve a serializable descriptor without initializing a model or vector client."""
    if tool.name != "knowledge_base_search" or tool.source != "local":
        return False
    params = tool.params or {}
    if set(params) - _SEARCH_PARAMS:
        return False
    try:
        binding = KnowledgeSearchBinding(
            description=FileToolDescription(**{
                name: getattr(tool, name) for name in FileToolDescription.model_fields
            }),
            index_names=params.get("index_names") or [],
            allowed=[],
            display_name_to_index={},
            document_paths=document_paths,
            usage=tool.usage,
            # Match the SDK constructor before the strict wire contract sees the value.
            top_k=max(1, min(int(params.get("top_k") or 3), 100)),
            **{name: params[name] for name in ("search_mode", "rerank", "rerank_model_name") if name in params},
        )
    except (ValueError, TypeError, OverflowError):
        return False

    rows = read_knowledge_search_records(tenant_id, binding.index_names)
    by_index = {row["index_name"]: row for row in rows}
    if len(rows) != len(by_index):
        return False
    decisions = resolve_knowledge_base_permissions(rows, user_id, tenant_id)
    allowed = [name for name in dict.fromkeys(binding.index_names) if decisions.get(name) is not None]
    names = {
        name: (by_index[name]["knowledge_name"] or name)
        if name in by_index and by_index[name]["tenant_id"] == tenant_id else name
        for name in binding.index_names
    }
    binding.allowed = [
        KnowledgeSearchIndexBinding(
            knowledge_id=by_index[name]["knowledge_id"], index_name=name,
            revision=knowledge_search_revision(by_index[name]),
        ) for name in allowed
    ]
    binding.display_name_to_index = {display: name for name, display in names.items()}
    if allowed:
        first = by_index[allowed[0]]
        model_id = first.get("embedding_model_id")
        model = get_model_by_model_id(model_id, tenant_id) if model_id and first["tenant_id"] == tenant_id else None
        if not model or model.get("model_type") not in {"embedding", "multi_embedding"}:
            raise ValidationError(
                f"No embedding model found for index '{allowed[0]}'. Please configure an embedding model for this knowledge base."
            )
        binding.embedding = _model_binding(model)
        if binding.rerank and binding.rerank_model_name:
            binding.reranker, binding.default_reranker = _rerank_bindings(tenant_id, binding.rerank_model_name)

    tool.params = {**params, "index_names": binding.index_names}
    tool.metadata = {
        "prepared_knowledge_search": binding.model_dump(mode="json"),
        "allowed_index_names": allowed,
        "index_name_to_display_map": names,
    }
    return True
