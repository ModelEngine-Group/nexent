# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One owned upload attempt, from durable admission to confirmed visible generation."""

import asyncio
import hashlib
import json
import logging
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeAuthorizationRequest,
    KnowledgeFileDelete,
    KnowledgeFileUpload,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OperationCancelled,
    OutcomeUnknown,
)
from nexent.storage.models import OperationContext, Revision
from runtime.knowledge_base.composition import knowledge_jobs, require_knowledge_grant
from runtime.knowledge_base.ingestion import KnowledgeIngestor
from runtime.knowledge_base.jobs import job_state

from infrastructure.knowledge_runtime import (
    knowledge_execution_ports,
    knowledge_runtime_ports,
)

logger = logging.getLogger(__name__)


class _Cancellation:
    def __init__(self, owned, parent):
        self.owned, self.parent = owned, parent

    def is_set(self):
        return self.owned.is_set() or self.parent is not None and self.parent.is_set()


def read_knowledge_job(lookup, actor, *, context):
    with knowledge_runtime_ports(actor, context=context) as records:
        row = records.get("runtime_knowledge_jobs", lookup.job_id, context=context)
        if (
            row is None
            or row["tenant_id"] != actor.tenant_id
            or row["user_id"] != actor.user_id
            or any(
                row[name] != getattr(lookup, name)
                for name in ("knowledge_id", "file_id", "file_version")
            )
        ):
            raise NotFound()
        return row


def knowledge_request(row, *, operation):
    if row["operation"] != operation or operation not in {"upload", "delete"}:
        raise InvalidInput()
    schema = KnowledgeFileUpload if operation == "upload" else KnowledgeFileDelete
    request = schema.model_validate(row["request_payload"])
    encoded = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    if hashlib.sha256(encoded).hexdigest() != row["request_hash"] or any(
        row[name] != getattr(request, name)
        for name in ("knowledge_id", "file_id", "file_version")
    ):
        raise InvalidInput()
    return request


def cancellable_context(context):
    owned = Event()
    return replace(context, cancelled=_Cancellation(owned, context.cancelled)), owned


class KnowledgeUploadWorker:
    def __init__(
        self,
        authorization_client,
        models,
        *,
        max_artifact_bytes,
        max_source_bytes,
        jobs=knowledge_jobs,
        ports=knowledge_execution_ports,
        operation_seconds=300,
    ):
        if (
            type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 3600
            or any(
                type(value) is not int or value <= 0
                for value in (max_artifact_bytes, max_source_bytes)
            )
        ):
            raise InvalidInput()
        self.client, self.models, self.jobs, self.ports = (
            authorization_client,
            models,
            jobs,
            ports,
        )
        self.max_artifact_bytes, self.max_source_bytes = (
            max_artifact_bytes,
            max_source_bytes,
        )
        self.operation_seconds = operation_seconds

    async def _blocking(self, action, *args, **kwargs):
        return await run_blocking(
            "knowledge-upload-worker",
            action,
            *args,
            lane="control-io",
            owner="runtime.knowledge_base",
            **kwargs,
        )

    async def _job(self, actor, grant, method, *args, context, **kwargs):
        def execute():
            context.remaining()
            with self.jobs(actor, grant, context=context) as jobs:
                return getattr(jobs, method)(*args, context=context, **kwargs)

        return await self._blocking(execute)

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge(
            KnowledgeAuthorizationRequest(
                knowledge_id=request.knowledge_id,
                file_id=request.file_id,
                file_version=request.file_version,
                action="execute",
                artifact=request.artifact,
                parser_version=request.parser_version,
            ),
            actor.user_id,
            actor.tenant_id,
        )
        require_knowledge_grant(request, grant, action="execute")
        return grant

    async def process(self, lookup, actor, *, owner_id, context=None):
        context = context or OperationContext(
            "knowledge-execution-" + uuid4().hex, monotonic() + self.operation_seconds
        )
        context, cancelled = cancellable_context(context)
        handle = ingestor = grant = None
        try:
            async with asyncio.timeout(context.remaining()):
                row = await self._blocking(
                    read_knowledge_job, lookup, actor, context=context
                )
                request = knowledge_request(row, operation="upload")
                if (
                    row["status"] not in {"queued", "running"}
                    or row["write_started"]
                    or row["reconcile_required"]
                ):
                    return job_state(row)
                grant = await self._grant(request, actor)
                lease_seconds = min(3600, int(context.remaining()) + 30)
                handle = await self._job(
                    actor,
                    grant,
                    "claim",
                    lookup,
                    owner_id=owner_id,
                    lease_seconds=lease_seconds,
                    context=context,
                )
                if handle is None:
                    return await self._job(
                        actor, grant, "inspect", lookup, context=context
                    )
                dimensions = await self.models.embedding_dimensions(
                    request.embedding_model, actor
                )
                if not await self._job(
                    actor, grant, "begin_execution", handle, context=context
                ):
                    raise OperationCancelled(operation_id=context.operation_id)

                async def checkpoint():
                    fresh = await self._grant(request, actor)
                    if fresh != grant:
                        raise Conflict()
                    if not await self._job(
                        actor,
                        fresh,
                        "renew",
                        handle,
                        lease_seconds=lease_seconds,
                        context=context,
                    ):
                        raise OperationCancelled(operation_id=context.operation_id)

                with self.ports(actor, grant, dimensions, context=context) as (
                    objects,
                    vectors,
                ):
                    ingestor = KnowledgeIngestor(
                        objects,
                        vectors,
                        self.models,
                        max_artifact_bytes=self.max_artifact_bytes,
                        max_source_bytes=self.max_source_bytes,
                    )
                    await self._blocking(
                        vectors.ensure_collection, grant.collection, context=context
                    )
                    result = await ingestor.execute(
                        request,
                        actor=actor,
                        source=grant.source,
                        filename=grant.filename,
                        collection=grant.collection,
                        generation=Revision(handle["attempt_id"]),
                        context=context,
                        checkpoint=checkpoint,
                    )
                    if not ingestor.stop_writes():
                        raise OutcomeUnknown(operation_id=context.operation_id)
                await checkpoint()
                if not await self._job(
                    actor,
                    grant,
                    "complete",
                    handle,
                    chunk_count=len(result.chunk_keys),
                    context=context,
                ):
                    raise OperationCancelled(operation_id=context.operation_id)
                return await self._job(actor, grant, "inspect", lookup, context=context)
        except BaseException as error:
            cancelled.set()
            failure = error
            if isinstance(error, TimeoutError):
                logger.warning(
                    "knowledge_worker_timeout operation_id=%s phase=execute",
                    context.operation_id,
                )
                failure = DeadlineExceeded(operation_id=context.operation_id)
            ended = (ingestor is None or ingestor.stop_writes()) and not isinstance(
                failure, OutcomeUnknown
            )
            if handle is not None:
                cleanup = OperationContext(
                    "knowledge-finish-" + uuid4().hex, monotonic() + 5
                )
                try:
                    await self._job(
                        actor,
                        grant,
                        "end_attempt",
                        handle,
                        writer_ended=ended,
                        context=cleanup,
                    )
                except Exception as close_error:  # noqa: BLE001 - Preserve the execution error and its durable unknown obligation.
                    logger.warning(
                        "knowledge_worker_finish_failed operation_id=%s exception_type=%s",
                        context.operation_id,
                        type(close_error).__name__,
                    )
            if failure is not error:
                raise failure from error
            raise
