# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence one collection setup against existing file/chunk writers and deletion."""

from contracts.knowledge_base_deletion import RUNTIME_JOBS as JOBS
from contracts.knowledge_chunk_mutation import STATES
from contracts.knowledge_collections import CollectionSetup
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
)
from pydantic import ValidationError
from runtime.knowledge_base.chunk_journal import (
    ChunkMutationJournal,
    assert_knowledge_open,
)


class KnowledgeCollectionJournal:
    def __init__(self, records, knowledge_id):
        self.records = records
        self.chunks = ChunkMutationJournal(records, knowledge_id)
        if JOBS not in records.scope.namespaces:
            raise ScopeDenied()

    @staticmethod
    def _setup(row):
        raw = row.get('collection_setup') if row is not None else None
        if raw is None:
            return None
        try:
            return CollectionSetup.model_validate(raw)
        except ValidationError as error:
            raise Conflict() from error

    def inspect(self, *, context):
        return self._setup(self.chunks._state(self.records, context))

    def reserve(self, setup, *, context):
        if not isinstance(setup, CollectionSetup) or setup.phase != 'reserved' or setup.writer_ended:
            raise InvalidInput()
        setup = CollectionSetup.model_validate(setup.model_dump())
        if setup.actor_id != self.records.scope.actor_id:
            raise ScopeDenied()
        with self.records.transaction(context=context) as tx:
            row = self.chunks._locked_state(tx, context)
            assert_knowledge_open(tx, self.chunks.knowledge_id, context=context)
            ChunkMutationJournal(tx, self.chunks.knowledge_id).assert_drained(context=context)
            writers = tx.query(JOBS, RecordQuery(where=Junction('and', (
                Comparison('knowledge_id', 'eq', self.chunks.knowledge_id),
                Comparison('writer_ended', 'eq', False),
            ))), PageRequest(limit=1), context=context)
            if writers.items:
                raise Conflict()
            self.chunks._patch(tx, STATES, row, {'collection_setup': setup.model_dump(mode='json')}, context)

    def _owned(self, tx, operation_id, context):
        row = self.chunks._locked_state(tx, context)
        current = self._setup(row)
        if current is None or current.operation_id != operation_id:
            raise Conflict()
        if current.actor_id != self.records.scope.actor_id:
            raise ScopeDenied()
        return row, current

    def begin(self, operation_id, *, context):
        with self.records.transaction(context=context) as tx:
            row, current = self._owned(tx, operation_id, context)
            if current.phase != 'reserved':
                raise Conflict()
            current = current.model_copy(update={'phase': 'writing'})
            self.chunks._patch(tx, STATES, row, {'collection_setup': current.model_dump(mode='json')}, context)

    def unknown(self, operation_id, *, writer_ended, context):
        if type(writer_ended) is not bool:
            raise InvalidInput()
        with self.records.transaction(context=context) as tx:
            row, current = self._owned(tx, operation_id, context)
            if current.phase not in {'writing', 'unknown'}:
                raise Conflict()
            current = current.model_copy(update={'phase': 'unknown', 'writer_ended': current.writer_ended or writer_ended})
            self.chunks._patch(tx, STATES, row, {'collection_setup': current.model_dump(mode='json')}, context)

    def finish(self, operation_id, *, confirmed, context):
        if type(confirmed) is not bool:
            raise InvalidInput()
        with self.records.transaction(context=context) as tx:
            row, current = self._owned(tx, operation_id, context)
            if current.phase == 'unknown' or confirmed and current.phase != 'writing':
                raise Conflict()
            self.chunks._patch(tx, STATES, row, FieldPatch(set_values={'collection_setup': None},
                increments={'epoch': 1} if confirmed else {}), context)
