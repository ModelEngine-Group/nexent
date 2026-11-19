# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-owned manual creation, model invocation and conditional storage under one admission."""

import asyncio
import logging
import math
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos import EmbeddingInvocation, ModelMetadata, ModelReference
from contracts.agentos_knowledge import ModelVersion
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_mutation import ChunkCreateData, ChunkMutationIntent
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    OperationContext,
    Revision,
    VectorKey,
    VectorRecord,
    WriteOutcome,
    WriteReceipt,
)
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_executor import (
    explicit_chunk_vector,
    record_mutation_failure,
    require_chunk_identity,
    require_chunk_scope,
)

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_chunk_mutations import knowledge_creation_vector_ports

logger = logging.getLogger(__name__)


class _Cancellation:
    def __init__(self, parent):
        self.parent, self.local = parent, Event()

    def is_set(self):
        return self.local.is_set() or self.parent is not None and self.parent.is_set()


class ChunkCreationExecutor:
    def __init__(
        self,
        journal,
        models,
        actor,
        collection,
        *,
        ports=knowledge_creation_vector_ports,
        operation_seconds=180,
    ):
        if (
            not isinstance(journal, ChunkMutationAdmission)
            or type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 180
        ):
            raise InvalidInput()
        if (
            actor.user_id != journal.records.scope.actor_id
            or journal.records.scope.tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}
        ):
            raise ScopeDenied()
        self.journal, self.models, self.actor, self.collection = (
            journal,
            models,
            actor,
            collection,
        )
        self.ports, self.operation_seconds = ports, operation_seconds
        self.namespace = {} if journal.records.scope.tenant_id == actor.tenant_id else {
            "resource_tenant_id": journal.records.scope.tenant_id
        }

    async def _blocking(self, action, *args, context):
        def execute():
            context.remaining()
            result = action(*args, context=context)
            context.remaining()
            return result

        return await run_blocking(
            "knowledge-chunk-create",
            execute,
            lane="control-io",
            owner="runtime.knowledge_base",
        )

    def _existing(self, intent, *, context):
        with self.ports(self.actor, self.collection, None, context=context, **self.namespace) as vectors:
            require_chunk_scope(self.journal, vectors, self.collection)
            row = vectors.get(
                VectorKey(self.collection, intent.chunk_id),
                include_vector=False,
                context=context,
            )
            if row is not None:
                require_chunk_identity(row, intent, self.collection)
                if row.generation is None:
                    raise Conflict()
            return row

    @staticmethod
    def _supplied(data, binding):
        values = data.supplied_embedding
        if values is None:
            return None, (), None, False
        vector = explicit_chunk_vector(values)
        return len(vector), vector, binding if isinstance(binding, ModelVersion) else None, False

    async def _embedding(self, data, *, context):
        text = data.content if data.embedding_input is None else data.embedding_input
        binding = data.embedding_model
        if data.embedding_model is None or not text:
            return self._supplied(data, binding)
        try:
            async with asyncio.timeout(context.remaining()):
                if isinstance(binding, ModelReference):
                    metadata = await self.models.get(binding.model_id, self.actor)
                    if (not isinstance(metadata, ModelMetadata) or metadata.model_id != binding.model_id
                        or metadata.model_type not in {"embedding", "multi_embedding"}):
                        raise ValueError("Invalid embedding model metadata")
                    binding = ModelVersion(model_id=metadata.model_id, revision=metadata.revision)
                dimensions = await self.models.embedding_dimensions(
                    binding, self.actor
                )
                result = await self.models.invoke(
                    EmbeddingInvocation(
                        model_id=binding.model_id,
                        expected_revision=binding.revision,
                        input=[text],
                    ),
                    self.actor,
                )
            output = result.output
            if (
                normalize_model_revision(result.revision)
                != normalize_model_revision(binding.revision)
                or not isinstance(output, list)
                or len(output) != 1
                or not isinstance(output[0], list)
                or not output[0]
                or any(
                    type(value) not in {int, float} or not math.isfinite(value)
                    for value in output[0]
                )
            ):
                raise ValueError("Invalid embedding response")
            if type(dimensions) is not int or dimensions <= 0:
                raise ValueError("Missing embedding dimensions")
            return dimensions, tuple(output[0]), binding, True
        except Exception as error:  # noqa: BLE001 - Existing manual creation saves plaintext after model failures.
            context.remaining()
            # This is the existing manual-create behavior; resource checks stay outside this branch.
            logger.warning(
                "knowledge_chunk_create_embedding_failed operation_id=%s phase=model exception_type=%s",
                context.operation_id,
                type(error).__name__,
            )
        return self._supplied(data, binding)

    def _write(self, intent, data, admitted, previous, dimensions, vector, binding, generated, *, context):
        key = admitted["mutation_id"]
        with self.ports(
            self.actor, self.collection, dimensions, context=context, **self.namespace
        ) as vectors:
            try:
                require_chunk_scope(self.journal, vectors, self.collection)
                self.journal.revalidate(intent, context=context)
                current = vectors.get(
                    VectorKey(self.collection, intent.chunk_id),
                    include_vector=False,
                    context=context,
                )
                if (current is None) != (previous is None):
                    raise Conflict()
                if current is not None:
                    require_chunk_identity(current, intent, self.collection)
                    if current.generation != previous.generation:
                        raise Conflict()
            except Exception:
                record_mutation_failure(
                    self.journal, key, unknown=False, context=context
                )
                raise
            state, started = self.journal.begin(key, context=context)
            if not started:
                return state
            try:
                vectors.ensure_collection(self.collection, context=context)
                location = data.location
                if generated and PUBLIC_CHUNK_SOURCE_KEY in location:
                    location = {**location, PUBLIC_CHUNK_SOURCE_KEY: {
                        **location[PUBLIC_CHUNK_SOURCE_KEY], "embedding_model_id": binding.model_id}}
                ref = intent.file_ref
                record = VectorRecord(
                    VectorKey(self.collection, intent.chunk_id),
                    vector,
                    {
                        "knowledge_id": intent.knowledge_id,
                        "file_id": ref.file_id if ref else None,
                        "file_version": ref.file_version if ref else None,
                        "chunk_index": intent.chunk_index,
                        "embedding_model_id": binding.model_id if binding else None,
                        "embedding_revision": binding.revision if binding else None,
                        "parser_version": None,
                        "content": data.content,
                        "filename": data.filename,
                        "location": location,
                    },
                    Revision(intent.generation if ref else key),
                )
                receipt = vectors.put(
                    record,
                    expected_generation=previous.generation if previous else None,
                    context=context,
                )
                if (
                    not isinstance(receipt, WriteReceipt)
                    or not isinstance(receipt.outcome, WriteOutcome)
                    or receipt.outcome is WriteOutcome.UNKNOWN
                    or type(receipt.matched) is not bool
                ):
                    raise OutcomeUnknown()
                if receipt.outcome is WriteOutcome.FAILED or not receipt.matched:
                    raise Conflict()
            except (
                Conflict,
                InvalidInput,
                ScopeDenied,
                NotFound,
                CapabilityUnsupported,
            ):
                record_mutation_failure(
                    self.journal, key, unknown=False, context=context
                )
                raise
            except Exception:
                record_mutation_failure(
                    self.journal, key, unknown=True, context=context
                )
                raise
            return self.journal.complete(
                key,
                count_delta=0 if previous else 1,
                outcome=WriteOutcome.CONFIRMED,
                context=context,
            )

    async def execute(self, intent, *, context=None, authorize=None):
        if not isinstance(intent, ChunkMutationIntent) or intent.operation != "create":
            raise InvalidInput()
        intent = ChunkMutationIntent.model_validate(intent.model_dump(mode="json"))
        data = ChunkCreateData.model_validate(intent.changes)
        context = context or OperationContext(
            "knowledge-chunk-create-" + uuid4().hex,
            monotonic() + self.operation_seconds,
        )
        cancellation = _Cancellation(context.cancelled)
        context = replace(context, cancelled=cancellation)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                admitted, fresh = await self._blocking(
                    self.journal.reserve, intent, context=context
                )
                if not fresh:
                    return admitted
                try:
                    previous = await self._blocking(
                        self._existing, intent, context=context
                    )
                    embedding = await self._embedding(data, context=context)
                    if authorize is not None:
                        await authorize()
                        context.remaining()
                except Exception:
                    await run_blocking(
                        "knowledge-chunk-create-rejected",
                        record_mutation_failure,
                        self.journal,
                        admitted["mutation_id"],
                        unknown=False,
                        context=context,
                        lane="control-io",
                        owner="runtime.knowledge_base",
                    )
                    raise
                return await self._blocking(
                    self._write,
                    intent,
                    data,
                    admitted,
                    previous,
                    *embedding,
                    context=context,
                )
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning(
                "knowledge_chunk_create_timeout operation_id=%s phase=create threshold_seconds=%s exception_type=%s",
                context.operation_id,
                threshold,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancellation.local.set()
