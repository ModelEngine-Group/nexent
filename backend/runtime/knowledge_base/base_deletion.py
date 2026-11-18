# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence a single collection removal after all Runtime file writers have ended."""

from contracts.knowledge_base_deletion import (
    BASE_DELETION_DATASET as BASE,
)
from contracts.knowledge_base_deletion import (
    RUNTIME_FILES as FILES,
)
from contracts.knowledge_base_deletion import (
    RUNTIME_JOBS as JOBS,
)
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDeleteLookup,
    KnowledgeBaseDeleteState,
    knowledge_base_deletion_id,
)
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)
from runtime.knowledge_base.chunk_journal import (
    ChunkMutationJournal,
    assert_knowledge_open,
)


class KnowledgeBaseDeletionJournal:
    def __init__(self, records, actor, grant):
        if (records.scope.system or records.scope.service_role != 'runtime'
                or records.scope.actor_id != actor.user_id or records.scope.tenant_id != actor.tenant_id):
            raise ScopeDenied()
        self.records, self.actor, self.grant = records, actor, grant

    def ready(self, records, *, context):
        ChunkMutationJournal(records, self.grant.knowledge_id).assert_drained(context=context)
        unended = records.query(JOBS, RecordQuery(where=Junction('and', (
            Comparison('knowledge_id', 'eq', self.grant.knowledge_id), Comparison('writer_ended', 'eq', False),
        ))), PageRequest(limit=1), context=context)
        if unended.items:
            raise Conflict()
        cursor = None
        while True:
            page = records.query(FILES, RecordQuery(where=Comparison('knowledge_id', 'eq', self.grant.knowledge_id),
                                                     order_by=(Sort('record_id'),)), PageRequest(limit=200, cursor=cursor), context=context)
            if any(row['tombstone_version'] < row['latest_version'] or any(row[name] is not None for name in (
                'active_job_id', 'visible_job_id', 'visible_version', 'visible_generation',
            )) for row in page.items):
                raise Conflict()
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    def _identity(self, row, lookup):
        if row is None:
            raise NotFound()
        if (row['tenant_id'] != self.actor.tenant_id or row['user_id'] != self.actor.user_id
                or row['knowledge_id'] != lookup.knowledge_id or lookup.knowledge_id != self.grant.knowledge_id):
            raise ScopeDenied()
        if row['collection'] != self.grant.collection:
            raise Conflict()
        return row

    def record(self, lookup, *, context):
        return self._identity(self.records.get(BASE, lookup.job_id, context=context), lookup)

    def reserve(self, request, *, context):
        if request.knowledge_id != self.grant.knowledge_id:
            raise ScopeDenied()
        lookup = KnowledgeBaseDeleteLookup(knowledge_id=request.knowledge_id,
                                           job_id=knowledge_base_deletion_id(request, self.actor.tenant_id, self.actor.user_id))
        existing = self.records.get(BASE, lookup.job_id, context=context)
        if existing is not None:
            return self._identity(existing, lookup), False
        with self.records.transaction(context=context) as tx:
            ChunkMutationJournal(tx, self.grant.knowledge_id)._locked_state(tx, context)
            existing = tx.get(BASE, lookup.job_id, context=context)
            if existing is not None:
                return self._identity(existing, lookup), False
            assert_knowledge_open(tx, request.knowledge_id, context=context)
            self.ready(tx, context=context)
            row = tx.create(BASE, {'job_id': lookup.job_id, 'knowledge_id': request.knowledge_id,
                                  'user_id': self.actor.user_id, 'collection': self.grant.collection,
                                  'status': 'deleting'}, context=context)
        return row, True

    @staticmethod
    def state(row):
        return KnowledgeBaseDeleteState(knowledge_id=row['knowledge_id'], job_id=row['job_id'],
                                        status='deleted' if row['status'] == 'deleted' else 'cleanup_pending',
                                        physical_cleanup_complete=row['status'] == 'deleted')

    def finish(self, row, *, physical_absence_confirmed, context):
        if physical_absence_confirmed is not True:
            raise Conflict()
        with self.records.transaction(context=context) as tx:
            ChunkMutationJournal(tx, self.grant.knowledge_id)._locked_state(tx, context)
            lookup = KnowledgeBaseDeleteLookup(knowledge_id=row['knowledge_id'], job_id=row['job_id'])
            current = self._identity(tx.get(BASE, row['job_id'], context=context), lookup)
            self.ready(tx, context=context)
            if current['status'] == 'deleted':
                return self.state(current)
            receipt = tx.patch(BASE, row['job_id'], FieldPatch(set_values={'status': 'deleted'}),
                               expected=Revision(str(row['revision'])), context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if not receipt.matched:
                raise Conflict()
        return self.state({**row, 'status': 'deleted'})
