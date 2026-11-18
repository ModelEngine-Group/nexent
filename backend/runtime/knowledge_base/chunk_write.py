# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute signed normalized chunk writes under current Management edit grants."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_mutation import (
    ChunkCreateData,
    ChunkMutationAuthorization,
    ChunkMutationGrant,
    ChunkMutationIntent,
    ChunkMutationState,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext
from pydantic import ValidationError
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.chunk_creation import ChunkCreationExecutor
from runtime.knowledge_base.chunk_executor import ChunkMutationExecutor

from infrastructure.knowledge_chunk_mutations import (
    knowledge_chunk_mutation_ports,
    knowledge_chunk_vector_ports,
    knowledge_creation_vector_ports,
)

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
        if intent.operation == "create":
            model = ChunkCreateData.model_validate(intent.changes).embedding_model
            if model is not None and model.model_id != grant.embedding_model_id:
                raise ScopeDenied()
        return grant

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
