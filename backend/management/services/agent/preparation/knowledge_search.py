# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare the authorized knowledge search descriptor for AgentOS evaluation."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos import (
    FileToolDescription,
    KnowledgeSearchBinding,
    KnowledgeSearchIndexBinding,
    ModelListQuery,
    RevisionedModelBinding,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, ValidationError
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.knowledge_base.permission import (
    resolve_knowledge_base_permissions,
)
from management.services.knowledge_base.tool_files import prepare_tool_files
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.rdb.knowledge_search_records import read_knowledge_search_records

logger = logging.getLogger(__name__)
PREPARATION_SECONDS = 10
_SEARCH_PARAMS = {"index_names", "top_k", "search_mode", "rerank", "rerank_model_name", "document_paths"}


def _model_binding(metadata):
    return RevisionedModelBinding(model_id=metadata.model_id, revision=metadata.revision)


def _prepare_scope(tool, user_id: str, tenant_id: str, document_paths, *, context: OperationContext):
    """Resolve a serializable descriptor without initializing a model or vector client."""
    if tool.class_name != "KnowledgeBaseSearchTool" or tool.source != "local":
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
            usage=tool.usage,
            native_documents=environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED,
            # Match the SDK constructor before the strict wire contract sees the value.
            top_k=max(1, min(int(params.get("top_k") or 3), 100)),
            **{name: params[name] for name in ("search_mode", "rerank", "rerank_model_name") if name in params},
        )
    except (ValueError, TypeError, OverflowError):
        return False

    context.remaining()
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
    if allowed and document_paths:
        binding.file_refs = prepare_tool_files(user_id, tenant_id, [ref.knowledge_id for ref in binding.allowed],
                                              document_paths, context=context)
    elif document_paths:
        binding.file_refs = []
    default_id = tenant_config_manager.get_app_config("RERANK_ID", tenant_id=tenant_id) if (
        allowed and binding.rerank and binding.rerank_model_name) else None
    return binding, by_index, allowed, names, default_id


async def prepare_knowledge_search(tool, user_id: str, tenant_id: str, document_paths) -> bool:
    """Assemble authorized resources using Runtime-owned model metadata only."""
    context = OperationContext("knowledge-tool-" + uuid4().hex, monotonic() + PREPARATION_SECONDS)
    try:
        async with asyncio.timeout(context.remaining()):
            scope = await run_blocking("prepare-knowledge-scope", _prepare_scope, tool, user_id, tenant_id, document_paths,
                                       context=context, lane="control-io", owner="management.knowledge_base")
            context.remaining()
            if not scope:
                return False
            binding, by_index, allowed, names, default_id = scope
            client = AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
            models = {}
            for name in allowed:
                model_id = by_index[name].get("embedding_model_id")
                if type(model_id) is not int or model_id <= 0:
                    raise ValidationError(f"No embedding model found for index '{name}'.")
                if model_id not in models:
                    models[model_id] = await client.get_model(model_id, user_id, tenant_id)
                model = models[model_id]
                if model.model_id != model_id or model.model_type not in {"embedding", "multi_embedding"}:
                    raise ValidationError(f"Invalid embedding model for index '{name}'.")
                binding.embedding_models[name] = _model_binding(model)
            if allowed and binding.rerank and binding.rerank_model_name:
                cursor, seen = None, set()
                while True:
                    page = await client.list_models(ModelListQuery(model_type="rerank", cursor=cursor), user_id, tenant_id)
                    selected = next((model for model in page.models if model.qualified_name == binding.rerank_model_name), None)
                    if selected is not None:
                        binding.reranker = _model_binding(selected)
                        break
                    if page.next_cursor is None:
                        break
                    if page.next_cursor in seen:
                        raise ValidationError("Invalid model catalog cursor")
                    seen.add(page.next_cursor)
                    cursor = page.next_cursor
                if binding.reranker is None and default_id not in (None, ""):
                    try:
                        model_id = int(default_id)
                    except (ValueError, TypeError) as error:
                        raise ValidationError("Invalid default rerank model") from error
                    default = await client.get_model(model_id, user_id, tenant_id)
                    if default.model_type == "rerank":
                        binding.default_reranker = _model_binding(default)

            tool.params = {**(tool.params or {}), "index_names": binding.index_names}
            tool.metadata = {
                "prepared_knowledge_search": binding.model_dump(mode="json"),
                "allowed_index_names": allowed,
                "index_name_to_display_map": names,
            }
            return True
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning("knowledge_prepare_timeout phase=resources threshold_seconds=%s exception_type=%s",
                       PREPARATION_SECONDS, type(error).__name__)
        raise RuntimeServiceTimeoutError("Knowledge resource preparation timed out") from error
