# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Infer the complete text batch before appending independently keyed records."""

import asyncio
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
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
)
from nexent.storage.models import OperationContext
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_creation import ChunkCreationExecutor
from runtime.knowledge_base.ingestion import embedding_vectors

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.rdb.document_embedding_batch import read_document_embedding_batch

logger = logging.getLogger(__name__)


class KnowledgeDocumentAppender:
    def __init__(self, mutations):
        self.mutations = mutations

    async def append(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeDocumentsAppend):
            raise InvalidInput()
        request = KnowledgeDocumentsAppend.model_validate(request.model_dump(mode="json"))
        context = context or OperationContext("knowledge-document-append-" + uuid4().hex,
                                              time.monotonic() + self.mutations.operation_seconds)
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
                prepared, vectors = [], []
                now = int(time.time())
                for document in request.documents:
                    source = dict(document.metadata)
                    source.pop("content", None)
                    source.pop("embedding", None)
                    if not source.get("id"):
                        source["id"] = f"{now}_{hash(document.content)}"[:20]
                    prepared.append(source)
                for offset in range(0, len(request.documents), embedding_batch_size):
                    documents = request.documents[offset:offset + embedding_batch_size]
                    result = await self.mutations.models.invoke(EmbeddingInvocation(
                        model_id=binding.model_id, expected_revision=binding.revision,
                        input=[document.content for document in documents]), actor)
                    if normalize_model_revision(result.revision) != normalize_model_revision(binding.revision):
                        raise Conflict()
                    vectors.extend(embedding_vectors(result.output, len(documents), dimensions))

                async def authorized():
                    if await self.mutations._grant(probe, actor) != grant:
                        raise Conflict()

                await authorized()
                namespace = {} if grant.resource_tenant_id == actor.tenant_id else {"resource_tenant_id": grant.resource_tenant_id}
                with self.mutations.records(actor, context=context, **namespace) as records:
                    journal = ChunkMutationAdmission(records, request.knowledge_id)
                    executor = ChunkCreationExecutor(journal, self.mutations.models, actor, grant.collection,
                                                     ports=self.mutations.creation_ports)
                    keys = []
                    for index, (document, source, vector) in enumerate(zip(request.documents, prepared, vectors, strict=True)):
                        key = "document-" + uuid4().hex
                        intent = ChunkMutationIntent(knowledge_id=request.knowledge_id, chunk_id=key, operation="create",
                            request_key=f"{batch}:{index}", resource_revision=grant.revision,
                            changes={"content": document.content, "filename": source.get("filename") if isinstance(source.get("filename"), str) else None,
                                     "location": {PUBLIC_CHUNK_SOURCE_KEY: source}, "supplied_embedding": list(vector),
                                     "embedding_model": binding.model_dump(), "embedding_input": ""})
                        state = await executor.execute(intent, context=context, authorize=authorized)
                        if state["status"] != "completed" or not state["writer_ended"]:
                            raise OutcomeUnknown(operation_id=context.operation_id)
                        if state["count_delta"] != 1:
                            raise Conflict()
                        keys.append(key)
                context.remaining()
                return KnowledgeDocumentsAppended(knowledge_id=request.knowledge_id, total_submitted=len(request.documents),
                                                  total_indexed=len(keys), chunk_ids=keys)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning("knowledge_document_append_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
