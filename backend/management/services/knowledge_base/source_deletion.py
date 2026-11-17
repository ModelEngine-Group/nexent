# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete one fenced source once, then atomically release its charge and lifecycle."""

from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge import STORAGE_LEDGER_HISTORY_DATASET as HISTORY
from management.services.file.source_publish import validate_scope
from management.services.knowledge_base.deletion_journal import (
    DeletionJournal,
    DeletionPhaseChanged,
)
from management.services.knowledge_base.usage_cache import invalidate_usage_cache
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    ObjectRef,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)


class SourceDeletion:
    def __init__(self, records, objects):
        self.journal = DeletionJournal(records)
        if objects is not None:
            validate_scope(records, objects)
        self.records, self.objects = records, objects

    @staticmethod
    def _ledger(records, row, intent, context):
        if row['object_name'] is None:
            if row['storage_object_id'] is not None or intent.source is not None:
                raise Conflict()
            return None
        page = records.query(HISTORY, RecordQuery(where=Junction('and', (
            Comparison('bucket_name', 'eq', row['bucket_name']),
            Comparison('object_name', 'eq', row['object_name']),
        ))), PageRequest(limit=2), context=context)
        if len(page.items) > 1 or page.next_cursor:
            raise Conflict()
        ledger = page.items[0] if page.items else None
        if ledger is None:
            if row['storage_object_id'] is not None or intent.source is not None:
                raise Conflict()
            return None
        if (any(ledger[name] != row[name] for name in ('tenant_id', 'knowledge_id', 'index_name', 'bucket_name', 'object_name'))
                or row['storage_object_id'] != ledger['storage_object_id']
                or row['file_size'] != ledger['raw_bytes'] or ledger['status'] not in {'COMMITTED', 'DELETED'}
                or ledger['status'] == 'COMMITTED' and ledger['delete_flag'] != 'N'):
            raise Conflict()
        return ledger

    def _finish(self, row, context):
        try:
            with self.records.transaction(context=context) as tx:
                journal = DeletionJournal(tx)
                current = journal.record(row['file_id'], context=context)
                if current['version'] != row['version']:
                    raise DeletionPhaseChanged()
                intent = journal.request(current)
                ledger = self._ledger(tx, current, intent, context)
                if ledger is not None and ledger['status'] == 'COMMITTED':
                    receipt = tx.patch(LEDGER, ledger['storage_object_id'], FieldPatch(set_values={'status': 'DELETED'}),
                                       expected=Revision(str(ledger['version'])), context=context)
                    if receipt.outcome is not WriteOutcome.CONFIRMED:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    if not receipt.matched:
                        raise Conflict()
                    deleted = tx.delete(LEDGER, ledger['storage_object_id'], expected=receipt.revision, context=context)
                    if deleted.outcome is not WriteOutcome.CONFIRMED:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    if not deleted.deleted:
                        raise Conflict()
                return journal.finish_source(current, physical_absence_confirmed=True, context=context)
        finally:
            invalidate_usage_cache(row['tenant_id'])

    def _stat(self, row, context):
        if row['object_name'] is None:
            if self.objects is not None:
                raise Conflict()
            return None
        if self.objects is None:
            raise Conflict()
        try:
            return self.objects.stat(ObjectRef('files', row['object_name']), context=context)
        except NotFound:
            return None

    def advance(self, row, *, context):
        context.remaining()
        intent = self.journal.request(row)
        allowed = {'DELETE_ACCEPTED'} if intent.scope == 'source_only' else {'DELETE_SOURCE_PENDING'}
        self.journal._phase(row, allowed | {'DELETE_SOURCE_DELETING'})
        self._ledger(self.records, row, intent, context)
        metadata = self._stat(row, context)
        if row['stage'] == 'DELETE_SOURCE_DELETING':
            # A previous write may have reached storage; subsequent calls only observe absence.
            return row if metadata is not None else self._finish(row, context)
        if metadata is not None:
            source = intent.source
            if (source is None or source.key != row['object_name'] or metadata.ref.space != source.space
                    or metadata.ref.key != source.key or metadata.ref.version != Revision(source.version)
                    or metadata.sha256 != source.sha256 or metadata.size != row['file_size']):
                raise Conflict()
            if not source.version.startswith('version:') and (
                not source.version.startswith('etag:') or row['source_upload_sha256'] != source.sha256
                or not row['upload_owner_service'] or row['storage_object_id'] is None
            ):
                # Unversioned deletion needs the closed single-publisher path, never a guessed legacy owner.
                raise OutcomeUnknown(operation_id=context.operation_id)
        row = self.journal.begin_source(row, context=context)
        if metadata is not None:
            target = metadata.ref if intent.source.version.startswith('version:') else ObjectRef('files', intent.source.key)
            receipt = self.objects.delete(target, context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.deleted:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if self._stat(row, context) is not None:
                return row
        return self._finish(row, context)
