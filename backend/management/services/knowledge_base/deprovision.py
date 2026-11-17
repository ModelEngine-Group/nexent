# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare exact deprovision authority while identities are live, then execute admitted work."""

import logging
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_admission import knowledge_admission_ports

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeCleanupPlan:
    owner_user_id: str | None
    actor: ServicePrincipal
    purpose: str
    indexes: tuple[str, ...]
    total: int | None
    failed: int


def _coordinator():
    from management.services.knowledge_base.ingestion_dispatch import (
        default_base_deletion_coordinator,
        default_coordinator,
    )

    return default_base_deletion_coordinator(default_coordinator())


def _select(owner_user_id, actor, context):
    indexes, cursor = [], None
    terms = ((Comparison('created_by', 'eq', owner_user_id), Comparison('ingroup_permission', 'eq', 'PRIVATE'))
             if owner_user_id is not None else (Comparison('ingroup_permission', 'in', ['EDIT', 'READ_ONLY']),))
    with knowledge_admission_ports(actor, context=context, readonly=True) as (records, _):
        while True:
            context.remaining()
            page = records.query(KB, RecordQuery(
                fields=('index_name',), order_by=(Sort('knowledge_id'),),
                where=Junction('and', (*terms, Comparison('knowledge_sources', 'eq', 'elasticsearch'))),
            ), PageRequest(limit=100, cursor=cursor), context=context)
            indexes.extend(row.get('index_name') for row in page.items)
            if page.next_cursor is None:
                return indexes
            cursor = page.next_cursor


async def prepare_private_cleanup(owner_user_id, tenant_id, actor_id, *, purpose='user_deletion'):
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise ScopeDenied()
    return await _prepare(owner_user_id, tenant_id, actor_id, purpose)


async def prepare_tenant_cleanup(tenant_id, actor_id):
    return await _prepare(None, tenant_id, actor_id, 'tenant_deletion')


async def _prepare(owner_user_id, tenant_id, actor_id, purpose):
    actor = ServicePrincipal(actor_id, tenant_id)
    context = OperationContext('private-knowledge-prepare-' + uuid4().hex, monotonic() + 10)
    try:
        indexes = await run_blocking('private-knowledge-select', _select, owner_user_id, actor, context,
                                     lane='control-io', owner='management.knowledge_base')
    except Exception as error:  # noqa: BLE001 - Resource cleanup must not prevent identity revocation.
        logger.error('private_knowledge_selection_failed owner=%s error_type=%s', owner_user_id, type(error).__name__)
        return KnowledgeCleanupPlan(owner_user_id, actor, purpose, (), None, 0)
    admitted, failed = [], 0
    try:
        coordinator = _coordinator() if indexes else None
    except Exception as error:  # noqa: BLE001 - Resource cleanup must not prevent identity revocation.
        logger.error('private_knowledge_admission_unavailable owner=%s error_type=%s', owner_user_id, type(error).__name__)
        return KnowledgeCleanupPlan(owner_user_id, actor, purpose, (), len(indexes), len(indexes))
    for index in indexes:
        try:
            if not index:
                raise ScopeDenied()
            if owner_user_id is None:
                await coordinator.admit_tenant_cleanup(index, actor)
            else:
                await coordinator.admit_owner_cleanup(index, owner_user_id, actor, purpose=purpose)
            admitted.append(index)
        except Exception as error:  # noqa: BLE001 - Resource cleanup must not prevent identity revocation.
            failed += 1
            logger.error('private_knowledge_admission_failed owner=%s error_type=%s', owner_user_id, type(error).__name__)
    return KnowledgeCleanupPlan(owner_user_id, actor, purpose, tuple(admitted), len(indexes), failed)


async def execute_cleanup(plan):
    if not plan.total:
        return None
    result = {'total': plan.total, 'succeeded': 0, 'failed': plan.failed, 'pending': 0}
    coordinator = _coordinator() if plan.indexes else None
    for index in plan.indexes:
        try:
            if plan.owner_user_id is None:
                row = await coordinator.request_tenant_cleanup(index, plan.actor)
            else:
                row = await coordinator.request_owner_cleanup(index, plan.owner_user_id, plan.actor, purpose=plan.purpose)
            intent = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
            if plan.owner_user_id is None:
                scope_matches = intent.tenant_cleanup is not None and plan.purpose == 'tenant_deletion'
            else:
                scope_matches = (intent.owner_cleanup is not None
                                 and intent.owner_cleanup.owner_user_id == plan.owner_user_id
                                 and intent.owner_cleanup.purpose == plan.purpose)
            if (intent.user_id != plan.actor.user_id or intent.index_name != index
                    or row['index_name'] != index or intent.knowledge_id != row['knowledge_id']
                    or not scope_matches):
                raise ScopeDenied()
            if row['delete_flag'] == 'Y' and intent.phase == 'deleted':
                result['succeeded'] += 1
            elif row['delete_flag'] == 'N' and intent.phase != 'deleted':
                result['pending'] += 1
            else:
                raise ScopeDenied()
        except Exception as error:  # noqa: BLE001 - Resource cleanup must not prevent identity revocation.
            result['failed'] += 1
            logger.error('private_knowledge_execution_failed owner=%s error_type=%s',
                         plan.owner_user_id, type(error).__name__)
    return result
