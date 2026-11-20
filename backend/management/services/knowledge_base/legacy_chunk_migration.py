# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Move an exact legacy standalone chunk through the standard Runtime mutation path."""

import hashlib
import re

from contracts.agentos import MAX_REQUEST_BYTES
from contracts.constants import environment
from contracts.knowledge_chunk_mutation import ChunkMutationIntent, ChunkMutationLookup
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from contracts.knowledge_maintenance import LEGACY_DOCUMENTS, LEGACY_VECTOR_METADATA
from management.services.knowledge_base.file_authorization import KnowledgeFileAuthorization
from management.services.knowledge_base.legacy_vectors import _scope, standalone_candidate
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, InvalidInput, NotFound, OutcomeUnknown, ScopeDenied
from pydantic import ValidationError

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_cleanse import knowledge_resource_ports
from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.legacy_vectors import legacy_vector_records


class LegacyChunkMigration:
    def __init__(self, *, client=None, resources=knowledge_resource_ports, vectors=legacy_vector_records,
                 cancellation_scope=None):
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.resources, self.vectors = resources, vectors
        self.cancellation_scope = cancellation_scope

    def _source(self, knowledge_id, document_id, collection_revision, document_revision, actor, context):
        with self.resources(actor.tenant_id, actor.user_id, context=context) as resources:
            _scope(resources, actor)
            policy = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
            resource = policy.resolve_knowledge(knowledge_id, edit=True, context=context)
            if resource['knowledge_sources'] != 'elasticsearch':
                raise ScopeDenied()
            collection = resource['index_name']
            with self.vectors(actor, knowledge_id, collection, context=context,
                              cancellation_scope=self.cancellation_scope) as records:
                _scope(records, actor)
                metadata = records.get(LEGACY_VECTOR_METADATA, collection, context=context)
                if metadata is None or metadata['tenant_id'] != actor.tenant_id or metadata['collection'] != collection:
                    raise ScopeDenied()
                if metadata['revision'] != collection_revision:
                    raise Conflict()
                row = records.get(LEGACY_DOCUMENTS, document_id, context=context)
                if row is None:
                    raise NotFound()
                if row['tenant_id'] != actor.tenant_id or row['document_id'] != document_id:
                    raise ScopeDenied()
                properties = row['properties']
                if row['revision'] != document_revision or not standalone_candidate(properties, actor.tenant_id):
                    raise Conflict()
                vector = properties.get('embedding')
                if vector is not None and (
                    not isinstance(vector, list) or len(vector) != metadata['dimensions'] or metadata['metric'] != 'cosine'
                ):
                    raise Conflict()
            if policy.resolve_knowledge(knowledge_id, edit=True, context=context) != resource:
                raise Conflict()
            return knowledge_search_revision(resource), properties

    @staticmethod
    def _changes(source):
        if 'content' not in source:
            raise InvalidInput()
        return {
            'content': source['content'],
            'filename': source['filename'] if isinstance(source.get('filename'), str) else None,
            'supplied_embedding': source.get('embedding'),
            'location': {PUBLIC_CHUNK_SOURCE_KEY: {
                key: value for key, value in source.items() if key not in {'content', 'embedding'}
            }},
        }

    async def migrate(self, knowledge_id, document_id, collection_revision, document_revision, actor, *,
                      legacy_quiesced, context):
        if (legacy_quiesced is not True or type(knowledge_id) is not int or knowledge_id <= 0 or not isinstance(document_id, str)
            or not document_id or len(document_id.encode('utf-8')) > 512
            or not isinstance(collection_revision, str) or not isinstance(document_revision, str)
            or not re.fullmatch(r'[0-9a-f]{64}', collection_revision)
            or not re.fullmatch(r'[0-9]{1,20}:[1-9][0-9]{0,19}', document_revision)):
            raise InvalidInput()

        async def current_source():
            return await run_blocking('legacy-chunk-source', self._source, knowledge_id, document_id,
                collection_revision, document_revision, actor, context, lane='control-io', owner=__name__)

        resource_revision, properties = await current_source()
        lookup = ChunkMutationLookup(knowledge_id=knowledge_id, chunk_id=document_id, operation='create',
                                     resource_revision=resource_revision)
        target = await self.client.inspect_knowledge_chunk(lookup, actor.user_id, actor.tenant_id)
        if target.chunk is not None or any(getattr(target, key) != value for key, value in lookup.model_dump().items()):
            raise Conflict()
        if await current_source() != (resource_revision, properties):
            raise Conflict()
        digest = hashlib.sha256(document_id.encode('utf-8')).hexdigest()
        try:
            intent = ChunkMutationIntent(knowledge_id=knowledge_id, chunk_id=document_id, operation='create',
                request_key=f'legacy-chunk:{collection_revision}:{digest}', resource_revision=resource_revision,
                expected_change_epoch=target.change_epoch, changes=self._changes(properties))
        except (ValidationError, ValueError):
            raise InvalidInput() from None
        if len(intent.model_dump_json().encode('utf-8')) > MAX_REQUEST_BYTES:
            raise InvalidInput()
        state = await self.client.mutate_knowledge_chunk(intent, actor.user_id, actor.tenant_id)
        if (state.knowledge_id, state.chunk_id, state.operation) != (knowledge_id, document_id, 'create'):
            raise Conflict()
        if state.status != 'completed' or not state.writer_ended:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if state.count_delta != 1 or state.commit_epoch is None or state.commit_epoch <= target.change_epoch:
            raise Conflict()
        published = await self.client.inspect_knowledge_chunk(lookup, actor.user_id, actor.tenant_id)
        if (published.chunk is None or published.chunk.file_id is not None or published.generation != state.mutation_id
            or any(getattr(published, key) != value for key, value in lookup.model_dump().items())
            or published.change_epoch < state.commit_epoch
            or published.chunk.content != intent.changes['content']
            or published.chunk.location != intent.changes['location']):
            raise Conflict()
        context.remaining()
        return {'document_id_hash': digest, 'document_revision': document_revision,
                'collection_revision': collection_revision, 'commit_epoch': state.commit_epoch, 'chunk_migrated': True}
