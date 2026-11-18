# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit source rebuilds reuse standard ingestion and never mutate legacy vectors or queues."""

import asyncio
from contextlib import asynccontextmanager

from contracts.agentos_knowledge import (
    KnowledgeBaseInspect,
    KnowledgeFileReference,
    KnowledgeSearchAuthorization,
    ObjectReference,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_ingestion import (
    KnowledgeIngestionIntent,
    LegacyIngestionSnapshot,
)
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from management.services.knowledge_base.search_authorization import (
    KnowledgeSearchAuthorizationPolicy,
)
from management.services.knowledge_base.source_inspection import (
    KnowledgeSourceInspector,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_ingestion import knowledge_ingestion_ports


@asynccontextmanager
async def _deadline(context):
    try:
        async with asyncio.timeout(context.remaining()): yield
    except (TimeoutError, RuntimeServiceTimeoutError) as error: raise DeadlineExceeded(operation_id=context.operation_id) from error


class LegacyMigrationService:
    def __init__(self, *, ports=knowledge_ingestion_ports, client=None, sources=None, parser_version=None, cancellation_scope=None):
        self.ports = ports
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.sources = sources or KnowledgeSourceInspector(cancellation_scope=cancellation_scope)
        self.parser_version = parser_version or environment.KNOWLEDGE_CLEANSE_PARSER_VERSION

    @staticmethod
    async def _blocking(method, *args):
        return await run_blocking('legacy-knowledge-migration', method, *args, lane='control-io', owner='management.knowledge.maintenance')

    def _selected(self, knowledge_id, file_id, actor, context):
        KnowledgeFileReference(knowledge_id=knowledge_id, file_id=file_id, file_version=0)
        context.remaining()
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (records, resources):
            if (records.scope.system or records.scope.service_role != 'management'
                or records.scope.actor_id != actor.user_id or records.scope.tenant_id != actor.tenant_id): raise ScopeDenied()
            row = IngestionJournal(records).record(file_id, context=context)
            if row['knowledge_id'] != knowledge_id: raise ScopeDenied()
            resource = KnowledgeSearchAuthorizationPolicy(resources, user_id=actor.user_id).authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[knowledge_id]), edit=True, context=context).knowledge_bases[0]
            return row, resource

    @staticmethod
    def _eligible(row):
        if (row['ingestion_request'] is not None or row['deletion_request'] is not None
            or row['status'] not in {'UPLOADED', 'COMPLETED', 'FAILED'}
            or any(row[name] is not None for name in ('process_task_id', 'forward_task_id', 'parent_task_id'))):
            raise Conflict()

    def _source(self, plan, actor, context):
        page = self.sources.page(plan.knowledge_id, actor, file_id=plan.file_id, page_size=1, context=context)
        if (page.knowledge_revision != plan.legacy_snapshot.resource_revision or page.next_cursor is not None or len(page.files) != 1):
            raise Conflict()
        finding = page.files[0]
        if (finding.file_id != plan.file_id or finding.lifecycle_revision != plan.legacy_snapshot.lifecycle_revision
            or finding.source_generation != plan.file_version or finding.issues or finding.candidate_source != plan.source):
            raise Conflict()

    async def _empty_runtime(self, plan, actor):
        cursor, revision, seen = None, None, set()
        while True:
            state = await self.client.inspect_knowledge_base(KnowledgeBaseInspect(knowledge_id=plan.knowledge_id,
                expected_revision=plan.legacy_snapshot.resource_revision, page_size=1000, cursor=cursor), actor.user_id, actor.tenant_id)
            if (state.knowledge_id != plan.knowledge_id or state.knowledge_revision != plan.legacy_snapshot.resource_revision
                or state.embedding_model_id != plan.embedding_model.model_id or revision is not None and state.manifest_revision != revision
                or any(item.file_id == plan.file_id for item in state.files)): raise Conflict()
            revision = state.manifest_revision
            if state.next_cursor is None: return
            if state.next_cursor in seen: raise Conflict()
            seen.add(state.next_cursor); cursor = state.next_cursor

    async def _model(self, model_id, actor):
        model = await self.client.get_model(model_id, user_id=actor.user_id, tenant_id=actor.tenant_id)
        if (model.model_id != model_id or model.model_type not in {'embedding', 'multi_embedding'}
            or model.embedding_dimensions is None): raise Conflict()
        return model

    async def plan(self, knowledge_id, file_id, actor, *, legacy_quiesced, context):
        if legacy_quiesced is not True: raise InvalidInput()
        async with _deadline(context):
            row, resource = await self._blocking(self._selected, knowledge_id, file_id, actor, context)
            self._eligible(row)
            metadata = await self._model(resource.embedding_model_id, actor)
            plan = KnowledgeIngestionIntent(knowledge_id=knowledge_id, file_id=file_id, file_version=row['source_generation'],
                user_id=actor.user_id, attempt=row['processing_attempt']+1, filename=row['original_filename'], parser_version=self.parser_version,
                source=ObjectReference(space=row['source_space'], key=row['source_key'], version=row['source_revision'], sha256=row['source_sha256']),
                embedding_model={'model_id': metadata.model_id, 'revision': metadata.revision},
                legacy_snapshot=LegacyIngestionSnapshot.capture(row, resource_revision=resource.revision, legacy_quiesced=True))
            await self._blocking(self._source, plan, actor, context)
            await self._empty_runtime(plan, actor)
            final, final_resource = await self._blocking(self._selected, knowledge_id, file_id, actor, context)
            if final != row or final_resource != resource or await self._model(resource.embedding_model_id, actor) != metadata: raise Conflict()
            return plan

    def _change(self, plan, actor, context, action):
        context.remaining()
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (records, resources):
            journal = IngestionJournal(records)
            row = journal.record(plan.file_id, context=context)
            resource = KnowledgeSearchAuthorizationPolicy(resources, user_id=actor.user_id).authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[plan.knowledge_id]), edit=True, context=context).knowledge_bases[0]
            if resource.revision != plan.legacy_snapshot.resource_revision or resource.embedding_model_id != plan.embedding_model.model_id:
                raise Conflict()
            KnowledgeCleanseAuthorization(resources, user_id=actor.user_id).authorize(plan.cleanse_request(), context=context)
            return getattr(journal, action)(plan, row, context=context)

    def _plan(self, plan, actor, *, check_parser=True):
        if not isinstance(plan, KnowledgeIngestionIntent) or plan.legacy_snapshot is None: raise InvalidInput()
        KnowledgeIngestionIntent.model_validate_json(plan.model_dump_json())
        if plan.user_id != actor.user_id or plan.legacy_snapshot.tenant_id != actor.tenant_id: raise ScopeDenied()
        if check_parser and plan.parser_version != self.parser_version: raise Conflict()

    async def inspect(self, plan, actor, *, context):
        self._plan(plan, actor, check_parser=False)
        def observe():
            context.remaining()
            with self.ports(actor.tenant_id, actor.user_id, context=context) as (records, resources):
                if (records.scope.system or records.scope.actor_id != actor.user_id or records.scope.tenant_id != actor.tenant_id): raise ScopeDenied()
                row = IngestionJournal(records).record(plan.file_id, context=context)
                if row['knowledge_id'] != plan.knowledge_id: raise ScopeDenied()
                KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve_knowledge(plan.knowledge_id, edit=True, context=context)
                return row
        async with _deadline(context):
            return await self._blocking(observe)

    async def admit(self, plan, actor, *, context):
        self._plan(plan, actor)
        async with _deadline(context):
            row, resource = await self._blocking(self._selected, plan.knowledge_id, plan.file_id, actor, context)
            if row['ingestion_request'] is not None:
                return await self._blocking(self._change, plan, actor, context, 'admit_legacy')
            self._eligible(row)
            if resource.revision != plan.legacy_snapshot.resource_revision: raise Conflict()
            model = await self._model(plan.embedding_model.model_id, actor)
            if model.revision != plan.embedding_model.revision: raise Conflict()
            await self._blocking(self._source, plan, actor, context)
            await self._empty_runtime(plan, actor)
            return await self._blocking(self._change, plan, actor, context, 'admit_legacy')

    async def restore(self, plan, actor, *, context):
        self._plan(plan, actor)
        async with _deadline(context):
            return await self._blocking(self._change, plan, actor, context, 'restore_legacy')

    async def execute(self, plan, actor, *, context, coordinator=None):
        async with _deadline(context):
            await self.admit(plan, actor, context=context)
            if coordinator is None:
                from management.services.knowledge_base.ingestion_dispatch import (
                    default_coordinator,
                )
                coordinator = default_coordinator()
            return await coordinator.advance(plan.file_id, actor, context=context)
