# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute signed normalized chunk writes under current Management edit grants."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeChunksGrant
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_mutation import (
    ChunkCreateData,
    ChunkMutationAuthorization,
    ChunkMutationGrant,
    ChunkMutationIntent,
    ChunkMutationLookup,
    ChunkMutationState,
    ChunkMutationTarget,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext, VectorKey
from pydantic import ValidationError
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_creation import ChunkCreationExecutor
from runtime.knowledge_base.chunk_executor import ChunkMutationExecutor
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.knowledge_chunk_mutations import (
    knowledge_chunk_mutation_ports,
    knowledge_chunk_vector_ports,
    knowledge_creation_vector_ports,
)
from infrastructure.knowledge_runtime import knowledge_chunks_ports

logger = logging.getLogger(__name__)


class ChunkMutationService:
    def __init__(
        self,
        client,
        models,
        *,
        records=knowledge_chunk_mutation_ports,
        creation_ports=knowledge_creation_vector_ports,
        maintenance_ports=knowledge_chunk_vector_ports,
        lookup_ports=knowledge_chunks_ports,
        operation_seconds=180,
    ):
        if (
            type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 180
        ):
            raise InvalidInput()
        self.client, self.models, self.records = client, models, records
        self.creation_ports, self.maintenance_ports, self.operation_seconds = (
            creation_ports,
            maintenance_ports,
            operation_seconds,
        )
        self.lookup_ports = lookup_ports

    async def _grant(self, intent, actor):
        request = ChunkMutationAuthorization(
            **intent.model_dump(include={"knowledge_id", "chunk_id", "operation"})
        )
        grant = await self.client.authorize_knowledge_chunk_mutation(
            request, actor.user_id, actor.tenant_id
        )
        if (
            not isinstance(grant, ChunkMutationGrant)
            or grant.resource_tenant_id != actor.tenant_id
            or any(
                getattr(grant, field) != getattr(intent, field)
                for field in ("knowledge_id", "chunk_id", "operation")
            )
        ):
            raise ScopeDenied()
        if grant.revision != intent.resource_revision:
            raise Conflict()
        if isinstance(intent, ChunkMutationIntent) and intent.operation == "create":
            model = ChunkCreateData.model_validate(intent.changes).embedding_model
            if model is not None and model.model_id != grant.embedding_model_id:
                raise ScopeDenied()
        return grant

    @staticmethod
    def _visible_target(view, target, *, context):
        view.stable(context=context)
        if target.chunk is not None and target.chunk.file_id is not None:
            policy = KnowledgeJobs(view.records, authorize=lambda *args, **kwargs: None)
            if not policy.is_visible(target.chunk, target.generation, context=context):
                raise Conflict()

    @classmethod
    def _target(cls, records, vectors, payload, grant, actor, *, context):
        for scope in (records.scope, vectors.scope):
            if (
                scope.system
                or scope.resource_prefix
                or scope.service_role != "runtime"
                or scope.tenant_id != actor.tenant_id
                or scope.actor_id != actor.user_id
            ):
                raise ScopeDenied()
        view = ChunkReadView(records, payload.knowledge_id, context=context)
        row = vectors.get(
            VectorKey(grant.collection, payload.chunk_id),
            include_vector=False,
            context=context,
        )
        chunk, generation = None, None
        if row is not None:
            if row.key != VectorKey(grant.collection, payload.chunk_id):
                raise ScopeDenied()
            try:
                chunk = view._dto(row, grant)
            except ValidationError as error:
                raise Conflict() from error
            if row.generation is None or not view.allows_candidate(
                row, context=context
            ):
                raise Conflict()
            generation = row.generation.value
        target = ChunkMutationTarget(
            **payload.model_dump(),
            change_epoch=view.version,
            chunk=chunk,
            generation=generation,
        )
        cls._visible_target(view, target, context=context)
        return view, target

    async def lookup(self, payload, actor, *, context=None):
        if not isinstance(payload, ChunkMutationLookup):
            raise InvalidInput()
        payload = ChunkMutationLookup.model_validate(payload.model_dump(mode="json"))
        context = context or OperationContext(
            "knowledge-chunk-target-" + uuid4().hex,
            monotonic() + min(10, self.operation_seconds),
        )
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(payload, actor)
                resource = KnowledgeChunksGrant(
                    knowledge_id=grant.knowledge_id,
                    collection=grant.collection,
                    resource_tenant_id=grant.resource_tenant_id,
                    revision=grant.revision,
                )
                with self.lookup_ports(actor, resource, context=context) as (
                    records,
                    vectors,
                ):
                    view, target = await run_blocking(
                        "knowledge-chunk-target",
                        self._target,
                        records,
                        vectors,
                        payload,
                        grant,
                        actor,
                        context=context,
                        lane="control-io",
                        owner="runtime.knowledge_base",
                    )
                    if await self._grant(payload, actor) != grant:
                        raise Conflict()
                    await run_blocking(
                        "knowledge-chunk-target-check",
                        self._visible_target,
                        view,
                        target,
                        context=context,
                        lane="control-io",
                        owner="runtime.knowledge_base",
                    )
                return target
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning(
                "knowledge_chunk_target_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                context.operation_id,
                threshold,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error

    async def mutate(self, payload, actor, *, context=None):
        if not isinstance(payload, ChunkMutationIntent):
            raise InvalidInput()
        try:
            payload = ChunkMutationIntent.model_validate(
                payload.model_dump(mode="json")
            )
            if payload.operation == "create":
                ChunkCreateData.model_validate(payload.changes)
        except ValidationError as error:
            raise InvalidInput() from error
        context = context or OperationContext(
            "knowledge-chunk-write-" + uuid4().hex, monotonic() + self.operation_seconds
        )
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(payload, actor)
                with self.records(actor, context=context) as records:
                    journal = ChunkMutationAdmission(records, payload.knowledge_id)
                    scope = records.scope
                    if (
                        scope.tenant_id != actor.tenant_id
                        or scope.actor_id != actor.user_id
                    ):
                        raise ScopeDenied()
                    if payload.operation == "create":

                        async def authorize():
                            if await self._grant(payload, actor) != grant:
                                raise Conflict()

                        row = await ChunkCreationExecutor(
                            journal,
                            self.models,
                            actor,
                            grant.collection,
                            ports=self.creation_ports,
                        ).execute(payload, context=context, authorize=authorize)
                    else:

                        def execute():
                            context.remaining()
                            with self.maintenance_ports(
                                actor, grant.collection, context=context
                            ) as vectors:
                                result = ChunkMutationExecutor(
                                    journal, vectors, grant.collection
                                ).execute(payload, context=context)
                                context.remaining()
                                return result

                        row = await run_blocking(
                            "knowledge-chunk-write",
                            execute,
                            lane="control-io",
                            owner="runtime.knowledge_base",
                        )
                return ChunkMutationState(
                    **{field: row[field] for field in ChunkMutationState.model_fields}
                )
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning(
                "knowledge_chunk_write_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                context.operation_id,
                threshold,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error
