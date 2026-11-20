# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete one fenced source once, then commit its charge, file and KB metadata together."""

import hashlib
from datetime import UTC, datetime

from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge import STORAGE_LEDGER_HISTORY_DATASET as HISTORY
from contracts.knowledge_deletion import (
    DELETION_KNOWLEDGE_DATASET,
    NULL_SOURCE_VERSION,
    is_immutable_source_version,
)
from contracts.knowledge_ingestion import KnowledgeIngestionIntent
from management.services.file.source_publish import validate_scope
from management.services.knowledge_base.deletion_journal import (
    DeletionJournal,
    DeletionPhaseChanged,
)
from management.services.knowledge_base.usage_cache import invalidate_usage_cache
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
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
from pydantic import ValidationError


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
                if intent.scope == 'full' and (intent.object_name is not None or current['deleted_vector_count'] > 0):
                    knowledge = tx.get(DELETION_KNOWLEDGE_DATASET, current['knowledge_id'], context=context)
                    if knowledge is None or knowledge['tenant_id'] != current['tenant_id'] or knowledge['index_name'] != current['index_name']:
                        raise ScopeDenied()
                    receipt = tx.patch(DELETION_KNOWLEDGE_DATASET, current['knowledge_id'],
                                       FieldPatch(set_values={'last_doc_update_time': datetime.now(UTC).isoformat()}),
                                       expected=Revision(str(knowledge['version'])), context=context)
                    if receipt.outcome is not WriteOutcome.CONFIRMED:
                        raise OutcomeUnknown(operation_id=context.operation_id)
                    if not receipt.matched:
                        raise DeletionPhaseChanged()
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

    def _matches_digest(self, row, source, metadata, context):
        if metadata.sha256 is not None:
            return metadata.sha256 == source.sha256
        if not is_immutable_source_version(source.version) or row['ingestion_request'] is None:
            return False
        try:
            ingestion = KnowledgeIngestionIntent.model_validate(row['ingestion_request'])
        except ValidationError:
            return False
        if not self.journal._verified_historical_version(row, source, ingestion):
            return False
        size, digest = 0, hashlib.sha256()
        # Old uploads may lack SHA metadata. Read only the immutable version selected for deletion.
        with self.objects.open_read(metadata.ref, context=context) as stream:
            while True:
                context.remaining()
                block = stream.read(min(64 * 1024, metadata.size - size + 1))
                if not block:
                    break
                size += len(block)
                if size > metadata.size:
                    return False
                digest.update(block)
        return size == metadata.size and digest.hexdigest() == source.sha256

    def advance(self, row, *, context):
        context.remaining()
        intent = self.journal.request(row)
        if intent.scope == 'full' and row['deleted_vector_count'] is None:
            raise Conflict()
        allowed = {'DELETE_ACCEPTED'} if intent.scope == 'source_only' else {'DELETE_SOURCE_PENDING'}
        self.journal._phase(row, allowed | {'DELETE_SOURCE_DELETING'})
        source = intent.source
        if source is not None and source.version == NULL_SOURCE_VERSION:
            raise OutcomeUnknown(operation_id=context.operation_id)
        immutable = source is not None and is_immutable_source_version(source.version)
        self._ledger(self.records, row, intent, context)
        metadata = self._stat(row, context)
        if row['stage'] == 'DELETE_SOURCE_DELETING':
            # A previous write may have reached storage; subsequent calls only observe absence.
            return row if metadata is not None else self._finish(row, context)
        if metadata is not None:
            if (source is None or source.key != row['object_name'] or metadata.ref.space != source.space
                    or metadata.ref.key != source.key or metadata.ref.version != Revision(source.version)
                    or metadata.size != row['file_size'] or not self._matches_digest(row, source, metadata, context)):
                raise Conflict()
            if not immutable and (not source.version.startswith('etag:') or row['source_upload_sha256'] != source.sha256
                                  or not row['upload_owner_service'] or row['storage_object_id'] is None):
                # Unversioned deletion needs the closed single-publisher path, never a guessed legacy owner.
                raise OutcomeUnknown(operation_id=context.operation_id)
        row = self.journal.begin_source(row, context=context)
        if metadata is not None:
            target = metadata.ref if immutable else ObjectRef('files', source.key)
            receipt = self.objects.delete(target, context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.deleted:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if self._stat(row, context) is not None:
                return row
        return self._finish(row, context)
