# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reserve KB deletion only after serialized upload admission is quiescent."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from management.services.knowledge_base.admission import (
    change_knowledge_admission,
    require_admission_actor,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery, Revision, Sort


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
