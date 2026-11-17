# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attest only a fenced KB whose exact full-file deletions are confirmed."""

from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDeleteAuthorization,
    KnowledgeBaseDeleteGrant,
)
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.admission import require_admission_actor
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery, Sort
from pydantic import ValidationError

from infrastructure.knowledge_admission import knowledge_admission_ports


def authorize_base_deletion(records, resources, request, actor, *, context):
    require_admission_actor(records, resources, actor)
    if not isinstance(request, KnowledgeBaseDeleteAuthorization):
        raise ScopeDenied()
    knowledge = KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve_knowledge(
        request.knowledge_id, edit=True, cleanup=True, context=context,
    )
    row = records.get(KB, request.knowledge_id, context=context)
    if row is None or row['index_name'] != knowledge['index_name'] or row['deletion_request'] is None:
        raise ScopeDenied()
    try:
        intent = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
    except ValidationError:
        raise Conflict() from None
    if (intent.knowledge_id != request.knowledge_id or intent.index_name != knowledge['index_name']
            or intent.user_id != actor.user_id):
        raise ScopeDenied()
    cursor = None
    while True:
        page = records.query(FILES, RecordQuery(where=Comparison('knowledge_id', 'eq', request.knowledge_id),
                                                 order_by=(Sort('file_id'),)), PageRequest(limit=200, cursor=cursor), context=context)
        for file in page.items:
            if (file['status'] != 'DELETED' or file['stage'] != 'DELETE_DONE'
                    or type(file['deleted_vector_count']) is not int or file['deleted_vector_count'] < 0):
                raise Conflict()
            try:
                deletion = KnowledgeDeletionIntent.model_validate(file['deletion_request'])
            except ValidationError:
                raise Conflict() from None
            if deletion.scope != 'full' or any(getattr(deletion, field) != file[column] for field, column in (
                ('knowledge_id', 'knowledge_id'), ('file_id', 'file_id'), ('file_version', 'source_generation'),
                ('index_name', 'index_name'), ('filename', 'original_filename'), ('object_name', 'object_name'),
            )) or deletion.index_name != intent.index_name:
                raise Conflict()
            expected = ([deletion.source.space, deletion.source.key, deletion.source.version, deletion.source.sha256]
                        if deletion.source else [None] * 4)
            if [file[name] for name in ('source_space', 'source_key', 'source_revision', 'source_sha256')] != expected:
                raise Conflict()
        if page.next_cursor is None:
            return KnowledgeBaseDeleteGrant(knowledge_id=request.knowledge_id, collection=intent.index_name)
        cursor = page.next_cursor


def authorize_knowledge_base_deletion(request, actor, *, context):
    with knowledge_admission_ports(actor, context=context, readonly=True) as (records, resources):
        return authorize_base_deletion(records, resources, request, actor, context=context)
