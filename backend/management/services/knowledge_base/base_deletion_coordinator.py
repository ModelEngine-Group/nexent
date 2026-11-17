# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Order file and physical collection cleanup under the persisted KB fence."""

import asyncio
import logging
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from management.services.knowledge_base.base_deletion import (
    KnowledgeBaseDeletionJournal,
    request_knowledge_base_deletion,
    request_knowledge_base_owner_deletion,
    request_knowledge_base_tenant_deletion,
)
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCancellation,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, OutcomeUnknown, Unavailable
from nexent.storage.models import (
    Comparison,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)

from infrastructure.knowledge_admission import knowledge_admission_ports
from infrastructure.knowledge_base_metadata import knowledge_base_metadata_ports

logger = logging.getLogger(__name__)


class KnowledgeBaseDeletionCoordinator:
    """A request advances known work once; uncertain writes are only inspected."""

    def __init__(self, files, client, *, ports=knowledge_admission_ports, metadata_ports=knowledge_base_metadata_ports):
        self.files, self.client, self.ports = files, client, ports
        self.metadata_ports = metadata_ports

    async def _blocking(self, name, fn, *args, **kwargs):
        return await run_blocking('knowledge-base-deletion-' + name, fn, *args,
                                  lane='control-io', owner='management.knowledge_base', **kwargs)

    def _admit(self, index_name, actor, context, owner_user_id=None, purpose=None, tenant_cleanup=False):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            if tenant_cleanup:
                return request_knowledge_base_tenant_deletion(records, resources, index_name, actor, context=context)
            if owner_user_id is not None:
                return request_knowledge_base_owner_deletion(records, resources, index_name, owner_user_id,
                                                             purpose, actor, context=context)
            return request_knowledge_base_deletion(records, resources, index_name, actor, context=context)

    def _page(self, row, actor, context, cursor):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            journal = KnowledgeBaseDeletionJournal(records, resources, actor)
            current = journal.load(row['knowledge_id'], context=context)
            if journal.intent(current).phase != 'files':
                return None
            return records.query(FILES, RecordQuery(
                fields=('file_id', 'status', 'stage'), where=Comparison('knowledge_id', 'eq', row['knowledge_id']),
                order_by=(Sort('file_id'),),
            ), PageRequest(limit=200, cursor=cursor), context=context)

    def _journal(self, row, actor, context, method, *args):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            return getattr(KnowledgeBaseDeletionJournal(records, resources, actor), method)(row, *args, context=context)

    def _current(self, row, actor, context):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            return KnowledgeBaseDeletionJournal(records, resources, actor).load(row['knowledge_id'], context=context)

    def _finalize(self, row, actor, context):
        from management.services.knowledge_base.base_metadata import (
            finalize_knowledge_base_deletion,
        )

        context.remaining()
        with self.metadata_ports(actor, context=context) as (records, resources):
            return finalize_knowledge_base_deletion(records, resources, row, actor, context=context)

    async def request(self, index_name, actor, *, context=None):
        return await self._request(index_name, actor, context=context)

    async def request_owner_cleanup(self, index_name, owner_user_id, actor, *, purpose='user_deletion', context=None):
        return await self._request(index_name, actor, owner_user_id=owner_user_id, purpose=purpose, context=context)

    async def admit_owner_cleanup(self, index_name, owner_user_id, actor, *, purpose='user_deletion', context=None):
        return await self._request(index_name, actor, owner_user_id=owner_user_id, purpose=purpose,
                                   prepare_only=True, context=context)

    async def admit_tenant_cleanup(self, index_name, actor, *, context=None):
        return await self._request(index_name, actor, tenant_cleanup=True, prepare_only=True, context=context)

    async def request_tenant_cleanup(self, index_name, actor, *, context=None):
        return await self._request(index_name, actor, tenant_cleanup=True, context=context)

    async def _request(self, index_name, actor, *, owner_user_id=None, purpose=None, prepare_only=False,
                       tenant_cleanup=False, context=None):
        context = context or OperationContext('kb-base-delete-' + uuid4().hex, monotonic() + 10)
        stopped = Event()
        operation = replace(context, deadline=min(context.deadline, monotonic() + 10),
                            cancelled=IngestionCancellation(stopped, context.cancelled))
        row = None
        try:
            async with asyncio.timeout(operation.remaining()):
                row = await self._blocking('admit', self._admit, index_name, actor, operation,
                                           owner_user_id, purpose, tenant_cleanup)
                intent = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
                if prepare_only:
                    return row
                # A different editor may acknowledge the intent but cannot execute as its owner.
                if intent.user_id != actor.user_id:
                    return row
                if intent.phase == 'metadata_pending':
                    return await self._blocking('finalize', self._finalize, row, actor, operation)
                if intent.phase == 'files':
                    complete, cursor = True, None
                    while True:
                        page = await self._blocking('files', self._page, row, actor, operation, cursor)
                        if page is None:
                            return row
                        for file in page.items:
                            if file['status'] == 'DELETED' and file['stage'] == 'DELETE_DONE':
                                continue
                            result = await self.files.request(index_name, None, 'full', actor,
                                                              file_id=file['file_id'], context=operation, remove_tags=False)
                            complete &= result['status'] == 'DELETED' and result['stage'] == 'DELETE_DONE'
                        if page.next_cursor is None:
                            break
                        cursor = page.next_cursor
                    if not complete:
                        return row
                    # Child source finalization advances the same KB revision for its document timestamp.
                    row = await self._blocking('current-parent', self._current, row, actor, operation)
                    if KnowledgeBaseDeletionIntent.model_validate(row['deletion_request']).phase != 'files':
                        return row
                    row, payload = await self._blocking('reserve', self._journal, row, actor, operation, 'begin_collection')
                    state = await self.client.delete_knowledge_base(payload, user_id=actor.user_id, tenant_id=actor.tenant_id)
                else:
                    request = await self._blocking('lookup', self._journal, row, actor, operation, 'lookup')
                    try:
                        state = await self.client.inspect_knowledge_base_deletion(request,
                                                                                 user_id=actor.user_id, tenant_id=actor.tenant_id)
                    except RuntimeUpstreamError as error:
                        if error.status_code != 404:
                            raise
                        return row
                row = await self._blocking('observe', self._journal, row, actor, operation, 'observe_collection', state)
                if KnowledgeBaseDeletionIntent.model_validate(row['deletion_request']).phase == 'metadata_pending':
                    return await self._blocking('finalize', self._finalize, row, actor, operation)
                return row
        except (TimeoutError, DeadlineExceeded, OutcomeUnknown, Unavailable,
                RuntimeServiceTimeoutError, RuntimeServiceUnavailableError) as error:
            logger.warning('knowledge_base_deletion_pending operation_id=%s error_type=%s',
                           operation.operation_id, type(error).__name__)
            if row is not None:
                return row
            if isinstance(error, TimeoutError):
                raise DeadlineExceeded(operation_id=operation.operation_id) from error
            raise
        finally:
            stopped.set()
