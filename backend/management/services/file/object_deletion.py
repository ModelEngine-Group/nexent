# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete authorized storage objects and release source charges only after confirmation."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from contracts.knowledge import StorageObjectReference
from management.services.file.access import check_file_access
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.source_reference import (
    resolve_storage_reference,
)
from management.services.knowledge_base.usage_cache import invalidate_usage_cache
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    ObjectRef,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.file_objects import file_object_ports
from infrastructure.rdb.storage_ledger import HISTORY, LEDGER
from infrastructure.storage_ledger import ledger_record_ports

logger = logging.getLogger(__name__)
DENIED = "You don't have permission to delete this file"


def _scope(records, actor):
    scope = records.scope
    if (scope.service_role != 'management' or scope.system or scope.resource_prefix
        or scope.actor_id != actor.user_id or scope.tenant_id != actor.tenant_id):
        raise ScopeDenied()


class StorageObjectDeletion:
    def __init__(self, *, reader=None, ledger_ports=ledger_record_ports, object_ports=file_object_ports):
        self.reader = reader if reader is not None else KnowledgeFileReader()
        self.ledger_ports, self.object_ports = ledger_ports, object_ports

    def _row(self, records, reference, context, *, history=False):
        terms = [Comparison('bucket_name', 'eq', reference.bucket_name), Comparison('object_name', 'eq', reference.object_name)]
        if not history:
            terms.append(Comparison('status', 'eq', 'COMMITTED'))
        page = records.query(HISTORY if history else LEDGER, RecordQuery(where=Junction('and', tuple(terms))),
                             PageRequest(limit=2), context=context)
        if page.next_cursor or len(page.items) > 1:
            raise Conflict()
        return page.items[0] if page.items else None

    def _authorize_source(self, reference, actor, context):
        try:
            with self.ledger_ports(actor.tenant_id, actor.user_id, context=context) as records:
                _scope(records, actor)
                row = self._row(records, reference, context)
            if row is None or row['tenant_id'] != actor.tenant_id or not row['index_name']:
                raise PermissionError(DENIED)
            knowledge = self.reader.knowledge(row['index_name'], actor, edit=True, context=context)
            if any(str(knowledge.get(name)) != str(row[name]) for name in ('tenant_id', 'knowledge_id', 'index_name')):
                raise PermissionError(DENIED)
            return row
        except (DeadlineExceeded, OperationCancelled):
            raise
        except Exception as error:
            # Preserve fail-closed authorization for unavailable or ambiguous ownership.
            raise PermissionError(DENIED) from error

    def _delete(self, reference, actor, context):
        with self.object_ports(actor, reference, context=context) as objects:
            _scope(objects, actor)
            if objects.scope.namespaces != {'files'}:
                raise ScopeDenied()
            receipt = objects.delete(ObjectRef('files', reference.object_name), context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if not receipt.deleted:
                raise Unavailable(operation_id=context.operation_id)

    def _release(self, reference, actor, context):
        with self.ledger_ports(actor.tenant_id, actor.user_id, context=context) as records:
            _scope(records, actor)
            with records.transaction(context=context) as tx:
                row = self._row(tx, reference, context, history=True)
                if row is None:
                    return False
                if row['delete_flag'] != 'Y' and row['status'] != 'DELETED':
                    receipt = tx.patch(LEDGER, row['storage_object_id'], FieldPatch(set_values={'status': 'DELETED'}),
                                       expected=Revision(str(row['version'])), context=context)
                    if receipt.outcome is not WriteOutcome.CONFIRMED:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    if not receipt.matched:
                        raise Conflict()
                    deleted = tx.delete(LEDGER, row['storage_object_id'], expected=receipt.revision, context=context)
                    if deleted.outcome is not WriteOutcome.CONFIRMED:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    if not deleted.deleted:
                        raise Conflict()
        try:
            invalidate_usage_cache(actor.tenant_id)
        except Exception:
            logger.exception('Failed to invalidate quota cache for tenant %s', actor.tenant_id)
        return True

    def delete(self, object_name, actor, *, context):
        context.remaining()
        if not actor.user_id or not actor.tenant_id:
            raise PermissionError(DENIED)
        source = object_name.startswith(('knowledge_base/', ASSET_OWNER_ATTACHMENTS_PREFIX + '/'))
        if source:
            reference = resolve_storage_reference(object_name)
            if reference is None:
                raise PermissionError(DENIED)
            self._authorize_source(reference, actor, context)
        else:
            if not check_file_access(object_name, actor.user_id, actor.tenant_id, required_permission='DELETE'):
                raise PermissionError(DENIED)
            reference = StorageObjectReference(environment.MINIO_DEFAULT_BUCKET, object_name)
        self._delete(reference, actor, context)
        if source:
            self._release(reference, actor, context)
        context.remaining()
        return {'success': True, 'object_name': reference.object_name}

    def compensate(self, storage, object_names, actor, *, context):
        if actor.tenant_id != storage.tenant_id or not actor.user_id:
            raise ScopeDenied()
        for name in object_names:
            context.remaining()
            reference = StorageObjectReference(storage.bucket_name, name)
            try:
                with self.ledger_ports(actor.tenant_id, actor.user_id, context=context) as records:
                    _scope(records, actor)
                    row = self._row(records, reference, context, history=True)
                if row is not None and any(row[field] != getattr(storage, field) for field in ('tenant_id', 'knowledge_id', 'index_name')):
                    raise ScopeDenied()
                self._delete(reference, actor, context)
                if not self._release(reference, actor, context):
                    logger.warning('No active storage ledger row found while compensating %s', name)
            except (DeadlineExceeded, OperationCancelled, ScopeDenied):
                raise
            except Exception:
                logger.exception('Failed to compensate newly uploaded KB source object %s', name)


async def _operation(phase, action, *args, suppress_timeout=False):
    stopped = Event()
    context = OperationContext('storage-object-' + uuid4().hex, monotonic() + 30, cancelled=stopped)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('storage-object-' + phase, action, *args, context=context,
                                      lane='control-io', owner='management.file')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('storage_object_timeout operation_id=%s phase=%s threshold_seconds=30 exception_type=%s',
                       context.operation_id, phase, type(error).__name__)
        if not suppress_timeout:
            raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        stopped.set()


async def delete_file_impl(object_name, tenant_id=None, updated_by=None):
    return await _operation('delete', StorageObjectDeletion().delete, object_name, ServicePrincipal(updated_by, tenant_id))


async def compensate_uploaded_objects(storage, names, actor):
    # Cleanup failure must keep the original upload/quota failure as the response.
    try:
        await _operation('compensate', StorageObjectDeletion().compensate, storage, names, actor, suppress_timeout=True)
    except Exception:
        logger.exception('Failed to compensate the current upload batch')
