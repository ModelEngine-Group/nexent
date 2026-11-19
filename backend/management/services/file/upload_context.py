# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve an upload's tenant-owned KB context before lifecycle admission."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.environment import MINIO_DEFAULT_BUCKET
from contracts.knowledge import KnowledgeStorageContext
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
)

from infrastructure.upload_context import DATASET, upload_context_ports

logger = logging.getLogger(__name__)


class UploadContextReader:
    def __init__(self, *, ports=upload_context_ports, bucket_name=MINIO_DEFAULT_BUCKET):
        self.ports, self.bucket = ports, bucket_name

    def read(self, index_name, actor, *, context):
        if not index_name:
            return None
        context.remaining()
        with self.ports(actor, context=context) as (identity, open_records):
            quota_identity_roles(identity, actor, context=context)
            records = open_records()
            require_quota_scope(records, actor, actor.tenant_id)
            page = records.query(DATASET, RecordQuery(where=Junction('and', (
                Comparison('index_name', 'eq', index_name), Comparison('delete_flag', 'ne', 'Y'),
            ))), PageRequest(limit=1), context=context)
            row = page.items[0] if page.items else None
            quota_identity_roles(identity, actor, context=context)
            context.remaining()
            if row is None or row.get('knowledge_id') is None or row['tenant_id'] != actor.tenant_id:
                return None
            if not self.bucket:
                raise RuntimeError('MinIO default bucket is not configured')
            return KnowledgeStorageContext(actor.tenant_id, int(row['knowledge_id']), index_name,
                                           self.bucket, row.get('ingroup_permission'))


async def resolve_upload_context(index_name, actor):
    if not index_name:
        return None
    cancelled = Event()
    context = OperationContext('upload-context-' + uuid4().hex, monotonic() + 10, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('upload-context', UploadContextReader().read, index_name, actor,
                                      context=context, lane='control-io', owner='management.file')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('upload_context_timeout operation_id=%s phase=metadata threshold_seconds=10 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
