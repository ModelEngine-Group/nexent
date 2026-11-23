# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve public aliases under live DAC before installing a deletion intent."""

from contracts.knowledge_deletion import DELETION_DATASET, KnowledgeDeletionIntent
from contracts.knowledge_ingestion import (
    ACTIVE_LEGACY_FILE_IDS,
    KnowledgeIngestionIntent,
    is_canonical_file_id,
    is_historical_file_id,
)
from management.services.knowledge_base.deletion_journal import DeletionJournal
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_selection import parse_file_selections
from management.services.knowledge_base.source_deletion import SourceDeletion
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery, Sort
from pydantic import ValidationError


class DocumentLedgerNotFound(ValueError):
    pass


def _selection(path):
    if not isinstance(path, str) or not 0 < len(path) <= 2048:
        raise ValueError('path_or_url or file_id is required')
    # Local aliases are compared as strings, never opened on the filesystem.
    choices = [Comparison('local_source_path', 'eq', path), Comparison('object_name', 'eq', path)]
    if '://' in path and not path.startswith('s3://'):
        return Junction('or', tuple(choices))
    keys, qualified = parse_file_selections([path])
    if keys:
        choices.extend(Comparison(field, 'in', keys) for field in ('source_key', 'object_name'))
    if path.startswith('/') and '/' in path[1:]:
        bucket, key = path[1:].split('/', 1)
        qualified.setdefault(bucket, []).append(key)
    for bucket, names in qualified.items():
        choices.append(Junction('and', (
            Comparison('bucket_name', 'eq', bucket),
            Junction('or', tuple(Comparison(field, 'in', names) for field in ('source_key', 'object_name'))),
        )))
    return Junction('or', tuple(choices))


def _verified_source(row):
    """Reject unconverted historical layouts before any deletion is admitted."""
    if row['parent_task_id']:
        raise Unavailable()
    raw = row['ingestion_request']
    needs_ingestion = row['status'] in {'COMPLETED', 'PROCESSING', 'FORWARDING'}
    if raw is None and (needs_ingestion or row['process_task_id'] or row['forward_task_id']):
        raise Unavailable()
    if raw is not None:
        try:
            ingestion = KnowledgeIngestionIntent.model_validate(raw)
        except ValidationError:
            raise Unavailable() from None
        if any(getattr(ingestion, field) != row[column] for field, column in (
            ('knowledge_id', 'knowledge_id'), ('file_id', 'file_id'), ('file_version', 'source_generation'),
        )):
            raise Unavailable()
    else:
        ingestion = None
    if row['status'] == 'UPLOADING' and row['stage'].startswith('SOURCE_'):
        # The journal validates the original publisher; it alone can bind an unknown write.
        if ingestion is not None:
            raise Unavailable()
        return None
    values = [row[name] for name in ('source_space', 'source_key', 'source_revision', 'source_sha256')]
    if values == [None] * 4:
        if row['object_name'] is not None or ingestion is not None:
            raise Unavailable()
        return None
    try:
        source = DeletionJournal._published_source(row, historical_intent=ingestion)
    except Conflict:
        raise Unavailable() from None
    if (not source.version.startswith(('etag:', 'version:')) or not row['bucket_name']
            or ingestion is not None and ingestion.source != source):
        raise Unavailable()
    return source


def _existing(row, scope, actor):
    try:
        intent = KnowledgeDeletionIntent.model_validate(row['deletion_request'])
    except ValidationError:
        raise Conflict() from None
    # Validate the server-owned snapshot without borrowing its user's authority.
    if any(getattr(intent, field) != row[column] for field, column in (
        ('knowledge_id', 'knowledge_id'), ('file_id', 'file_id'), ('file_version', 'source_generation'),
        ('index_name', 'index_name'), ('object_name', 'object_name'),
    )):
        raise Conflict()
    waiting = intent.scope == 'full' and DeletionJournal.awaiting_source(row)
    if not waiting and intent.filename != row['original_filename']:
        raise Conflict()
    live = [row[name] for name in ('source_space', 'source_key', 'source_revision', 'source_sha256')]
    expected = [intent.source.space, intent.source.key, intent.source.version, intent.source.sha256] if intent.source else [None] * 4
    if intent.scope == 'source_only' and row['stage'] == 'SOURCE_DELETED':
        expected = [None] * 4
    if live != expected and not (waiting and intent.source is None):
        raise Conflict()
    if intent.scope == 'source_only' and row['stage'] == 'SOURCE_DELETED' and scope == 'full':
        if row['status'] != 'COMPLETED' or any(row[name] is not None for name in (
            'source_space', 'source_key', 'source_revision', 'source_sha256',
        )):
            raise Conflict()
        return intent.model_copy(update={'scope': 'full', 'source': None, 'user_id': actor.user_id}), True
    if intent.scope != scope:
        raise Conflict()
    terminal = row['stage'] in {'DELETE_DONE', 'SOURCE_DELETED'}
    if row['stage'] == 'SOURCE_DELETED' and (intent.scope != 'source_only' or row['status'] != 'COMPLETED'):
        raise Conflict()
    if row['stage'] == 'DELETE_DONE' and (row['status'] != 'DELETED' or row['deleted_vector_count'] is None):
        raise Conflict()
    return intent, not terminal and intent.user_id == actor.user_id


def prepare_deletion(records, resources, index_name, path, scope, actor, *, file_id=None, context):
    """Return a snapshot and whether this actor may advance it; perform no writes."""
    if scope not in {'full', 'source_only'}:
        raise ValueError('Unsupported document deletion scope')
    for port in (records, resources):
        if (port.scope.system or port.scope.service_role != 'management'
                or port.scope.actor_id != actor.user_id or port.scope.tenant_id != actor.tenant_id):
            raise ScopeDenied()
    authorization = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
    knowledge = authorization._one('cleanse_knowledge', 'index_name', index_name, context)
    authorization.resolve_knowledge(knowledge['knowledge_id'], edit=True, cleanup=True, context=context)
    terms = [Comparison('knowledge_id', 'eq', knowledge['knowledge_id']), Comparison('index_name', 'eq', index_name)]
    if file_id is not None:
        if not is_canonical_file_id(file_id):
            if not is_historical_file_id(file_id) or ACTIVE_LEGACY_FILE_IDS not in records.scope.namespaces:
                raise ValueError('Invalid file_id')
            alias = records.get(ACTIVE_LEGACY_FILE_IDS, file_id, context=context)
            if alias is None or alias['knowledge_id'] != knowledge['knowledge_id']:
                raise ValueError('Invalid file_id')
            file_id = alias['standard_file_id']
        terms.append(Comparison('file_id', 'eq', file_id))
    else:
        terms.append(_selection(path))
    page = records.query(DELETION_DATASET, RecordQuery(
        where=Junction('and', tuple(terms)), order_by=(Sort('update_time', descending=True), Sort('file_id')),
    ), PageRequest(limit=1), context=context)
    if not page.items:
        raise DocumentLedgerNotFound('Document not found')
    row = page.items[0]
    if scope == 'source_only' and row['status'] != 'COMPLETED':
        raise ValueError('Cannot delete source file before processing is completed')
    if scope == 'source_only' and row['object_name'] is None:
        raise ValueError('A file without a storage object can only use full deletion')
    if row['deletion_request'] is not None:
        intent, advance = _existing(row, scope, actor)
        return row, intent, advance
    source = _verified_source(row)
    try:
        intent = KnowledgeDeletionIntent(
            knowledge_id=row['knowledge_id'], file_id=row['file_id'], file_version=row['source_generation'],
            user_id=actor.user_id, scope=scope, index_name=index_name, filename=row['original_filename'],
            object_name=row['object_name'], source=source,
        )
    except ValidationError:
        raise Unavailable() from None
    if source is not None and (
        row['source_upload_sha256'] != source.sha256 or not row['upload_owner_service']
    ):
        # Without the old publisher receipt, prove current accounting before any delete is admitted.
        try:
            ledger = SourceDeletion._ledger(records, row, intent, context)
        except Conflict:
            raise Unavailable() from None
        if ledger is None or ledger['status'] != 'COMMITTED':
            raise Unavailable()
    return row, intent, True
