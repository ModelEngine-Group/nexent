# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Advance persisted deletion through AgentOS and local physical cleanup once."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from management.services.knowledge_base.deletion_journal import (
    DeletionJournal,
    DeletionPhaseChanged,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCancellation,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
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

    def _prepare(self, index_name, path, scope, actor, file_id, context):
        from management.services.knowledge_base.deletion_selection import (
            prepare_deletion,
        )

        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            row, intent, advance = prepare_deletion(
                records, resources, index_name, path, scope, actor, file_id=file_id, context=context,
            )
            if advance:
                row = DeletionJournal(records).admit(intent, row, context=context)
            return row, advance

    def _remove_tags(self, row, actor, context):
        from management.services.tag.library import TagManagementService

        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            if any(port.scope.system or port.scope.service_role != 'management'
                   or port.scope.actor_id != actor.user_id or port.scope.tenant_id != actor.tenant_id
                   for port in (records, resources)):
                raise ScopeDenied()
            current = DeletionJournal(records).record(row['file_id'], context=context)
            knowledge = KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve_knowledge(
                current['knowledge_id'], edit=True, context=context,
            )
            if (current['tenant_id'] != actor.tenant_id or current['index_name'] != knowledge['index_name']
                    or current['knowledge_id'] != row['knowledge_id']):
                raise ScopeDenied()
            if current['object_name']:
                TagManagementService.cleanup_document_assignments(
                    actor.tenant_id, 'local', current['index_name'], current['object_name'], actor.user_id,
                )

    async def request(self, index_name, path, scope, actor, *, file_id=None, context=None, remove_tags=False):
        """Admit once, then share one total deadline with the existing phase owner."""
        admitted = None
        try:
            async with self._operation(context, file_id) as operation:
                admitted, advance = await self._blocking(
                    'prepare', self._prepare, index_name, path, scope, actor, file_id, operation,
                )
                if remove_tags and scope == 'full':
                    await self._blocking('remove-tags', self._remove_tags, admitted, actor, operation)
                if not advance:
                    return admitted
                return await self.advance(admitted['file_id'], actor, context=operation)
        except (DeadlineExceeded, OutcomeUnknown, Unavailable, DeletionPhaseChanged,
                RuntimeServiceTimeoutError, RuntimeServiceUnavailableError):
            if admitted is None:
                raise
            # The persistent owner continues from its last phase. Never reread or replay here.
            return admitted

    def _change(self, previous, actor, context, method, *args, **kwargs):
        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            journal, row, _ = self._validated(records, resources, previous['file_id'], actor, context)
            if row['version'] != previous['version']:
                raise DeletionPhaseChanged()
            return getattr(journal, method)(row, *args, context=context, **kwargs)

    def _delete_source(self, previous, actor, context):
        from management.services.knowledge_base.source_deletion import SourceDeletion

        from infrastructure.knowledge_deletion import deletion_source_objects

        context.remaining()
        with self.ports(actor, context=context) as (records, resources):
            _, row, _ = self._validated(records, resources, previous['file_id'], actor, context)
            if row['version'] != previous['version']:
                raise DeletionPhaseChanged()
            with deletion_source_objects(row, actor, context=context) as objects:
                result = SourceDeletion(records, objects).advance(row, context=context)
            if result['stage'] == 'SOURCE_DELETED' and row['stage'] != 'SOURCE_DELETED':
                self._cleanup_preview(result, actor, context)
            return result

    @staticmethod
    def _cleanup_preview(row, actor, context):
        from management.services.file.preview import build_preview_pdf_object_key
        from nexent.storage.errors import NotFound
        from nexent.storage.models import ObjectRef

        from infrastructure.knowledge_deletion import deletion_preview_objects

        if not row['object_name'] or not row['object_name'].startswith('knowledge_base/'):
            return
        try:
            key = build_preview_pdf_object_key(row['object_name'])
            with deletion_preview_objects(row, actor, key, context=context) as objects:
                metadata = objects.stat(ObjectRef('files', key), context=context)
                target = metadata.ref if metadata.ref.version and metadata.ref.version.value.startswith('version:') else ObjectRef('files', key)
                objects.delete(target, context=context)
        except NotFound:
            return
        except Exception as error:  # noqa: BLE001 - retain the original best-effort cache cleanup
            # Preview caches were always best effort; never retry or alter the source outcome.
            logger.warning('knowledge_delete_preview_failed file_id=%s error_type=%s',
                           row['file_id'], type(error).__name__)

    async def advance(self, file_id, actor, *, context=None):
        async with self._operation(context, file_id) as operation:
            row, intent = await self._blocking('load', self._load, file_id, actor, operation)
            if DeletionJournal.awaiting_source(row):
                row = await self._blocking('activate', self._change, row, actor, operation, 'activate')
                if DeletionJournal.awaiting_source(row):
                    return row
                row, intent = await self._blocking('load-activated', self._load, file_id, actor, operation)
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
