# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Advance persisted ingestion once; uncertain submissions are inspected, never replayed."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeJobLookup,
    ObjectReference,
)
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_cleanse import KnowledgeCleanseLookup
from contracts.knowledge_ingestion import KnowledgeIngestionIntent
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.knowledge_base.ingestion_journal import (
    IngestionJournal,
    IngestionPhaseChanged,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
)
from nexent.storage.models import OperationContext

from infrastructure.knowledge_ingestion import knowledge_ingestion_ports

logger = logging.getLogger(__name__)


class IngestionCancellation:
    def __init__(self, owned, parent):
        self.owned, self.parent = owned, parent

    def is_set(self):
        return self.owned.is_set() or self.parent is not None and self.parent.is_set()


class IngestionCoordinator:
    def __init__(self, cleanse, client, *, ports=knowledge_ingestion_ports):
        self.cleanse, self.client, self.ports = cleanse, client, ports

    @asynccontextmanager
    async def _operation(self, context, file_id, *, phase):
        context = context or OperationContext(
            "kb-ingest-" + uuid4().hex, monotonic() + 10
        )
        owned = Event()
        context = replace(context, cancelled=IngestionCancellation(owned, context.cancelled))
        seconds = max(0, context.deadline - monotonic())
        try:
            async with asyncio.timeout(context.remaining()):
                yield context
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning(
                "knowledge_ingestion_timeout file_id=%s operation_id=%s phase=%s threshold_seconds=%.3f error_type=%s",
                file_id,
                context.operation_id,
                phase,
                seconds,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            owned.set()

    async def _blocking(self, name, fn, *args, **kwargs):
        return await run_blocking(
            "knowledge-ingestion-" + name,
            fn,
            *args,
            lane="control-io",
            owner="management.knowledge_base",
            **kwargs,
        )

    def _validated(self, records, resources, file_id, actor, context, intent=None):
        if (
            records.scope.actor_id != actor.user_id
            or records.scope.tenant_id != actor.tenant_id
        ):
            raise ScopeDenied()
        journal = IngestionJournal(records)
        row = journal.record(file_id, context=context)
        intent = intent if intent is not None else journal.request(row)
        if intent.user_id != actor.user_id:
            raise ScopeDenied()
        # Admission also checks the current source against the lifecycle row in the journal.
        authorization = KnowledgeCleanseAuthorization(resources, user_id=actor.user_id)
        authorization.authorize(intent.cleanse_request(), context=context)
        knowledge = authorization.resolve_knowledge(
            intent.knowledge_id, edit=True, context=context
        )
        if knowledge["embedding_model_id"] != intent.embedding_model.model_id:
            raise Conflict()
        return journal, row, intent

    def _load(self, file_id, actor, context, intent=None):
        context.remaining()
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (
            records,
            resources,
        ):
            _, row, value = self._validated(
                records, resources, file_id, actor, context, intent
            )
            return row, value

    def _draft(self, file_id, actor, strategy, context):
        context.remaining()
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (
            records,
            resources,
        ):
            journal = IngestionJournal(records)
            row = journal.record(file_id, context=context)
            if row["ingestion_request"] is not None and row['status'] != 'FAILED':
                _, row, intent = self._validated(
                    records, resources, file_id, actor, context
                )
                if intent.chunking_strategy != strategy:
                    raise Conflict()
                return (
                    row,
                    intent.model_dump(mode="json"),
                    intent.embedding_model.model_id,
                    None,
                )
            prior = journal.request(row) if row['status'] == 'FAILED' else None
            reference = KnowledgeFileReference(
                knowledge_id=row["knowledge_id"],
                file_id=file_id,
                file_version=row["source_generation"],
            )
            authorization = KnowledgeCleanseAuthorization(
                resources, user_id=actor.user_id
            )
            _, knowledge = authorization.resolve(reference, edit=True, context=context)
            values = {
                **reference.model_dump(),
                "user_id": actor.user_id,
                "attempt": row["processing_attempt"] + 1,
                "source": ObjectReference(
                    space=row["source_space"],
                    key=row["source_key"],
                    version=row["source_revision"],
                    sha256=row["source_sha256"],
                ),
                "filename": row["original_filename"],
                "parser_version": self.cleanse.parser_version,
                "chunking_strategy": strategy,
            }
            if prior is not None and prior.legacy_snapshot is not None:
                values['legacy_snapshot'] = prior.legacy_snapshot.model_dump(mode='json')
            return row, values, knowledge["embedding_model_id"], prior

    async def _prior_children(self, row, prior, actor, context):
        cleanse = await self._blocking(
            'inspect-prior-cleanse', self.cleanse.inspect,
            KnowledgeCleanseLookup(**prior._reference(), job_id=row['process_task_id']),
            tenant_id=actor.tenant_id, user_id=actor.user_id, context=context)
        context.remaining()
        runtime = None
        if row['forward_task_id'] is not None:
            runtime = await self.client.inspect_knowledge_file(
                KnowledgeJobLookup(**prior._reference(), job_id=row['forward_task_id']),
                user_id=actor.user_id, tenant_id=actor.tenant_id)
            context.remaining()
        return cleanse, runtime

    def _change(self, previous, actor, context, method, *args, intent=None):
        context.remaining()
        with self.ports(actor.tenant_id, actor.user_id, context=context) as (
            records,
            resources,
        ):
            journal, row, _ = self._validated(
                records,
                resources,
                previous["file_id"],
                actor,
                context,
                intent,
            )
            if row["version"] != previous["version"]:
                raise IngestionPhaseChanged()
            result = (
                getattr(journal, method)(*args, row, context=context)
                if method == "admit"
                else (getattr(journal, method)(row, *args, context=context))
            )
            # A reread after a successful CAS may already observe another participant's write.
            updated = result[0] if isinstance(result, tuple) else result
            if updated["version"] > row["version"] + 1:
                raise IngestionPhaseChanged()
            return result

    async def _model(self, intent, actor, context):
        context.remaining()
        model = await self.client.get_model(
            intent.embedding_model.model_id,
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
        )
        context.remaining()
        if (
            model.model_id != intent.embedding_model.model_id
            or model.revision != intent.embedding_model.revision
            or model.model_type not in {"embedding", "multi_embedding"}
        ):
            raise Conflict()

    async def admit(self, intent, actor, *, context=None):
        if not isinstance(intent, KnowledgeIngestionIntent):
            raise InvalidInput()
        if intent.parser_version != self.cleanse.parser_version:
            raise Conflict()
        async with self._operation(context, intent.file_id, phase="admit") as operation:
            row, _ = await self._blocking(
                "authorize", self._load, intent.file_id, actor, operation, intent
            )
            await self._model(intent, actor, operation)
            return await self._blocking(
                "admit",
                self._change,
                row,
                actor,
                operation,
                "admit",
                intent,
                intent=intent,
            )

    async def accept(self, file_id, actor, *, chunking_strategy="basic", context=None):
        """Freeze current authorized resource metadata without accepting caller-supplied model bindings."""
        if chunking_strategy not in {"basic", "by_title", "none"}:
            raise InvalidInput()
        async with self._operation(context, file_id, phase="accept") as operation:
            row, values, model_id, prior = await self._blocking(
                "prepare",
                self._draft,
                file_id,
                actor,
                chunking_strategy,
                operation,
            )
            children = await self._prior_children(row, prior, actor, operation) if prior is not None else ()
            if type(model_id) is not int or model_id <= 0:
                raise InvalidInput()
            metadata = await self.client.get_model(
                model_id, user_id=actor.user_id, tenant_id=actor.tenant_id
            )
            operation.remaining()
            if metadata.model_id != model_id or metadata.model_type not in {
                "embedding",
                "multi_embedding",
            }:
                raise Conflict()
            binding = {"model_id": model_id, "revision": metadata.revision}
            if "embedding_model" in values and values["embedding_model"] != binding:
                raise Conflict()
            intent = KnowledgeIngestionIntent.model_validate(
                {**values, "embedding_model": binding}
            )
            return await self._blocking(
                "admit",
                self._change,
                row,
                actor,
                operation,
                "reprocess" if prior is not None else "admit",
                intent,
                *children,
                intent=intent,
            )

    async def advance(self, file_id, actor, *, context=None):
        async with self._operation(context, file_id, phase="advance") as operation:
            row, intent = await self._blocking(
                "authorize", self._load, file_id, actor, operation
            )
            if row["stage"] in {"COMPLETE", "FAILED"}:
                return row
            await self._model(intent, actor, operation)
            stage = row["stage"]
            if stage == "INGEST_ACCEPTED":
                if intent.parser_version != self.cleanse.parser_version:
                    raise Conflict()
                row = await self._blocking(
                    "reserve-cleanse",
                    self._change,
                    row,
                    actor,
                    operation,
                    "begin_cleanse",
                )
                child = await self._blocking(
                    "submit-cleanse",
                    self.cleanse.submit,
                    intent.cleanse_request(),
                    tenant_id=actor.tenant_id,
                    user_id=actor.user_id,
                    context=operation,
                )
            elif stage in {"CLEANSE_SUBMITTING", "CLEANSE_PENDING"}:
                lookup = KnowledgeCleanseLookup(
                    **intent._reference(), job_id=row["process_task_id"]
                )
                try:
                    child = await self._blocking(
                        "inspect-cleanse",
                        self.cleanse.inspect,
                        lookup,
                        tenant_id=actor.tenant_id,
                        user_id=actor.user_id,
                        context=operation,
                    )
                except NotFound:
                    return row
            elif stage in {"RUNTIME_SUBMITTING", "RUNTIME_PENDING"}:
                lookup = KnowledgeJobLookup(
                    **intent._reference(), job_id=row["forward_task_id"]
                )
                try:
                    state = await self.client.inspect_knowledge_file(
                        lookup,
                        user_id=actor.user_id,
                        tenant_id=actor.tenant_id,
                    )
                except RuntimeUpstreamError as error:
                    if error.status_code != 404:
                        raise
                    return row
                return await self._blocking(
                    "observe-runtime",
                    self._change,
                    row,
                    actor,
                    operation,
                    "observe_runtime",
                    state,
                )
            else:
                raise Conflict()
            if child.status != "completed":
                return await self._blocking(
                    "observe-cleanse",
                    self._change,
                    row,
                    actor,
                    operation,
                    "observe_cleanse",
                    child,
                )
            row, payload = await self._blocking(
                "reserve-runtime",
                self._change,
                row,
                actor,
                operation,
                "begin_runtime",
                child,
            )
            state = await self.client.upload_knowledge_file(
                payload,
                user_id=actor.user_id,
                tenant_id=actor.tenant_id,
            )
            return await self._blocking(
                "observe-runtime",
                self._change,
                row,
                actor,
                operation,
                "observe_runtime",
                state,
            )
