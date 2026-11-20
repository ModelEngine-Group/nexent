# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read legacy vectors as evidence without exposing URLs, content or native drivers."""

import hashlib
import math
import re
import sys

from contracts.knowledge_maintenance import (
    LEGACY_DOCUMENTS,
    LEGACY_FILE_CHUNK_FIELDS,
    LEGACY_VECTOR_METADATA,
    LegacyVectorFinding,
    LegacyVectorPage,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery

from infrastructure.knowledge_cleanse import knowledge_resource_ports
from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.legacy_vectors import legacy_vector_records


def _scope(port, actor):
    if (port.scope.system or port.scope.service_role != 'management' or port.scope.actor_id != actor.user_id
        or port.scope.tenant_id != actor.tenant_id): raise ScopeDenied()


def standalone_candidate(source, tenant_id):
    creator = source.get('created_by')
    metadata = source.get('metadata')
    if not isinstance(creator, str) or not creator.strip() or (metadata is not None and not isinstance(metadata, dict)):
        return False
    return all(
        fields.get('tenant_id') in (None, tenant_id)
        and all(fields.get(name) is None for name in LEGACY_FILE_CHUNK_FIELDS)
        for fields in (source, metadata or {})
    )


def _finding(row, metadata, actor):
    properties = row['properties']
    item = LegacyVectorFinding(document_id_hash=hashlib.sha256(row['document_id'].encode()).hexdigest(), revision=row['revision'])
    item.standalone_candidate = standalone_candidate(properties, actor.tenant_id)
    reference = properties.get('path_or_url')
    if isinstance(reference, str) and reference:
        item.source_reference_hash = hashlib.sha256(reference.encode()).hexdigest()
    else: item.issues.append('SOURCE_REFERENCE_UNKNOWN')
    file_id = properties.get('file_id')
    if isinstance(file_id, str) and re.fullmatch(r'[0-9a-f]{32}', file_id): item.file_id = file_id
    else: item.issues.append('LEGACY_FILE_ID_UNRESOLVED')
    index = properties.get('index')
    if type(index) is int and index >= 0: item.chunk_index = index
    else: item.issues.append('CHUNK_INDEX_UNKNOWN')
    if properties.get('tenant_id') is not None and properties['tenant_id'] != actor.tenant_id:
        item.issues.append('LEGACY_DOCUMENT_TENANT_CONFLICT')
    vector = properties.get('embedding')
    if not isinstance(vector, list): item.issues.append('VECTOR_MISSING_OR_INVALID')
    else:
        item.dimensions = len(vector)
        if not vector: item.issues.append('VECTOR_DIMENSIONS_INVALID')
        elif any(type(value) not in {int, float} or abs(value) > sys.float_info.max or not math.isfinite(value) for value in vector):
            item.issues.append('VECTOR_VALUES_INVALID')
        elif all(value == 0 for value in vector): item.issues.append('VECTOR_ZERO_NORM')
        if metadata['dimensions'] is not None and len(vector) != metadata['dimensions']:
            item.issues.append('VECTOR_DIMENSION_MISMATCH')
    if metadata['dimensions'] is None: item.issues.append('LEGACY_VECTOR_MAPPING_UNKNOWN')
    return item


class LegacyVectorInspector:
    def __init__(self, *, resources=knowledge_resource_ports, vectors=legacy_vector_records, cancellation_scope=None):
        self.resources, self.vectors = resources, vectors
        self.cancellation_scope = cancellation_scope

    def scan(self, knowledge_id, actor, emit, *, page_size=100, context):
        if type(knowledge_id) is not int or knowledge_id <= 0: raise InvalidInput()
        PageRequest(limit=page_size)
        with self.resources(actor.tenant_id, actor.user_id, context=context) as resources:
            _scope(resources, actor)
            authorize = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
            knowledge = authorize.resolve_knowledge(knowledge_id, edit=True, context=context)
            if knowledge['knowledge_sources'] != 'elasticsearch': raise ScopeDenied()
            revision = knowledge_search_revision(knowledge)
            count, issues, cursor = 0, 0, None
            with self.vectors(actor, knowledge_id, knowledge['index_name'], context=context, cancellation_scope=self.cancellation_scope) as records:
                _scope(records, actor)
                metadata = records.get(LEGACY_VECTOR_METADATA, knowledge['index_name'], context=context)
                if metadata is None or metadata['collection'] != knowledge['index_name'] or metadata['tenant_id'] != actor.tenant_id:
                    raise ScopeDenied()
                total = records.count(LEGACY_DOCUMENTS, RecordQuery(), context=context)
                while True:
                    page = records.query(LEGACY_DOCUMENTS, RecordQuery(), PageRequest(limit=page_size, cursor=cursor), context=context)
                    documents = []
                    for row in page.items:
                        context.remaining()
                        if row['tenant_id'] != actor.tenant_id: raise ScopeDenied()
                        documents.append(_finding(row, metadata, actor))
                    if authorize.resolve_knowledge(knowledge_id, edit=True, context=context) != knowledge: raise Conflict()
                    context.remaining()
                    emit(LegacyVectorPage(knowledge_id=knowledge_id, index_name=knowledge['index_name'], tenant_id=actor.tenant_id,
                        actor_id=actor.user_id, knowledge_revision=revision, collection_revision=metadata['revision'],
                        collection_dimensions=metadata['dimensions'], metric=metadata['metric'], documents=documents))
                    count += len(documents); issues += sum(bool(item.issues) for item in documents)
                    cursor = page.next_cursor
                    if cursor is None: break
                if count != total: raise Conflict()
            if authorize.resolve_knowledge(knowledge_id, edit=True, context=context) != knowledge: raise Conflict()
            context.remaining()
            return {'documents': count, 'documents_with_issues': issues, 'knowledge_revision': revision,
                    'collection_revision': metadata['revision']}
