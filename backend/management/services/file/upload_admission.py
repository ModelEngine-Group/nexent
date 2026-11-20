# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Admit KB uploads and persist the outcome for the admitted file."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeUploadFile
from management.services.knowledge_base.admission import (
    change_knowledge_admission,
    require_admission_actor,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import FieldPatch, OperationContext, Revision, WriteOutcome

from infrastructure.knowledge_admission import knowledge_admission_ports

logger = logging.getLogger(__name__)


class KnowledgeUploadAdmission:
    def __init__(self, records, resources, actor):
        require_admission_actor(records, resources, actor)
        self.records, self.resources, self.actor = records, resources, actor

    def admit(self, specs, *, context):
        specs = [KnowledgeUploadFile.model_validate(spec) for spec in specs]
        if not specs:
            return []
        if any(spec.tenant_id != self.actor.tenant_id or spec.created_by != self.actor.user_id for spec in specs):
            raise ScopeDenied()
        ids = sorted({spec.knowledge_id for spec in specs})
        authorized = KnowledgeFileAuthorization(self.resources, user_id=self.actor.user_id).resolve_knowledges(
            ids, edit=True, context=context,
        )
        by_id = {row['knowledge_id']: row for row in authorized}
        if any(spec.index_name != by_id[spec.knowledge_id]['index_name'] for spec in specs):
            raise ScopeDenied()
        with self.records.transaction(context=context) as transaction:
            for knowledge_id in ids:
                row = transaction.get(KB, knowledge_id, context=context)
                if row is None or row['index_name'] != by_id[knowledge_id]['index_name']:
                    raise ScopeDenied()
                if row['deletion_request'] is not None:
                    raise Conflict()
                # Serialize ordinary uploads without rejecting another valid upload's revision.
                locked = change_knowledge_admission(transaction, row, {}, expected=None, context=context)
                if locked['deletion_request'] is not None:
                    raise Conflict()
                if locked['index_name'] != by_id[knowledge_id]['index_name']:
                    raise ScopeDenied()
            return [transaction.create(FILES, {
                **spec.model_dump(exclude={'created_by'}), 'source_generation': 0, 'processing_attempt': 0,
            }, context=context) for spec in specs]


async def admit_knowledge_uploads(specs, *, actor):
    if not specs:
        return []
    stopped = Event()
    context = OperationContext('knowledge-upload-admission-' + uuid4().hex, monotonic() + 10, cancelled=stopped)

    def admit():
        with knowledge_admission_ports(actor, context=context) as (records, resources):
            return KnowledgeUploadAdmission(records, resources, actor).admit(specs, context=context)

    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('knowledge-upload-admission', admit, lane='control-io', owner='management.file')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_upload_admission_timeout operation_id=%s threshold_seconds=10 error_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        stopped.set()



def _patch_upload_record(records, file_id, actor, expected_statuses, fields, *, context):
    with records.transaction(context=context) as transaction:
        row = transaction.get(FILES, file_id, context=context)
        if row is None or row["created_by"] != actor.user_id or row["status"] not in expected_statuses:
            return None
        receipt = transaction.patch(
            FILES, file_id, FieldPatch(set_values=fields),
            expected=Revision(str(row["version"])), context=context,
        )
        if receipt.outcome is not WriteOutcome.CONFIRMED:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if not receipt.matched:
            return None
        return transaction.get(FILES, file_id, context=context)


async def update_upload_record(file_id, *, actor, expected_statuses, **fields):
    """Update an admitted upload owned by the current request identity."""
    stopped = Event()
    context = OperationContext('knowledge-upload-outcome-' + uuid4().hex, monotonic() + 10, cancelled=stopped)

    def update():
        with knowledge_admission_ports(actor, context=context) as (records, _):
            return _patch_upload_record(records, file_id, actor, expected_statuses, fields, context=context)

    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('knowledge-upload-outcome', update, lane='control-io', owner='management.file')
    except TimeoutError as error:
        raise OutcomeUnknown(operation_id=context.operation_id) from error
    finally:
        stopped.set()
