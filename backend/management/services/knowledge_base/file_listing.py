# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Assemble public file rows from AgentOS source summaries and SI lifecycle records."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_sources import KnowledgeSources, KnowledgeSourcesResult
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.file_source_display import FileSourceDisplay
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


def _physical_files(sources):
    files = {}
    for source in sources:
        try:
            timestamp = (
                datetime.strptime(source.create_time, "%Y-%m-%dT%H:%M:%S")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except (ValueError, TypeError):
            timestamp = time.time()
        # Keep the original JSON metadata instead of rewriting a displayed name
        # or a stored size. Lifecycle projection retains its existing precedence.
        files[source.path_or_url] = {
            "path_or_url": source.path_or_url,
            "file": source.filename,
            "file_size": source.file_size,
            "create_time": int(timestamp * 1000),
            "status": "COMPLETED",
            "latest_task_id": "",
            "chunk_count": source.chunk_count,
            "error_reason": None,
            "has_error_info": False,
        }
    return files


class KnowledgeFileListing:
    def __init__(
        self, *, reader=None, client=None, display=None, operation_seconds=180
    ):
        if (
            type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 180
        ):
            raise InvalidInput()
        self.reader = reader or KnowledgeFileReader()
        self.client = client or AgentOSClient(
            environment.RUNTIME_SERVICE_URL, create_httpx_client
        )
        self.display = display or FileSourceDisplay()
        self.operation_seconds = operation_seconds

    async def _blocking(self, name, action, *args, context, **kwargs):
        return await run_blocking(
            "knowledge-file-list-" + name,
            action,
            *args,
            context=context,
            **kwargs,
            lane="control-io",
            owner="management.knowledge_base",
        )

    async def list(self, index_name, actor):
        cancelled = Event()
        context = OperationContext(
            "knowledge-file-list-" + uuid4().hex,
            monotonic() + self.operation_seconds,
            cancelled=cancelled,
        )
        try:
            async with asyncio.timeout(context.remaining()):
                row = await self._blocking(
                    "resource",
                    self.reader.knowledge,
                    index_name,
                    actor,
                    context=context,
                )
                resource = chunks_resource_grant(row)
                if resource.collection != index_name:
                    raise ScopeDenied()
                lifecycle = await self._blocking(
                    "lifecycle", self.reader.files, index_name, actor, context=context
                )
                if any(
                    file["knowledge_id"] != resource.knowledge_id
                    or file["tenant_id"] != resource.resource_tenant_id
                    for file in lifecycle
                ):
                    raise ScopeDenied()
                if len({file["file_id"] for file in lifecycle}) != len(lifecycle):
                    raise Conflict()
                try:
                    response = await self.client.list_knowledge_sources(
                        KnowledgeSources(
                            knowledge_id=resource.knowledge_id,
                            expected_revision=resource.revision,
                        ),
                        actor.user_id,
                        actor.tenant_id,
                    )
                except RuntimeUpstreamError as error:
                    kind = {403: ScopeDenied, 409: Conflict, 504: DeadlineExceeded}.get(
                        error.status_code
                    )
                    if kind is not None:
                        raise kind(operation_id=context.operation_id) from error
                    raise
                if (
                    not isinstance(response, KnowledgeSourcesResult)
                    or response.knowledge_id != resource.knowledge_id
                ):
                    raise ScopeDenied()
                if response.revision != resource.revision:
                    raise Conflict()
                files = _physical_files(response.sources)
                projected = await self._blocking(
                    "display",
                    self.display.project,
                    list(files.values()),
                    actor,
                    context=context,
                    lifecycle_rows=lifecycle,
                )
                final = await self._blocking(
                    "recheck", self.reader.knowledge, index_name, actor, context=context
                )
                if chunks_resource_grant(final) != resource:
                    raise Conflict()
                context.remaining()
                return {"files": projected}
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning(
                "knowledge_file_list_timeout operation_id=%s phase=list threshold_seconds=%s exception_type=%s",
                context.operation_id,
                self.operation_seconds,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()


async def list_knowledge_files(index_name, actor):
    return await KnowledgeFileListing().list(index_name, actor)
