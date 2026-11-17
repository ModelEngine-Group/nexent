# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unlink a remote DataMate catalog locally while the actual SU is still live."""

import logging
from time import monotonic
from uuid import uuid4

from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from management.services.knowledge_base.admission import (
    change_knowledge_admission,
    require_admission_actor,
)
from management.services.knowledge_base.base_metadata import (
    _confirmed,
    remove_knowledge_metadata_bindings,
)
from management.services.knowledge_base.owner_cleanup import (
    require_tenant_cleanup_issuer,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_base_metadata import knowledge_base_metadata_ports

logger = logging.getLogger(__name__)


def unlink_datamate_record(records, resources, knowledge_id, actor, *, context):
    require_admission_actor(records, resources, actor)
    require_tenant_cleanup_issuer(actor, context=context)
    with records.transaction(context=context) as transaction:
        previous = transaction.get(KB, knowledge_id, context=context)
        if previous is None:
            raise ScopeDenied()
        row = change_knowledge_admission(transaction, previous, {},
                                         expected=Revision(str(previous['version'])), context=context)
        if row['tenant_id'] != actor.tenant_id or row['knowledge_sources'] != 'datamate':
            raise ScopeDenied()
        if row['deletion_request'] is not None:
            raise Conflict()
        for dataset, where in (
            (FILES, Comparison('knowledge_id', 'eq', knowledge_id)),
            (LEDGER, Junction('and', (Comparison('knowledge_id', 'eq', knowledge_id),
                                      Comparison('status', 'eq', 'COMMITTED')))),
        ):
            if transaction.query(dataset, RecordQuery(where=where), PageRequest(limit=1), context=context).items:
                raise Conflict()
        counts = remove_knowledge_metadata_bindings(transaction, row, context=context)
        require_tenant_cleanup_issuer(actor, context=context)
        _confirmed(transaction.delete(KB, knowledge_id, expected=Revision(str(row['version'])), context=context),
                    context, delete=True)
        return {**counts, 'knowledge_records_deleted': 1}


def _select(actor, context):
    ids, cursor = [], None
    with knowledge_base_metadata_ports(actor, context=context) as (records, _):
        while True:
            context.remaining()
            page = records.query(KB, RecordQuery(fields=('knowledge_id',),
                where=Comparison('knowledge_sources', 'eq', 'datamate'), order_by=(Sort('knowledge_id'),)),
                PageRequest(limit=100, cursor=cursor), context=context)
            ids.extend(row['knowledge_id'] for row in page.items)
            if page.next_cursor is None:
                return ids
            cursor = page.next_cursor


def _unlink(knowledge_id, actor, context):
    with knowledge_base_metadata_ports(actor, context=context, ledger=True) as (records, resources):
        return unlink_datamate_record(records, resources, knowledge_id, actor, context=context)


async def unlink_datamate_for_tenant(tenant_id, actor_id):
    actor = ServicePrincipal(actor_id, tenant_id)

    async def blocking(name, fn, *args):
        return await run_blocking('datamate-tenant-' + name, fn, *args,
                                  lane='control-io', owner='management.knowledge_base')

    def context():
        return OperationContext('datamate-unlink-' + uuid4().hex, monotonic() + 10)

    try:
        ids = await blocking('select', _select, actor, context())
    except Exception as error:  # noqa: BLE001 - Preserve credential revocation after resource cleanup failure.
        logger.error('datamate_unlink_selection_failed tenant=%s actor=%s error_type=%s',
                     tenant_id, actor_id, type(error).__name__)
        return None
    result = {'total': len(ids), 'succeeded': 0, 'failed': 0, 'pending': 0}
    for knowledge_id in ids:
        try:
            await blocking('record', _unlink, knowledge_id, actor, context())
            result['succeeded'] += 1
        except OutcomeUnknown:
            result['pending'] += 1
        except Exception as error:  # noqa: BLE001 - Best-effort unlink never retries or replaces the actual issuer.
            result['failed'] += 1
            logger.error('datamate_unlink_failed knowledge_id=%s tenant=%s actor=%s error_type=%s',
                         knowledge_id, tenant_id, actor_id, type(error).__name__)
    logger.info('datamate_tenant_unlink tenant=%s actor=%s result=%s', tenant_id, actor_id, result)
    return result
