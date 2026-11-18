# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the Runtime manifest catalog through AgentOS without inferring physical vector state."""

import asyncio
import hashlib
import json
import logging
import re
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeBaseInspect,
    KnowledgeBaseState,
    KnowledgeManifest,
    KnowledgeSearchAuthorization,
)
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from nexent.core.concurrency import RunCancellationScope, run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)
from pydantic import Field, ValidationError

from infrastructure.knowledge_runtime import knowledge_manifest_ports
from infrastructure.rdb.knowledge_jobs import FILES

logger = logging.getLogger(__name__)
FIELDS = ('record_id', 'tenant_id', 'knowledge_id', 'file_id', 'latest_version', 'active_job_id',
          'visible_job_id', 'visible_version', 'visible_generation', 'tombstone_version', 'revision')


class _Cursor(Contract):
    after: str = Field(pattern=r'^[0-9a-f]{32}$')
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    binding: str = Field(pattern=r'^[0-9a-f]{64}$')


def _read(records, actor, knowledge_id, after, limit, *, context):
    scope = records.scope
    if scope.system or scope.service_role != 'runtime' or scope.tenant_id != actor.tenant_id or scope.actor_id != actor.user_id:
        raise ScopeDenied()
    digest = hashlib.sha256(str(knowledge_id).encode())
    selected, previous = [], None
    while True:
        terms = [Comparison('knowledge_id', 'eq', knowledge_id)]
        if previous is not None: terms.append(Comparison('record_id', 'gt', previous))
        page = records.query(FILES, RecordQuery(fields=FIELDS, where=Junction('and', tuple(terms)),
            order_by=(Sort('record_id'),)), PageRequest(limit=500), context=context)
        for row in page.items:
            context.remaining()
            if row['tenant_id'] != actor.tenant_id or row['knowledge_id'] != knowledge_id: raise ScopeDenied()
            key = row['record_id']
            if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key) or previous is not None and key <= previous: raise Conflict()
            previous = key
            try:
                item = KnowledgeManifest(file_id=row['file_id'], latest_version=row['latest_version'],
                    visible_version=row['visible_version'], visible_generation=row['visible_generation'],
                    tombstone_version=row['tombstone_version'], record_revision=row['revision'],
                    upload_job_reference_present=row['active_job_id'] is not None)
            except ValidationError as error: raise Conflict() from error
            if (row['visible_job_id'] is None) != (row['visible_version'] is None): raise Conflict()
            digest.update(json.dumps([row[name] for name in FIELDS], separators=(',', ':')).encode())
            if limit and (after is None or key > after) and len(selected) <= limit: selected.append((key, item))
        if len(page.items) < 500: return digest.hexdigest(), selected


class KnowledgeManifestService:
    def __init__(self, authorization_client, *, ports=knowledge_manifest_ports, operation_seconds=30):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180: raise InvalidInput()
        self.client, self.ports, self.operation_seconds = authorization_client, ports, operation_seconds

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_search(
            KnowledgeSearchAuthorization(knowledge_ids=[request.knowledge_id]), actor.user_id, actor.tenant_id)
        if len(grant.knowledge_bases) != 1 or grant.knowledge_bases[0].knowledge_id != request.knowledge_id: raise ScopeDenied()
        if grant.knowledge_bases[0].revision != request.expected_revision: raise Conflict()
        return grant

    async def inspect(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeBaseInspect): raise InvalidInput()
        binding = hashlib.sha256(json.dumps([actor.user_id, actor.tenant_id, request.knowledge_id,
            request.expected_revision], separators=(',', ':')).encode()).hexdigest()
        try: cursor = _Cursor.model_validate_json(request.cursor) if request.cursor is not None else None
        except ValidationError as error: raise InvalidInput() from error
        if cursor is not None and cursor.binding != binding: raise ScopeDenied()
        cancellation = RunCancellationScope()
        context = context or OperationContext('knowledge-manifest-' + uuid4().hex, monotonic() + self.operation_seconds,
                                              cancelled=cancellation.stop_event)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(request, actor)
                def snapshot():
                    context.remaining()
                    with self.ports(actor, request.knowledge_id, context=context) as records:
                        revision, items = _read(records, actor, request.knowledge_id, cursor.after if cursor else None,
                                                request.page_size, context=context)
                        if cursor is not None and cursor.revision != revision: raise Conflict()
                        final, _ = _read(records, actor, request.knowledge_id, None, 0, context=context)
                        if final != revision: raise Conflict()
                    context.remaining()
                    return revision, items
                revision, items = await run_blocking('knowledge-manifest', snapshot, lane='control-io', owner='runtime.knowledge_base')
                if await self._grant(request, actor) != grant: raise Conflict()
                next_cursor = _Cursor(after=items[request.page_size-1][0], revision=revision, binding=binding).model_dump_json() if len(items) > request.page_size else None
                return KnowledgeBaseState(knowledge_id=request.knowledge_id, knowledge_revision=request.expected_revision,
                    manifest_revision=revision, embedding_model_id=grant.knowledge_bases[0].embedding_model_id,
                    files=[item for _, item in items[:request.page_size]], next_cursor=next_cursor)
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_manifest_timeout operation_id=%s phase=catalog threshold_seconds=%s exception_type=%s',
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally: cancellation.cancel()
