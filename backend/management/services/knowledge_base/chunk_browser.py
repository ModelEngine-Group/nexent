# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Adapt published AgentOS chunk windows to the existing public browse response."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeChunks, KnowledgeChunksResult
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_chunk_projection import (
    PUBLIC_CHUNK_FIELDS,
    PUBLIC_CHUNK_SOURCE_KEY,
    public_chunk_source,
    public_path_matches,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


class KnowledgeChunkBrowser:
    def __init__(self, *, client=None, reader=None, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.reader, self.operation_seconds = reader or KnowledgeFileReader(), operation_seconds

    async def _snapshot(self, index_name, actor, *, context):
        def read():
            row = self.reader.knowledge(index_name, actor, context=context)
            grant = chunks_resource_grant(row)
            files = self.reader.files(index_name, actor, context=context)
            selected = [file for file in files if file['delete_flag'] == 'N']
            if any(file['knowledge_id'] != grant.knowledge_id or file['tenant_id'] != grant.resource_tenant_id for file in selected):
                raise ScopeDenied()
            if len({file['file_id'] for file in selected}) != len(selected):
                raise Conflict()
            return grant, selected
        return await run_blocking('knowledge-chunk-browse-metadata', read, lane='control-io', owner='management.knowledge_base')

    @staticmethod
    def _chunk(chunk, files):
        file = files.get(chunk.file_id)
        if chunk.file_id is not None and (file is None or file['knowledge_id'] != chunk.knowledge_id):
            raise ScopeDenied()
        source = public_chunk_source(chunk.content, chunk.location)
        if source is not None:
            source.setdefault('id', chunk.chunk_id)
            return {key: value for key, value in source.items() if key in PUBLIC_CHUNK_FIELDS}
        result = {key: chunk.location[key] for key in ('title', 'language', 'author', 'date', 'create_time') if key in chunk.location}
        result.update(id=chunk.chunk_id, content=chunk.content, filename=chunk.filename,
                      path_or_url=(file['object_name'] or file['local_source_path'] or '') if file is not None else chunk.location.get('path_or_url',''))
        if 'create_time' not in result and file is not None and file['create_time'] is not None:
            result['create_time'] = file['create_time']
        return result

    async def browse(self, index_name, actor, *, page=None, page_size=None, path_or_url=None, native_documents=False):
        cancelled = Event()
        context = OperationContext('knowledge-chunk-browse-' + uuid4().hex, monotonic() + self.operation_seconds, cancelled=cancelled)
        threshold = context.remaining()
        paginate = page is not None and page_size is not None
        offset, wanted = ((max(page, 1)-1)*max(page_size, 1), max(page_size, 1)) if paginate else (0, None)
        try:
            async with asyncio.timeout(threshold):
                resource, files = await self._snapshot(index_name, actor, context=context)
                mapping = {file['file_id']: file for file in files}
                selected = None if not path_or_url or native_documents else [file['file_id'] for file in files
                    if path_or_url in (file['object_name'], file['local_source_path'])]
                chunks, seen, revision, total = [], set(), None, None
                while True:
                    limit = 1000 if wanted is None else min(wanted-len(chunks), 1000)
                    request = KnowledgeChunks(knowledge_id=resource.knowledge_id, expected_revision=resource.revision,
                        expected_data_revision=revision, offset=offset, limit=limit, file_ids=selected,
                        standalone_path=path_or_url or None, native_documents=native_documents)
                    result = await self.client.knowledge_chunks(request, actor.user_id, actor.tenant_id)
                    if not isinstance(result, KnowledgeChunksResult) or result.knowledge_id != resource.knowledge_id:
                        raise ScopeDenied()
                    if (result.knowledge_revision != resource.revision or revision is not None and result.data_revision != revision
                        or total is not None and result.total != total):
                        raise Conflict()
                    revision, total = result.data_revision, result.total
                    expected = min(limit, max(0, total-offset))
                    next_offset = offset+expected if offset+expected < total else None
                    if len(result.chunks) != expected or result.next_offset != next_offset:
                        raise Conflict()
                    for chunk in result.chunks:
                        if chunk.knowledge_id != resource.knowledge_id:
                            raise ScopeDenied()
                        matches_path = not path_or_url or (
                            public_path_matches(chunk.location, path_or_url)
                            if chunk.file_id is None or PUBLIC_CHUNK_SOURCE_KEY in chunk.location
                            else chunk.file_id in selected)
                        if chunk.chunk_id in seen or not matches_path:
                            raise Conflict()
                        seen.add(chunk.chunk_id)
                        chunks.append(self._chunk(chunk, mapping))
                    if next_offset is None or wanted is not None and len(chunks) == wanted:
                        break
                    offset = next_offset
                if await self._snapshot(index_name, actor, context=context) != (resource, files):
                    raise Conflict()
                return {'status': 'success', 'message': f'Successfully retrieved {len(chunks)} chunks from index {index_name}',
                        'chunks': chunks, 'total': total, 'page': page if paginate else None, 'page_size': page_size if paginate else None}
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_chunk_browse_timeout operation_id=%s phase=read threshold_seconds=%s exception_type=%s',
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
