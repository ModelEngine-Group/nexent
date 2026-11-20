# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collect Runtime manifest and configured-model evidence exclusively through AgentOS."""

import asyncio
import json

from contracts.agentos_knowledge import (
    KnowledgeBaseInspect,
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionsDescribe
from contracts.knowledge_maintenance import RuntimeInspectionPage
from management.services.knowledge_base.search_authorization import (
    KnowledgeSearchAuthorizationPolicy,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_cleanse import knowledge_resource_ports


class RuntimeKnowledgeInspector:
    def __init__(self, *, client=None, resources=knowledge_resource_ports):
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.resources = resources

    def _resolve(self, knowledge_id, actor, *, context):
        context.remaining()
        with self.resources(actor.tenant_id, actor.user_id, context=context) as records:
            scope = records.scope
            if scope.system or scope.service_role != 'management' or scope.tenant_id != actor.tenant_id or scope.actor_id != actor.user_id:
                raise ScopeDenied()
            grant = KnowledgeSearchAuthorizationPolicy(records, user_id=actor.user_id).authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[knowledge_id]), context=context, edit=True)
            return grant.knowledge_bases[0]

    async def _resource(self, knowledge_id, actor, context):
        return await run_blocking('knowledge-runtime-inventory-scope', self._resolve, knowledge_id, actor,
            context=context, lane='control-io', owner='management.knowledge.maintenance')

    async def _model(self, model_id, actor):
        try:
            metadata = await self.client.get_model(model_id, actor.user_id, actor.tenant_id)
        except RuntimeUpstreamError as error:
            try: missing = error.status_code == 404 and json.loads(error.content).get('code') == 'MODEL_NOT_FOUND'
            except (ValueError, AttributeError): missing = False
            if missing: return None
            raise
        if metadata.model_id != model_id: raise Conflict()
        return metadata

    async def scan(self, knowledge_id, actor, emit, *, page_size=100, include_vector_media=False, context):
        try:
            async with asyncio.timeout(context.remaining()):
                return await self._scan(knowledge_id, actor, emit, page_size=page_size, include_vector_media=include_vector_media, context=context)
        except (TimeoutError, RuntimeServiceTimeoutError) as error:
            raise DeadlineExceeded(operation_id=context.operation_id) from error

    async def _scan(self, knowledge_id, actor, emit, *, page_size, include_vector_media, context):
        if type(knowledge_id) is not int or knowledge_id <= 0: raise InvalidInput()
        PageRequest(limit=page_size)
        resource = await self._resource(knowledge_id, actor, context)
        model = await self._model(resource.embedding_model_id, actor)
        issues = []
        if model is None: issues.append('MODEL_NOT_FOUND')
        elif model.model_type not in {'embedding', 'multi_embedding'}: issues.append('MODEL_NOT_EMBEDDING')
        elif model.embedding_dimensions is None: issues.append('MODEL_DIMENSIONS_UNKNOWN')
        dimensions = model.embedding_dimensions if model is not None and model.model_type in {'embedding', 'multi_embedding'} else None
        binding = ModelVersion(model_id=model.model_id, revision=model.revision) if model is not None else None
        cursor, revision, count, visible, seen = None, None, 0, 0, set()
        while True:
            context.remaining()
            state = await self.client.inspect_knowledge_base(KnowledgeBaseInspect(knowledge_id=knowledge_id,
                expected_revision=resource.revision, page_size=page_size, cursor=cursor), actor.user_id, actor.tenant_id)
            if (state.knowledge_id != knowledge_id or state.knowledge_revision != resource.revision
                or state.embedding_model_id != resource.embedding_model_id or revision is not None and state.manifest_revision != revision):
                raise Conflict()
            for item in state.files:
                if item.file_id in seen: raise Conflict()
                seen.add(item.file_id)
                visible += item.visible_version is not None
            if await self._resource(knowledge_id, actor, context) != resource: raise Conflict()
            context.remaining()
            emit(RuntimeInspectionPage(**state.model_dump(), tenant_id=actor.tenant_id, actor_id=actor.user_id,
                index_name=resource.collection, embedding_model=binding, embedding_dimensions=dimensions, issues=issues))
            revision = state.manifest_revision; count += len(state.files)
            if state.next_cursor is None: break
            if state.next_cursor == cursor: raise Conflict()
            cursor = state.next_cursor
        if await self._resource(knowledge_id, actor, context) != resource: raise Conflict()
        if await self._model(resource.embedding_model_id, actor) != model: raise Conflict()
        media = {}
        if include_vector_media:
            response = await self.client.describe_knowledge_collections(KnowledgeCollectionsDescribe(
                knowledge_ids=[knowledge_id], expected_revisions={knowledge_id: resource.revision},
                include_vector_media=True), actor.user_id, actor.tenant_id)
            if len(response.items) != 1:
                raise Conflict()
            item = response.items[0]
            if (item.knowledge_id != knowledge_id or item.expected_revision != resource.revision
                or item.present and item.vector_media is None):
                raise Conflict()
            if await self._resource(knowledge_id, actor, context) != resource:
                raise Conflict()
            media = {"vector_collection_present": item.present, "vector_media": (
                item.vector_media.model_dump(mode="json") if item.vector_media else None)}
        context.remaining()
        return {'files': count, 'visible_files': visible, 'manifest_revision': revision,
            'knowledge_revision': resource.revision, 'embedding_model': binding.model_dump() if binding else None,
            'embedding_dimensions': dimensions, 'issues': issues, **media}
