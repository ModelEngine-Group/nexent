# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime's tenant-scoped model lookup and invocation."""

from datetime import datetime

from fastapi.encoders import jsonable_encoder

from contracts.agentos import (
    ChatInvocation,
    EmbeddingInvocation,
    ModelInvocation,
    ModelMetadata,
    ModelResult,
)
from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.concurrency import run_blocking
from nexent.core.gateway.modality.embedding.embedding_adapter import EmbeddingRequest
from nexent.core.gateway.modality.llm.llm_adapter import LLMRequest
from nexent.core.gateway.modality.rerank.rerank_adapter import RerankRequest
from nexent.monitor import set_monitoring_context, set_monitoring_operation


class ModelAccessError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


_MODEL_TYPES = {
    "chat": {"llm", "chat"},
    "embedding": {"embedding", "multi_embedding"},
    "rerank": {"rerank"},
}


class ModelService:
    def __init__(self, load_record, build_adapter):
        self.load_record = load_record
        self.build_adapter = build_adapter

    async def _load(self, model_id: int, actor: ServicePrincipal) -> tuple[dict, ModelMetadata]:
        record = await run_blocking(
            "agentos-model-lookup",
            self.load_record,
            model_id,
            actor.tenant_id,
            lane="control-io",
            owner="runtime.model",
        )
        if not record or record.get("tenant_id") != actor.tenant_id or record.get("delete_flag") != "N":
            raise ModelAccessError(404, "MODEL_NOT_FOUND")
        revision = record.get("update_time") or record.get("create_time")
        if isinstance(revision, datetime):
            revision = revision.isoformat()
        return record, ModelMetadata(
            model_id=model_id,
            model_type=record.get("model_type") or "",
            display_name=record.get("display_name"),
            revision=revision or "legacy",
            profile_version=record.get("capability_profile_version"),
        )

    async def get(self, model_id: int, actor: ServicePrincipal) -> ModelMetadata:
        _, metadata = await self._load(model_id, actor)
        return metadata

    async def invoke(self, payload: ModelInvocation, actor: ServicePrincipal) -> ModelResult:
        record, metadata = await self._load(payload.model_id, actor)
        if payload.expected_revision is not None and (
            normalize_model_revision(payload.expected_revision) != normalize_model_revision(metadata.revision)
        ):
            raise ModelAccessError(409, "MODEL_REVISION_MISMATCH")
        if metadata.model_type not in _MODEL_TYPES[payload.operation]:
            raise ModelAccessError(422, "MODEL_OPERATION_UNSUPPORTED")

        set_monitoring_context(user_id=actor.user_id, tenant_id=actor.tenant_id)
        set_monitoring_operation(f"agentos_model_{payload.operation}", display_name=metadata.display_name)
        if isinstance(payload, ChatInvocation):
            options = payload.options.model_dump(exclude_none=True) if payload.options else {}
            adapter = self.build_adapter(record, "llm", "llm", actor.tenant_id, stream=False, **options)
            output = await adapter.invoke(LLMRequest([message.model_dump() for message in payload.input]))
            output = {"content": output.content}
        elif isinstance(payload, EmbeddingInvocation):
            modality = metadata.model_type
            slot = "multiEmbedding" if modality == "multi_embedding" else "embedding"
            adapter = self.build_adapter(record, modality, slot, actor.tenant_id)
            output = await adapter.invoke(EmbeddingRequest(payload.input, worker_lane="model-embedding"))
        else:
            adapter = self.build_adapter(record, "rerank", "rerank", actor.tenant_id)
            options = payload.options
            output = await adapter.invoke(
                RerankRequest(payload.input.query, payload.input.documents, options.top_n if options else None)
            )
        return ModelResult(revision=metadata.revision, output=jsonable_encoder(output))
