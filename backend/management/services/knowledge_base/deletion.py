# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public document deletion delegates execution to the persistent phase owner."""

import asyncio
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_collections import (
    KnowledgeCollectionAuthorization,
    KnowledgeUntrackedSourceDelete,
    KnowledgeUntrackedSourceDeleted,
)
from management.services.knowledge_base.base_deletion_public import (
    project_base_deletion,
)
from management.services.knowledge_base.collection_authorization import (
    authorize_collection,
)
from management.services.knowledge_base.deletion_public import project_deletion
from management.services.knowledge_base.deletion_selection import DocumentLedgerNotFound
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.ingestion_dispatch import (
    default_base_deletion_coordinator,
    default_coordinator,
    default_deletion_coordinator,
)
from management.services.knowledge_base.management import KnowledgeBaseManagementService
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def _delete_untracked_source(client, index_name, address, actor):
    context = OperationContext('kb-delete-untracked-' + uuid4().hex, monotonic() + 10)

    def prepare():
        row = KnowledgeFileReader().knowledge(index_name, actor, edit=True, context=context)
        authorization = KnowledgeCollectionAuthorization(knowledge_id=row['knowledge_id'], untracked_source=address)
        grant = authorize_collection(authorization, actor, context=context)
        if grant.collection != index_name:
            raise Conflict()
        return KnowledgeUntrackedSourceDelete(knowledge_id=grant.knowledge_id, expected_revision=grant.revision,
                                              untracked_source=address)

    try:
        async with asyncio.timeout(context.remaining()):
            request = await run_blocking('knowledge-delete-untracked-authorization', prepare,
                                         lane='control-io', owner='management.knowledge_base')
            result = await client.delete_untracked_knowledge_source(request, actor.user_id, actor.tenant_id)
            if (not isinstance(result, KnowledgeUntrackedSourceDeleted) or result.knowledge_id != request.knowledge_id
                or result.expected_revision != request.expected_revision or result.untracked_source != address):
                raise Conflict()
    except (TimeoutError, RuntimeServiceTimeoutError) as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    return {
        'status': 'success', 'scope': 'full', 'deleted_es_count': result.deleted_count,
        'deleted_minio': False, 'source_available': False, 'lifecycle_deleted': False,
        'cancelled_tasks': {'task_ids': [], 'cancelled_count': 0},
    }


class KnowledgeBaseDocumentDeletionService(KnowledgeBaseManagementService):
    @staticmethod
    async def delete_knowledge_base(index_name, *, requested_by, tenant_id):
        actor = ServicePrincipal(requested_by, tenant_id)
        coordinator = default_base_deletion_coordinator(default_coordinator())
        row = await coordinator.request(index_name, actor)
        return project_base_deletion(index_name, row)

    @staticmethod
    async def delete_document_by_scope(
        index_name, path_or_url, scope, *, requested_by, tenant_id, file_id=None, remove_tags=False,
    ):
        actor = ServicePrincipal(requested_by, tenant_id)
        coordinator = default_deletion_coordinator(default_coordinator())
        try:
            row = await coordinator.request(
                index_name, path_or_url, scope, actor, file_id=file_id, remove_tags=remove_tags,
            )
        except DocumentLedgerNotFound:
            if file_id is not None or scope != 'full' or not environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED:
                raise
            return await _delete_untracked_source(coordinator.client, index_name, path_or_url, actor)
        return project_deletion(row)
