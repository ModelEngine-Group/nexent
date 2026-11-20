# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit source rebuilds reuse standard ingestion and never mutate legacy vectors or queues."""

import asyncio
from contextlib import asynccontextmanager

from contracts.agentos_knowledge import (
    KnowledgeBaseInspect,
    KnowledgeJobInspection,
    KnowledgeSearchAuthorization,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_ingestion import (
    KnowledgeIngestionIntent,
    LegacyIngestionSnapshot,
    LegacySourceBinding,
    LegacySourceState,
    canonical_legacy_file_id,
    is_canonical_file_id,
    is_historical_file_id,
)
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from management.services.knowledge_base.legacy_task_archive import (
    task_references,
    verify_task_archive,
)
from management.services.knowledge_base.search_authorization import (
    KnowledgeSearchAuthorizationPolicy,
)
from management.services.knowledge_base.source_inspection import (
    KnowledgeSourceInspector,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
)

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_ingestion import (
    activate_legacy_identity,
    knowledge_ingestion_ports,
    legacy_file_id_occupied,
    reserve_legacy_identity,
    restore_legacy_identity,
)
from infrastructure.legacy_tasks import legacy_task_records

SOURCE_BINDING_ISSUES = frozenset({'SOURCE_SPACE_UNPINNED', 'SOURCE_KEY_UNPINNED', 'SOURCE_REVISION_UNPINNED',
    'SOURCE_HASH_UNPINNED', 'SOURCE_SIZE_UNPINNED', 'LEDGER_LINK_UNBOUND', 'SOURCE_ALIAS_PROVEN'})


@asynccontextmanager
async def _deadline(context):
    try:
        async with asyncio.timeout(context.remaining()): yield
    except (TimeoutError, RuntimeServiceTimeoutError) as error: raise DeadlineExceeded(operation_id=context.operation_id) from error


class LegacyMigrationService:
    def __init__(self, *, ports=knowledge_ingestion_ports, client=None, sources=None, parser_version=None,
                 cancellation_scope=None, tasks=legacy_task_records, file_id_occupied=legacy_file_id_occupied,
                 reserve_identity=reserve_legacy_identity, activate_identity=activate_legacy_identity,
                 restore_identity=restore_legacy_identity):
        self.ports = ports
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.sources = sources or KnowledgeSourceInspector(cancellation_scope=cancellation_scope)
        self.parser_version = parser_version or environment.KNOWLEDGE_CLEANSE_PARSER_VERSION
        self.tasks, self.cancellation_scope = tasks, cancellation_scope
        self.file_id_occupied = file_id_occupied
        self.reserve_identity = reserve_identity
        self.activate_identity = activate_identity
        self.restore_identity = restore_identity

    @staticmethod
    async def _blocking(method, *args):
        return await run_blocking('legacy-knowledge-migration', method, *args, lane='control-io', owner='management.knowledge.maintenance')

    def _selected(self, knowledge_id, file_id, actor, context):
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
    def _eligible(row, *, archived_tasks=False):
        if (row['ingestion_request'] is not None or row['deletion_request'] is not None
            or row['status'] not in {'UPLOADED', 'COMPLETED', 'FAILED'}
            or task_references(row) and not archived_tasks):
            raise Conflict()
        if archived_tasks and not task_references(row): raise InvalidInput()

    def _task_evidence(self, row, resource, actor, path, context, expected_hash=None):
        if path is None:
            if task_references(row) or expected_hash is not None: raise Conflict()
            return None
        return verify_task_archive(path, row, resource, actor, task_records=self.tasks, context=context,
            cancellation_scope=self.cancellation_scope, expected_hash=expected_hash)

    def _source_evidence(self, row, resource_revision, actor, context, binding=False, archived_tasks=False,
                         map_legacy_file_id=False):
        page = self.sources.page(row['knowledge_id'], actor, file_id=row['file_id'], page_size=1, context=context)
        if (page.knowledge_revision != resource_revision or page.next_cursor is not None or len(page.files) != 1):
            raise Conflict()
        finding = page.files[0]
        allowed = {'LEGACY_TASK_UNVERIFIED'} if archived_tasks else set()
        if binding: allowed.update(SOURCE_BINDING_ISSUES)
        if map_legacy_file_id: allowed.add("FILE_ID_NONCANONICAL")
        if (finding.file_id != row['file_id'] or finding.lifecycle_revision != row['version']
            or finding.source_generation != row['source_generation'] or set(finding.issues) - allowed or finding.candidate_source is None):
            raise Conflict()
        source = finding.candidate_source
        for name, expected in (('source_space', source.space), ('source_key', source.key),
                               ('source_revision', source.version), ('source_sha256', source.sha256)):
            if (not binding or row[name] is not None) and row[name] != expected: raise Conflict()
        if binding:
            if not SOURCE_BINDING_ISSUES.intersection(finding.issues): raise InvalidInput()
            if finding.candidate_storage_object_id is None or finding.observed_size is None: raise Conflict()
        return finding

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

    def _require_unoccupied(self, actor, file_id, context):
        if self.file_id_occupied(actor, file_id, context=context):
            raise Conflict()

    async def plan(self, knowledge_id, file_id, actor, *, legacy_quiesced, context, task_archive=None,
                   bind_observed_source=False, map_legacy_file_id=False):
        if (
            legacy_quiesced is not True or type(bind_observed_source) is not bool
            or type(map_legacy_file_id) is not bool or type(knowledge_id) is not int or knowledge_id <= 0
            or not is_historical_file_id(file_id) or map_legacy_file_id == is_canonical_file_id(file_id)
        ):
            raise InvalidInput()
        target_id = canonical_legacy_file_id(actor.tenant_id, knowledge_id, file_id) if map_legacy_file_id else file_id
        async with _deadline(context):
            row, resource = await self._blocking(self._selected, knowledge_id, file_id, actor, context)
            self._eligible(row, archived_tasks=task_archive is not None)
            if map_legacy_file_id:
                await self._blocking(self._require_unoccupied, actor, target_id, context)
            archive_hash = await self._blocking(self._task_evidence, row, resource, actor, task_archive, context)
            metadata = await self._model(resource.embedding_model_id, actor)
            finding = await self._blocking(self._source_evidence, row, resource.revision, actor, context,
                bind_observed_source, archive_hash is not None, map_legacy_file_id)
            binding = LegacySourceBinding(previous=LegacySourceState.capture(row), storage_object_id=finding.candidate_storage_object_id,
                file_size=finding.observed_size,
                previous_object_name=row['object_name'] if 'SOURCE_ALIAS_PROVEN' in finding.issues else None,
            ) if bind_observed_source else None
            plan = KnowledgeIngestionIntent(knowledge_id=knowledge_id, file_id=target_id, file_version=row['source_generation'],
                user_id=actor.user_id, attempt=row['processing_attempt']+1, filename=row['original_filename'], parser_version=self.parser_version,
                source=finding.candidate_source,
                embedding_model={'model_id': metadata.model_id, 'revision': metadata.revision},
                legacy_snapshot=LegacyIngestionSnapshot.capture(row, resource_revision=resource.revision,
                    legacy_quiesced=True, task_archive_sha256=archive_hash, source_binding=binding,
                    previous_file_id=file_id if map_legacy_file_id else None))
            await self._empty_runtime(plan, actor)
            final, final_resource = await self._blocking(self._selected, knowledge_id, file_id, actor, context)
            if final != row or final_resource != resource or await self._model(resource.embedding_model_id, actor) != metadata: raise Conflict()
            if map_legacy_file_id:
                await self._blocking(self._require_unoccupied, actor, target_id, context)
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
            authorization = KnowledgeCleanseAuthorization(resources, user_id=actor.user_id)
            if plan.legacy_snapshot.source_binding is not None and row['ingestion_request'] is None:
                file, _ = authorization.resolve(plan.cleanse_request(), edit=True, context=context)
                if any(file[name] != row[name] for name in ('source_space','source_key','source_revision','source_sha256')):
                    raise Conflict()
            else:
                authorization.authorize(plan.cleanse_request(), context=context)
            return getattr(journal, action)(plan, row, context=context)

    def _plan(self, plan, actor, *, check_parser=True, mapping=False):
        if not isinstance(plan, KnowledgeIngestionIntent) or plan.legacy_snapshot is None: raise InvalidInput()
        KnowledgeIngestionIntent.model_validate_json(plan.model_dump_json())
        if plan.user_id != actor.user_id or plan.legacy_snapshot.tenant_id != actor.tenant_id: raise ScopeDenied()
        if bool(plan.legacy_snapshot.task_references) != bool(plan.legacy_snapshot.task_archive_sha256): raise InvalidInput()
        if (plan.legacy_snapshot.previous_file_id is not None) != mapping:
            raise Conflict()
        if check_parser and plan.parser_version != self.parser_version: raise Conflict()

    async def _revalidate_mapping(self, plan, actor, context, task_archive):
        snapshot = plan.legacy_snapshot
        current = await self.plan(plan.knowledge_id, snapshot.previous_file_id, actor, legacy_quiesced=True,
            context=context, task_archive=task_archive, bind_observed_source=snapshot.source_binding is not None,
            map_legacy_file_id=True)
        if current != plan:
            raise Conflict()

    async def reserve_file_id(self, plan, actor, *, context, task_archive=None):
        self._plan(plan, actor, mapping=True)
        async with _deadline(context):
            await self._revalidate_mapping(plan, actor, context, task_archive)
            return await self._blocking(self._reserve, plan, actor, context)

    def _reserve(self, plan, actor, context):
        return self.reserve_identity(actor, plan, context=context)

    def _change_mapping(self, plan, actor, context, change, journal_method):
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (_, resources):
            resource = KnowledgeSearchAuthorizationPolicy(resources, user_id=actor.user_id).authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[plan.knowledge_id]),
                edit=True, context=context,
            ).knowledge_bases[0]
            if (resource.revision != plan.legacy_snapshot.resource_revision
                or resource.embedding_model_id != plan.embedding_model.model_id):
                raise Conflict()

            def apply(records, row):
                return journal_method(IngestionJournal(records), plan, row, context=context)

            return change(actor, plan, apply, context=context)

    async def activate_file_id(self, plan, actor, *, context, task_archive=None):
        self._plan(plan, actor, mapping=True)
        original_id = plan.legacy_snapshot.previous_file_id
        async with _deadline(context):
            try:
                await self._blocking(self._selected, plan.knowledge_id, original_id, actor, context)
            except NotFound:
                # The transaction confirms the existing mapping before replaying its receipt.
                pass
            else:
                await self._revalidate_mapping(plan, actor, context, task_archive)
            return await self._blocking(
                self._change_mapping, plan, actor, context, self.activate_identity, IngestionJournal.admit_legacy,
            )

    async def restore_file_id(self, plan, actor, *, context):
        self._plan(plan, actor, mapping=True)
        async with _deadline(context):
            return await self._blocking(
                self._change_mapping, plan, actor, context, self.restore_identity, IngestionJournal.restore_legacy,
            )

    async def inspect(self, plan, actor, *, context):
        mapping = isinstance(plan, KnowledgeIngestionIntent) and plan.legacy_snapshot is not None and (
            plan.legacy_snapshot.previous_file_id is not None
        )
        self._plan(plan, actor, check_parser=False, mapping=mapping)
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

    async def verify_publication(self, plan, actor, *, context):
        mapping = isinstance(plan, KnowledgeIngestionIntent) and plan.legacy_snapshot is not None and (
            plan.legacy_snapshot.previous_file_id is not None
        )
        self._plan(plan, actor, check_parser=False, mapping=mapping)
        async with _deadline(context):
            row, resource = await self._blocking(self._selected, plan.knowledge_id, plan.file_id, actor, context)
            try:
                saved = KnowledgeIngestionIntent.model_validate(row["ingestion_request"])
                lookup = KnowledgeJobInspection(**plan._reference(), job_id=row["forward_task_id"],
                                                confirm_publication=True)
            except ValidationError:
                raise Conflict(operation_id=context.operation_id) from None
            if (saved != plan or row["status"] != "COMPLETED" or row["stage"] != "COMPLETE"
                or row["runtime_status"] != "completed" or row["deletion_request"] is not None
                or row["source_generation"] != plan.file_version
                or [row[f"source_{name}"] for name in ("space", "key", "revision", "sha256")] !=
                   [plan.source.space, plan.source.key, plan.source.version, plan.source.sha256]
                or resource.revision != plan.legacy_snapshot.resource_revision
                or resource.embedding_model_id != plan.embedding_model.model_id
                or type(row["total_chunks"]) is not int or row["total_chunks"] < 0
                or row["processed_chunks"] != row["total_chunks"]):
                raise Conflict(operation_id=context.operation_id)
            state = await self.client.inspect_knowledge_file(lookup, actor.user_id, actor.tenant_id)
            if (state.publication_confirmed is not True or state.status != "completed"
                or state.writer_ended is not True or state.reconcile_required is not False
                or state.total_chunks != row["total_chunks"] or state.processed_chunks != row["processed_chunks"]
                or any(getattr(state, name) != getattr(lookup, name)
                       for name in ("knowledge_id", "file_id", "file_version", "job_id"))):
                raise Conflict(operation_id=context.operation_id)
            if await self._blocking(self._selected, plan.knowledge_id, plan.file_id, actor, context) != (row, resource):
                raise Conflict(operation_id=context.operation_id)
            return row

    async def admit(self, plan, actor, *, context, task_archive=None):
        self._plan(plan, actor)
        async with _deadline(context):
            row, resource = await self._blocking(self._selected, plan.knowledge_id, plan.file_id, actor, context)
            if row['ingestion_request'] is not None:
                return await self._blocking(self._change, plan, actor, context, 'admit_legacy')
            self._eligible(row, archived_tasks=task_archive is not None)
            if resource.revision != plan.legacy_snapshot.resource_revision: raise Conflict()
            await self._blocking(self._task_evidence, row, resource, actor, task_archive, context, plan.legacy_snapshot.task_archive_sha256)
            model = await self._model(plan.embedding_model.model_id, actor)
            if model.revision != plan.embedding_model.revision: raise Conflict()
            binding = plan.legacy_snapshot.source_binding
            finding = await self._blocking(self._source_evidence, row, resource.revision, actor, context,
                binding is not None, plan.legacy_snapshot.task_archive_sha256 is not None)
            if finding.candidate_source != plan.source or row['version'] != plan.legacy_snapshot.lifecycle_revision:
                raise Conflict()
            alias = row['object_name'] if 'SOURCE_ALIAS_PROVEN' in finding.issues else None
            if binding is not None and (
                finding.candidate_storage_object_id != binding.storage_object_id
                or finding.observed_size != binding.file_size
                or alias != binding.previous_object_name
            ):
                raise Conflict()
            await self._empty_runtime(plan, actor)
            return await self._blocking(self._change, plan, actor, context, 'admit_legacy')

    async def restore(self, plan, actor, *, context):
        self._plan(plan, actor)
        async with _deadline(context):
            return await self._blocking(self._change, plan, actor, context, 'restore_legacy')

    async def execute(self, plan, actor, *, context, coordinator=None, task_archive=None):
        async with _deadline(context):
            await self.admit(plan, actor, context=context, task_archive=task_archive)
            if coordinator is None:
                from management.services.knowledge_base.ingestion_dispatch import (
                    default_coordinator,
                )
                coordinator = default_coordinator()
            return await coordinator.advance(plan.file_id, actor, context=context)
