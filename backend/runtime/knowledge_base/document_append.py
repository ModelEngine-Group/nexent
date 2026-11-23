# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Infer complete authorized text/image batches before appending keyed records."""

import asyncio
import base64
import logging
import time
from uuid import uuid4

from contracts.agentos import EmbeddingInvocation, ModelMetadata
from contracts.agentos_knowledge import ModelVersion
from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from contracts.knowledge_documents import (
    KnowledgeDocumentsAppend,
    KnowledgeDocumentsAppended,
)
from nexent.core.concurrency import run_blocking
from nexent.core.gateway.modality.embedding.embedding_adapter import _detect_image_mime
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import OperationContext
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_creation import ChunkCreationExecutor
from runtime.knowledge_base.ingestion import embedding_vectors
from runtime.knowledge_base.worker import cancellable_context

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.file_processing.image_sources import read_pinned_object_image
from infrastructure.object_storage.read_access import validate_s3_url_access
from infrastructure.rdb.document_embedding_batch import read_document_embedding_batch
from infrastructure.vdb.native_knowledge import native_document_creation_ports

logger = logging.getLogger(__name__)


class KnowledgeDocumentAppender:
    def __init__(self, mutations):
        self.mutations = mutations

    async def _inputs(self, documents, model, actor, *, context):
        selected = []
        for document in documents:
            reference = document.image_ref
            if reference is not None:
                try:
                    validate_s3_url_access(reference.key, actor.user_id, actor.tenant_id)
                except PermissionError as error:
                    raise ScopeDenied() from error
            image = document.metadata.get("process_source") == "UniversalImageExtractor"
            if image:
                if model.model_type != "multi_embedding" or reference is None:
                    continue
                raw = await run_blocking("knowledge-document-image", read_pinned_object_image, reference,
                    user_id=actor.user_id, tenant_id=actor.tenant_id, context=context,
                    lane="control-io", owner="runtime.knowledge_base")
                context.remaining()
                if not raw:
                    continue
                value = f"data:{_detect_image_mime(raw)};base64," + base64.b64encode(raw).decode("ascii")
            else:
                value = document.content
            selected.append((document, value, image))
        return selected

    async def _vectors(self, inputs, binding, batch_size, dimensions, actor):
        vectors = [None] * len(inputs)
        for image in (False, True):
            selected = [(index, value) for index, (_, value, is_image) in enumerate(inputs) if is_image == image]
            for offset in range(0, len(selected), batch_size):
                group = selected[offset:offset + batch_size]
                result = await self.mutations.models.invoke(EmbeddingInvocation(
                    model_id=binding.model_id, expected_revision=binding.revision,
                    input=[value for _, value in group], input_type="image" if image else "text"), actor)
                if normalize_model_revision(result.revision) != normalize_model_revision(binding.revision):
                    raise Conflict()
                for (index, _), vector in zip(group, embedding_vectors(result.output, len(group), dimensions), strict=True):
                    vectors[index] = vector
        return vectors

    async def append(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeDocumentsAppend):
            raise InvalidInput()
        request = KnowledgeDocumentsAppend.model_validate(request.model_dump(mode="json"))
        context = context or OperationContext("knowledge-document-append-" + uuid4().hex,
                                              time.monotonic() + self.mutations.operation_seconds)
        context, cancelled = cancellable_context(context)
        threshold = context.remaining()
        batch = uuid4().hex
        probe = ChunkMutationIntent(knowledge_id=request.knowledge_id, chunk_id="documents-" + batch,
            operation="create", request_key=batch, resource_revision=request.resource_revision,
            changes={"content": "", "embedding_model": request.embedding_model.model_dump()})
        try:
            async with asyncio.timeout(threshold):
                grant = await self.mutations._grant(probe, actor)
                model = await self.mutations.models.get(request.embedding_model.model_id, actor)
                if (not isinstance(model, ModelMetadata) or model.model_id != request.embedding_model.model_id
                    or model.model_type not in {"embedding", "multi_embedding"}):
                    raise InvalidInput()
                if (isinstance(request.embedding_model, ModelVersion) and normalize_model_revision(model.revision)
                    != normalize_model_revision(request.embedding_model.revision)):
                    raise Conflict()
                binding = ModelVersion(model_id=model.model_id, revision=model.revision)
                dimensions = await self.mutations.models.embedding_dimensions(binding, actor)
                embedding_batch_size = request.embedding_batch_size
                if embedding_batch_size is None:
                    embedding_batch_size = await run_blocking("knowledge-document-embedding-batch",
                        read_document_embedding_batch, actor, grant.resource_tenant_id, model.model_type,
                        context=context, lane="control-io", owner="runtime.knowledge_base")
                inputs = await self._inputs(request.documents, model, actor, context=context)
                prepared = []
                now = int(time.time())
                for document, _, _ in inputs:
                    source = dict(document.metadata)
                    source.pop("content", None)
                    source.pop("embedding", None)
                    if not source.get("id"):
                        source["id"] = f"{now}_{hash(document.content)}"[:20]
                    prepared.append(source)
                vectors = await self._vectors(inputs, binding, embedding_batch_size, dimensions, actor)

                async def authorized():
                    if await self.mutations._grant(probe, actor) != grant:
                        raise Conflict()

                await authorized()
                if not inputs:
                    return KnowledgeDocumentsAppended(knowledge_id=request.knowledge_id,
                        total_submitted=len(request.documents), total_indexed=0,
                        total_skipped=len(request.documents), chunk_ids=[])
                namespace = {} if grant.resource_tenant_id == actor.tenant_id else {"resource_tenant_id": grant.resource_tenant_id}
                ports = self.mutations.creation_ports
                if request.native_documents:
                    def ports(principal, collection, dimensions, *, context, resource_tenant_id=None):
                        if collection != grant.collection or (resource_tenant_id or principal.tenant_id) != grant.resource_tenant_id:
                            raise ScopeDenied()
                        return native_document_creation_ports(principal, grant, dimensions, context=context)

                with self.mutations.records(actor, context=context, **namespace) as records:
                    journal = ChunkMutationAdmission(records, request.knowledge_id)
                    executor = ChunkCreationExecutor(journal, self.mutations.models, actor, grant.collection,
                                                     ports=ports)
                    keys = []
                    for index, ((document, _, is_image), source, vector) in enumerate(zip(inputs, prepared, vectors, strict=True)):
                        key = "document-" + uuid4().hex
                        intent = ChunkMutationIntent(knowledge_id=request.knowledge_id, chunk_id=key, operation="create",
                            native_documents=request.native_documents,
                            request_key=f"{batch}:{index}", resource_revision=grant.revision,
                            changes={"content": document.content, "filename": source.get("filename") if isinstance(source.get("filename"), str) else None,
                                     "location": {PUBLIC_CHUNK_SOURCE_KEY: source}, "supplied_embedding": list(vector),
                                     "embedding_model": binding.model_dump(), "embedding_input": ""})
                        state = await executor.execute(intent, context=context, authorize=authorized,
                                                       supplied_image=is_image)
                        if state["status"] != "completed" or not state["writer_ended"]:
                            raise OutcomeUnknown(operation_id=context.operation_id)
                        if state["count_delta"] != 1:
                            raise Conflict()
                        keys.append(key)
                context.remaining()
                return KnowledgeDocumentsAppended(knowledge_id=request.knowledge_id, total_submitted=len(request.documents),
                    total_indexed=len(keys), total_skipped=len(request.documents) - len(inputs), chunk_ids=keys)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning("knowledge_document_append_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
