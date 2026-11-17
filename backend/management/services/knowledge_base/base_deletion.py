# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reserve KB deletion only after serialized upload admission is quiescent."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteAuthorization,
    KnowledgeBaseDeleteLookup,
    KnowledgeBaseDeleteState,
    knowledge_base_deletion_id,
)
from management.services.knowledge_base.admission import (
    change_knowledge_admission,
    require_admission_actor,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery, Revision, Sort


class KnowledgeBaseDeletionJournal:
    """Persist the parent phase before its single collection deletion request."""

    def __init__(self, records, resources, actor):
        require_admission_actor(records, resources, actor)
        self.records, self.resources, self.actor = records, resources, actor

    def load(self, knowledge_id, *, context):
        require_admission_actor(self.records, self.resources, self.actor)
        knowledge = KnowledgeFileAuthorization(self.resources, user_id=self.actor.user_id).resolve_knowledge(
            knowledge_id, edit=True, cleanup=True, context=context,
        )
        row = self.records.get(KB, knowledge_id, context=context)
        if row is None or row['index_name'] != knowledge['index_name'] or row['tenant_id'] != self.actor.tenant_id:
            raise ScopeDenied()
        self.intent(row)
        return row

    def intent(self, row):
        intent = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
        if (intent.user_id != self.actor.user_id or row['tenant_id'] != self.actor.tenant_id):
            raise ScopeDenied()
        if intent.knowledge_id != row['knowledge_id'] or intent.index_name != row['index_name']:
            raise Conflict()
        return intent

    def payload(self, row):
        intent = self.intent(row)
        return KnowledgeBaseDelete(knowledge_id=intent.knowledge_id,
                                   idempotency_key='kb-delete-' + str(intent.knowledge_id))

    def lookup(self, row, *, context=None):
        if context is not None:
            current = self.load(row['knowledge_id'], context=context)
            if current['version'] != row['version']:
                raise Conflict()
        payload = self.payload(row)
        return KnowledgeBaseDeleteLookup(knowledge_id=payload.knowledge_id, job_id=knowledge_base_deletion_id(
            payload, self.actor.tenant_id, self.actor.user_id,
        ))

    def _change(self, transaction, previous, phase, *, context):
        knowledge = KnowledgeFileAuthorization(self.resources, user_id=self.actor.user_id).resolve_knowledge(
            previous['knowledge_id'], edit=True, cleanup=True, context=context,
        )
        current = transaction.get(KB, previous['knowledge_id'], context=context)
        if current is None or current['version'] != previous['version'] or current['index_name'] != knowledge['index_name']:
            raise Conflict()
        intent = self.intent(current).model_copy(update={'phase': phase})
        return change_knowledge_admission(transaction, previous, {'deletion_request': intent.model_dump(mode='json')},
                                           expected=Revision(str(previous['version'])), context=context)

    def begin_collection(self, row, *, context):
        from management.services.knowledge_base.base_deletion_authorization import (
            authorize_base_deletion,
        )

        if self.intent(row).phase != 'files':
            raise Conflict()
        with self.records.transaction(context=context) as transaction:
            authorize_base_deletion(transaction, self.resources,
                                    KnowledgeBaseDeleteAuthorization(knowledge_id=row['knowledge_id']),
                                    self.actor, context=context)
            reserved = self._change(transaction, row, 'collection_submitting', context=context)
        return reserved, self.payload(reserved)

    def observe_collection(self, row, state, *, context):
        if self.intent(row).phase != 'collection_submitting':
            raise Conflict()
        if not isinstance(state, KnowledgeBaseDeleteState) or any(
            getattr(state, field) != getattr(self.lookup(row), field) for field in ('knowledge_id', 'job_id')
        ):
            raise ScopeDenied()
        # Always check live DAC, including when the remote task is still pending.
        current = self.load(row['knowledge_id'], context=context)
        if current['version'] != row['version']:
            raise Conflict()
        if state.status != 'deleted' or state.physical_cleanup_complete is not True:
            return current
        with self.records.transaction(context=context) as transaction:
            return self._change(transaction, row, 'metadata_pending', context=context)


def request_knowledge_base_deletion(records, resources, index_name, actor, *, context):
    require_admission_actor(records, resources, actor)
    authorization = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
    knowledge = authorization._one('cleanse_knowledge', 'index_name', index_name, context)
    authorization.resolve_knowledge(knowledge['knowledge_id'], edit=True, cleanup=True, context=context)
    with records.transaction(context=context) as transaction:
        row = transaction.get(KB, knowledge['knowledge_id'], context=context)
        if row is None or row['index_name'] != index_name:
            raise ScopeDenied()
        if row['deletion_request'] is not None:
            original = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
            if original.knowledge_id != row['knowledge_id'] or original.index_name != index_name:
                raise Conflict()
            return row
        intent = KnowledgeBaseDeletionIntent(knowledge_id=row['knowledge_id'], index_name=index_name, user_id=actor.user_id)
        reserved = change_knowledge_admission(transaction, row, {'deletion_request': intent.model_dump(mode='json')},
                                               expected=Revision(str(row['version'])), context=context)
        cursor = None
        while True:
            page = transaction.query(FILES, RecordQuery(
                fields=('file_id', 'original_filename', 'status', 'stage', 'deletion_request'),
                where=Comparison('knowledge_id', 'eq', row['knowledge_id']), order_by=(Sort('file_id'),),
            ), PageRequest(limit=200, cursor=cursor), context=context)
            blocking = [file for file in page.items if file['status'] in {
                'UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING', 'DELETE_REQUESTED',
            } or file['deletion_request'] is not None and file['stage'] not in {'SOURCE_DELETED', 'DELETE_DONE'}]
            if blocking:
                raise AppException(ErrorCode.KNOWLEDGE_DELETE_BLOCKED, details={
                    'index_name': index_name, 'blocking_files': [
                        {'file_id': file['file_id'], 'file_name': file['original_filename'] or file['file_id'],
                         'status': file['status']} for file in blocking
                    ],
                })
            if page.next_cursor is None:
                return reserved
            cursor = page.next_cursor
