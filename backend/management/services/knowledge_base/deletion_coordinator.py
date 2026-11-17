# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Advance persisted deletion through AgentOS and local physical cleanup once."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import RuntimeUpstreamError
from management.services.knowledge_base.deletion_journal import DeletionJournal
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCancellation,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.knowledge_deletion import knowledge_deletion_ports

logger = logging.getLogger(__name__)


class DeletionCoordinator:
    def __init__(self, cleanse, client, *, ports=knowledge_deletion_ports, source=None):
        self.cleanse, self.client, self.ports = cleanse, client, ports
        self.source = source if source is not None else self._delete_source

    @asynccontextmanager
    async def _operation(self, context, file_id):
        context = context or OperationContext('kb-delete-' + uuid4().hex, monotonic() + 10)
        stopped = Event()
        context = replace(context, deadline=min(context.deadline, monotonic() + 10),
                          cancelled=IngestionCancellation(stopped, context.cancelled))
        try:
            async with asyncio.timeout(context.remaining()):
                yield context
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_deletion_timeout file_id=%s operation_id=%s error_type=%s',
                           file_id, context.operation_id, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            stopped.set()

    async def _blocking(self, name, fn, *args, **kwargs):
        return await run_blocking('knowledge-deletion-' + name, fn, *args,
                                  lane='control-io', owner='management.knowledge_base', **kwargs)

    def _validated(self, records, resources, file_id, actor, context, intent=None):
        if any(port.scope.system or port.scope.service_role != 'management'
               or port.scope.actor_id != actor.user_id or port.scope.tenant_id != actor.tenant_id
               for port in (records, resources)):
            raise ScopeDenied()
        journal = DeletionJournal(records)
        row = journal.record(file_id, context=context)
        knowledge = KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve_knowledge(
            row['knowledge_id'], edit=True, context=context,
        )
        if row['tenant_id'] != actor.tenant_id or row['index_name'] != knowledge['index_name']:
            raise ScopeDenied()
        if intent is None:
            intent = journal.request(row)
        journal._identity(row, intent)
        return journal, row, intent

    def _load(self, file_id, actor, context):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            _, row, intent = self._validated(records, resources, file_id, actor, context)
            return row, intent

    def _admit(self, intent, actor, context):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            journal, row, _ = self._validated(records, resources, intent.file_id, actor, context, intent)
            return journal.admit(intent, row, context=context)

    async def admit(self, intent, actor, *, context=None):
        async with self._operation(context, intent.file_id) as operation:
            return await self._blocking('admit', self._admit, intent, actor, operation)

    def _change(self, previous, actor, context, method, *args, **kwargs):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            journal, row, _ = self._validated(records, resources, previous['file_id'], actor, context)
            if row['version'] != previous['version']:
                raise Conflict()
            return getattr(journal, method)(row, *args, context=context, **kwargs)

    def _delete_source(self, previous, actor, context):
        from management.services.knowledge_base.source_deletion import SourceDeletion

        from infrastructure.knowledge_deletion import deletion_source_objects

        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            _, row, _ = self._validated(records, resources, previous['file_id'], actor, context)
            if row['version'] != previous['version']:
                raise Conflict()
            with deletion_source_objects(row, actor, context=context) as objects:
                return SourceDeletion(records, objects).advance(row, context=context)

    async def advance(self, file_id, actor, *, context=None):
        async with self._operation(context, file_id) as operation:
            row, intent = await self._blocking('load', self._load, file_id, actor, operation)
            if row['stage'] in {'DELETE_DONE', 'SOURCE_DELETED'}:
                return row
            if intent.scope == 'full':
                if row['stage'] == 'DELETE_ACCEPTED':
                    row, payload = await self._blocking('reserve-runtime', self._change,
                                                        row, actor, operation, 'begin_runtime')
                    state = await self.client.delete_knowledge_file(payload, user_id=actor.user_id, tenant_id=actor.tenant_id)
                elif row['stage'] in {'DELETE_RUNTIME_SUBMITTING', 'DELETE_RUNTIME_PENDING'}:
                    try:
                        state = await self.client.inspect_knowledge_file(intent.runtime_lookup(actor.tenant_id),
                                                                        user_id=actor.user_id, tenant_id=actor.tenant_id)
                    except RuntimeUpstreamError as error:
                        if error.status_code != 404:
                            raise
                        return row
                else:
                    state = None
                if state is not None:
                    row = await self._blocking('observe-runtime', self._change, row, actor, operation, 'observe_runtime', state)
                if row['stage'] in {'DELETE_RUNTIME_SUBMITTING', 'DELETE_RUNTIME_PENDING'}:
                    return row
                if row['stage'] == 'DELETE_CLEANSE_PENDING':
                    result = await self._blocking('cancel-cleanse', self.cleanse.cancel_file, intent,
                                                  tenant_id=actor.tenant_id, user_id=actor.user_id, context=operation)
                    if result['execution_drained'] is not True:
                        return row
                    row = await self._blocking('confirm-cleanse', self._change, row, actor, operation,
                                               'confirm_cleanse_drained', physical_completion_confirmed=True)
            return await self._blocking('delete-source', self.source, row, actor, operation)
