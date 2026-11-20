# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Inspect historical source evidence without changing identities or replaying old tasks."""

import hashlib
import re

from contracts.agentos_knowledge import ObjectReference
from contracts.constants import environment
from contracts.knowledge_maintenance import (
    INSPECTION_FILES,
    INSPECTION_LEDGER,
    SourceFinding,
    SourceInspectionPage,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, InvalidInput, NotFound, ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    ObjectRef,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
)

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.object_storage.composition import bind_source_objects
from infrastructure.source_inspection import source_inspection_ports


def _scope(port, actor):
    scope = port.scope
    if scope.system or scope.service_role != 'management' or scope.tenant_id != actor.tenant_id or scope.actor_id != actor.user_id:
        raise ScopeDenied()


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _legacy_s3_key(row, bucket):
    prefix = f's3://{bucket}/'
    alias = row['object_name'] or ''
    if row['bucket_name'] != bucket or not alias.startswith(prefix):
        return None
    key = alias[len(prefix):]
    if not key or any(char in key for char in '\\:%?#\x00') or any(part in {'', '.', '..'} for part in key.split('/')):
        return None
    return key


class KnowledgeSourceInspector:
    def __init__(self, *, bucket=None, max_bytes=None, ports=source_inspection_ports, objects=bind_source_objects, cancellation_scope=None):
        self.bucket = environment.MINIO_DEFAULT_BUCKET if bucket is None else bucket
        self.max_bytes = environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES if max_bytes is None else max_bytes
        if not self.bucket or type(self.max_bytes) is not int or self.max_bytes <= 0:
            raise InvalidInput()
        self.ports, self.objects = ports, objects
        self.cancellation_scope = cancellation_scope

    def _ledger(self, records, row, context):
        key = _legacy_s3_key(row, self.bucket) or row['object_name']
        page = records.query(INSPECTION_LEDGER, RecordQuery(where=Junction('and', (
            Comparison('bucket_name', 'eq', row['bucket_name']), Comparison('object_name', 'eq', key)))),
            PageRequest(limit=2), context=context)
        if len(page.items) > 1 or page.next_cursor:
            raise Conflict()
        return page.items[0] if page.items else None

    def _alias_conflict(self, records, row, context):
        key = _legacy_s3_key(row, self.bucket)
        if key is None or row['storage_object_id'] is None:
            return False
        matches = records.query(INSPECTION_FILES, RecordQuery(where=Junction('or', (
            Comparison('object_name', 'eq', key), Comparison('source_key', 'eq', key),
            Comparison('storage_object_id', 'eq', row['storage_object_id'])))),
            PageRequest(limit=2), context=context)
        return bool(matches.next_cursor or any(item['file_id'] != row['file_id'] for item in matches.items))

    def _source(self, row, ledger, item, actor, context, *, alias_conflict):
        alias_key = _legacy_s3_key(row, self.bucket)
        key = alias_key or row['source_key'] or row['object_name']
        if row['bucket_name'] != self.bucket:
            item.issues.append('SOURCE_BUCKET_UNSUPPORTED')
        elif (row['object_name'] or '').startswith('s3://') and alias_key is None:
            item.issues.append('SOURCE_ALIAS_UNRESOLVED')
        elif not key or '://' in key or '\\' in key or ':' in key or any(part in {'', '.', '..'} for part in key.split('/')):
            item.issues.append('SOURCE_ALIAS_UNRESOLVED' if key else 'LOCAL_SOURCE_UNBOUND' if row['local_source_path'] else 'SOURCE_UNBOUND')
        elif row['source_key'] and row['object_name'] and row['source_key'] != (alias_key or row['object_name']):
            item.issues.append('SOURCE_KEY_CONFLICT')
        elif alias_conflict:
            item.issues.append('SOURCE_ALIAS_CONFLICT')
        elif alias_key is not None and row['storage_object_id'] is None:
            item.issues.append('SOURCE_ALIAS_UNRESOLVED')
        elif row['source_space'] not in {None, 'files'}:
            item.issues.append('SOURCE_SPACE_UNSUPPORTED')
        elif ledger is None:
            item.issues.append('LEDGER_UNPROVEN')
        elif ledger['status'] != 'COMMITTED' or ledger['delete_flag'] != 'N':
            item.issues.append('LEDGER_INACTIVE')
        elif (ledger['tenant_id'] != actor.tenant_id or ledger['knowledge_id'] != row['knowledge_id']
              or ledger['index_name'] != row['index_name'] or row['storage_object_id'] not in {None, ledger['storage_object_id']}):
            item.issues.append('LEDGER_LINK_MISMATCH')
        else:
            revision = row['source_revision']
            if revision is not None and (not isinstance(revision, str) or not revision.startswith(('etag:', 'version:')) or len(revision) > 128):
                item.issues.append('SOURCE_REVISION_INVALID')
                return
            objects = self.objects(actor.tenant_id, actor.user_id, key, self.bucket, writable=False)
            try:
                _scope(objects, actor)
                ref = ObjectRef('files', key, Revision(revision) if revision else None)
                metadata = objects.stat(ref, context=context)
                if metadata.ref.space != 'files' or metadata.ref.key != key or metadata.ref.version is None:
                    raise ScopeDenied()
                if revision is not None and metadata.ref.version != ref.version:
                    raise Conflict()
                if type(metadata.size) is not int or metadata.size < 0:
                    item.issues.append('SOURCE_METADATA_INVALID')
                    return
                item.observed_size = metadata.size
                if metadata.size > self.max_bytes:
                    item.issues.append('SOURCE_TOO_LARGE')
                    return
                digest, size = hashlib.sha256(), 0
                with objects.open_read(metadata.ref, context=context) as stream:
                    token = self.cancellation_scope.register_closer(stream.close) if self.cancellation_scope else None
                    try:
                        while True:
                            context.remaining()
                            block = stream.read(min(64 * 1024, self.max_bytes - size + 1))
                            if not block:
                                break
                            size += len(block)
                            if size > metadata.size or size > self.max_bytes:
                                item.issues.append('SOURCE_SIZE_MISMATCH')
                                return
                            digest.update(block)
                    finally:
                        if token is not None:
                            self.cancellation_scope.unregister_closer(token)
                if size != metadata.size or ledger['raw_bytes'] != size or row['file_size'] not in {None, size}:
                    item.issues.append('SOURCE_SIZE_MISMATCH')
                for expected in (row['source_sha256'], row['source_upload_sha256'], metadata.sha256):
                    if expected is not None and expected != digest.hexdigest():
                        item.issues.append('SOURCE_HASH_MISMATCH')
                        break
                item.candidate_source = ObjectReference(space='files', key=key, version=metadata.ref.version.value, sha256=digest.hexdigest())
                item.candidate_storage_object_id = ledger['storage_object_id']
                if {'SOURCE_SIZE_MISMATCH', 'SOURCE_HASH_MISMATCH'}.intersection(item.issues):
                    return
                if alias_key is not None:
                    item.issues.append('SOURCE_ALIAS_PROVEN')
                version = metadata.ref.version.value
                if version.startswith('version:') and version not in {'version:', 'version:null'}:
                    item.source_deletion_evidence = 'immutable_version'
                elif version.startswith('etag:') or version == 'version:null':
                    item.source_deletion_evidence = (
                        'confirmed_publisher'
                        if row['upload_owner_service'] and row['source_upload_sha256'] == digest.hexdigest()
                        else 'publisher_evidence_missing'
                    )
            except NotFound:
                item.issues.append('SOURCE_MISSING')
            except Conflict:
                item.issues.append('SOURCE_REVISION_MISMATCH')
            finally:
                objects.close()

    def page(self, knowledge_id, actor, *, cursor=None, page_size=100, file_id=None, context):
        if type(knowledge_id) is not int or knowledge_id <= 0:
            raise InvalidInput()
        page_request = PageRequest(limit=page_size, cursor=cursor)
        if file_id is not None and (not isinstance(file_id, str) or len(file_id) > 64): raise InvalidInput()
        with self.ports(actor, knowledge_id, context=context) as (records, resources):
            _scope(records, actor); _scope(resources, actor)
            authorize = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
            resource = authorize.resolve_knowledge(knowledge_id, edit=True, context=context)
            if resource['knowledge_sources'] != 'elasticsearch':
                raise ScopeDenied()
            where = Comparison('knowledge_id', 'eq', knowledge_id)
            if file_id is not None: where = Junction('and', (where, Comparison('file_id', 'eq', file_id)))
            rows = records.query(INSPECTION_FILES, RecordQuery(where=where,
                order_by=(Sort('file_id'),)), page_request, context=context)
            findings, evidence = [], []
            for row in rows.items:
                context.remaining()
                if row['tenant_id'] != actor.tenant_id or row['knowledge_id'] != knowledge_id or row['index_name'] != resource['index_name']:
                    raise ScopeDenied()
                item = SourceFinding(file_id=row['file_id'], lifecycle_revision=_number(row['version']), source_generation=_number(row['source_generation']))
                if not re.fullmatch(r'[0-9a-f]{32}', row['file_id']): item.issues.append('FILE_ID_NONCANONICAL')
                if item.lifecycle_revision is None: item.issues.append('LIFECYCLE_VERSION_UNKNOWN')
                if item.source_generation is None: item.issues.append('SOURCE_GENERATION_UNKNOWN')
                if not row['source_revision']: item.issues.append('SOURCE_REVISION_UNPINNED')
                if not row['source_sha256']: item.issues.append('SOURCE_HASH_UNPINNED')
                if not row['source_space']: item.issues.append('SOURCE_SPACE_UNPINNED')
                if not row['source_key']: item.issues.append('SOURCE_KEY_UNPINNED')
                if row['storage_object_id'] is None: item.issues.append('LEDGER_LINK_UNBOUND')
                if row['file_size'] is None: item.issues.append('SOURCE_SIZE_UNPINNED')
                if (row['status'] in {'UPLOADING', 'PROCESSING', 'FORWARDING'} or row['ingestion_request'] is None
                    and any(row[name] for name in ('process_task_id', 'forward_task_id', 'parent_task_id'))):
                    item.issues.append('LEGACY_TASK_UNVERIFIED')
                ledger = self._ledger(records, row, context)
                alias_conflict = self._alias_conflict(records, row, context)
                evidence.append((row, ledger, alias_conflict))
                if row['deletion_request'] is not None:
                    item.issues.append('DELETION_PENDING')
                else:
                    self._source(row, ledger, item, actor, context, alias_conflict=alias_conflict)
                findings.append(item)
            if authorize.resolve_knowledge(knowledge_id, edit=True, context=context) != resource:
                raise Conflict()
            for row, ledger, alias_conflict in evidence:
                if (records.get(INSPECTION_FILES, row['file_id'], context=context) != row
                    or self._ledger(records, row, context) != ledger
                    or self._alias_conflict(records, row, context) != alias_conflict):
                    raise Conflict()
            context.remaining()
            return SourceInspectionPage(knowledge_id=knowledge_id, index_name=resource['index_name'], tenant_id=actor.tenant_id,
                actor_id=actor.user_id, knowledge_revision=knowledge_search_revision(resource), files=findings, next_cursor=rows.next_cursor)
