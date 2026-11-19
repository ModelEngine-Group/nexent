# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Create an authorized empty collection under a durable lifecycle fence."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos import ModelMetadata
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_collections import (
    CollectionSetup,
    KnowledgeCollectionAuthorization,
    KnowledgeCollectionEnsure,
    KnowledgeCollectionEnsured,
    KnowledgeCollectionGrant,
    KnowledgeCollectionLookup,
    KnowledgeCollectionStatus,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OperationCancelled,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import OperationContext, VectorCollectionInfo
from runtime.knowledge_base.collection_journal import KnowledgeCollectionJournal
from runtime.knowledge_base.worker import cancellable_context

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_chunk_mutations import (
    knowledge_chunk_mutation_ports,
    knowledge_creation_vector_ports,
)

logger = logging.getLogger(__name__)


class KnowledgeCollectionService:
    def __init__(self, client, models, *, records=knowledge_chunk_mutation_ports,
                 ports=knowledge_creation_vector_ports, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client, self.models, self.records, self.ports, self.seconds = client, models, records, ports, operation_seconds

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_collection(
            KnowledgeCollectionAuthorization(knowledge_id=request.knowledge_id), actor.user_id, actor.tenant_id)
        if (not isinstance(grant, KnowledgeCollectionGrant) or grant.knowledge_id != request.knowledge_id
            or grant.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}):
            raise ScopeDenied()
        if grant.revision != request.expected_revision:
            raise Conflict()
        return grant

    def _execute(self, request, actor, grant, setup, *, context, inspect=False):
        namespace = {} if grant.resource_tenant_id == actor.tenant_id else {'resource_tenant_id': grant.resource_tenant_id}
        with self.records(actor, context=context, **namespace) as records:
            if (records.scope.actor_id != actor.user_id or records.scope.tenant_id != grant.resource_tenant_id
                or records.scope.service_role != 'runtime' or records.scope.system):
                raise ScopeDenied()
            journal = KnowledgeCollectionJournal(records, request.knowledge_id)
            if inspect:
                return KnowledgeCollectionStatus(knowledge_id=request.knowledge_id,
                    expected_revision=grant.revision, setup=journal.inspect(context=context))
            journal.reserve(setup, context=context)
            attempted = False
            returned = False
            try:
                with self.ports(actor, grant.collection, request.dimensions, context=context, **namespace) as vectors:
                    if (vectors.scope.actor_id != actor.user_id or vectors.scope.tenant_id != grant.resource_tenant_id
                        or vectors.scope.service_role != 'runtime' or vectors.scope.system
                        or vectors.scope.namespaces != {grant.collection} or vectors.scope.resource_prefix):
                        raise ScopeDenied()
                    journal.begin(setup.operation_id, context=context)
                    context.remaining()
                    attempted = True
                    info = vectors.ensure_collection(grant.collection, context=context)
                    returned = True
                    if (not isinstance(info, VectorCollectionInfo) or info.collection != grant.collection
                        or info.dimensions != request.dimensions or info.metric != 'cosine'):
                        raise Conflict()
                journal.finish(setup.operation_id, confirmed=True, context=context)
            except Exception as error:
                rejected = attempted and not returned and isinstance(error, (
                    CapabilityUnsupported, Conflict, InvalidInput, NotFound, ScopeDenied, Unavailable))
                uncertain = attempted and not rejected
                settlement_failed = False
                try:
                    context.remaining()
                    if uncertain:
                        journal.unknown(setup.operation_id, writer_ended=True, context=context)
                    else:
                        journal.finish(setup.operation_id, confirmed=False, context=context)
                except (DeadlineExceeded, OperationCancelled):
                    pass
                except Exception as settlement_error:  # noqa: BLE001 - A failed receipt cannot prove no provider effect.
                    settlement_failed = True
                    logger.warning('knowledge_collection_settlement_failed operation_id=%s exception_type=%s',
                                   context.operation_id, type(settlement_error).__name__)
                if uncertain or settlement_failed:
                    raise OutcomeUnknown(operation_id=context.operation_id) from error
                raise
            return KnowledgeCollectionEnsured(knowledge_id=request.knowledge_id, expected_revision=grant.revision,
                                               present=True, dimensions=request.dimensions, metric='cosine')

    async def ensure(self, request, actor, *, context=None):
        return await self._dispatch(request, actor, context=context, inspect=False)

    async def inspect(self, request, actor, *, context=None):
        return await self._dispatch(request, actor, context=context, inspect=True)

    async def _dispatch(self, request, actor, *, context, inspect):
        schema = KnowledgeCollectionLookup if inspect else KnowledgeCollectionEnsure
        if type(request) is not schema:
            raise InvalidInput()
        request = schema.model_validate(request.model_dump())
        context = context or OperationContext('knowledge-collection-' + uuid4().hex, monotonic() + self.seconds)
        context, cancelled = cancellable_context(context)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(request, actor)
                if not inspect and request.model_binding is not None:
                    binding = request.model_binding
                    if grant.embedding_model_id != binding.model_id:
                        raise ScopeDenied()
                    model = await self.models.get(binding.model_id, actor)
                    if (not isinstance(model, ModelMetadata) or model.model_id != binding.model_id
                        or model.model_type not in {'embedding', 'multi_embedding'}
                        or normalize_model_revision(model.revision) != normalize_model_revision(binding.revision)):
                        raise Conflict()
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                setup = None if inspect else CollectionSetup(operation_id=context.operation_id,
                    actor_id=actor.user_id, resource_revision=grant.revision, dimensions=request.dimensions,
                    model_binding=request.model_binding, phase='reserved', writer_ended=False)
                result = await run_blocking('knowledge-collection-inspect' if inspect else 'knowledge-collection-ensure',
                    self._execute, request, actor, grant, setup, context=context, inspect=inspect,
                    lane='control-io', owner='runtime.knowledge_base')
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                return result
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_collection_timeout operation_id=%s phase=%s threshold_seconds=%s exception_type=%s',
                context.operation_id, 'inspect' if inspect else 'ensure', threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
