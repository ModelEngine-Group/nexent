# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management summary orchestration consumes only authorized AgentOS document samples."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeSample,
    KnowledgeSampleResult,
    KnowledgeSearchAuthorization,
)
from contracts.constants import environment
from management.clients.model import worker_model_cancellation
from management.services.knowledge_base.search_authorization import (
    KnowledgeSearchAuthorizationPolicy,
)
from nexent.core.concurrency import (
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManagerNotRunning,
    get_current_thread_manager,
    get_default_thread_manager,
    run_blocking,
)
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
)
from nexent.storage.models import Comparison, OperationContext, PageRequest, RecordQuery

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_cleanse import knowledge_resource_ports

logger = logging.getLogger(__name__)
_MODEL_CLOSE_GRACE_SECONDS = 5


class KnowledgeSummaryService:
    def __init__(self, *, client=None, resources=knowledge_resource_ports, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
        self.resources, self.operation_seconds = resources, operation_seconds

    def _resolve(self, index_name, user_id, tenant_id, *, context):
        if not user_id or not tenant_id:
            raise ScopeDenied()
        with self.resources(tenant_id, user_id, context=context) as records:
            page = records.query('cleanse_knowledge', RecordQuery(where=Comparison('index_name', 'eq', index_name)),
                                 PageRequest(limit=2), context=context)
            if not page.items:
                raise NotFound()
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            grants = KnowledgeSearchAuthorizationPolicy(records, user_id=user_id).authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[page.items[0]['knowledge_id']]), edit=True, context=context)
            return grants.knowledge_bases[0]

    async def _resource(self, index_name, user_id, tenant_id, *, context):
        def resolve():
            context.remaining()
            result = self._resolve(index_name, user_id, tenant_id, context=context)
            context.remaining()
            return result
        return await run_blocking('knowledge-summary-authorize', resolve, lane='control-io', owner='management.knowledge.summary')

    @staticmethod
    def _validate(result, resource, limit):
        if (not isinstance(result, KnowledgeSampleResult) or result.knowledge_id != resource.knowledge_id
            or result.knowledge_revision != resource.revision
            or result.embedding_model.model_id != resource.embedding_model_id or len(result.documents) > limit):
            raise Conflict()
        sources, chunks, dimensions = set(), set(), None
        for document in result.documents:
            if document.file_ref is not None and document.file_ref.knowledge_id != resource.knowledge_id:
                raise ScopeDenied()
            source = ('file', document.file_ref.file_id) if document.file_ref else ('independent', document.standalone_key)
            if source in sources:
                raise Conflict()
            sources.add(source)
            previous = None
            for chunk in document.chunks:
                if chunk.chunk_id in chunks or (chunk.chunk_index is None) != (document.file_ref is None):
                    raise Conflict()
                chunks.add(chunk.chunk_id)
                order = (chunk.chunk_index, chunk.chunk_id) if document.file_ref else (chunk.chunk_id,)
                if previous is not None and order <= previous:
                    raise Conflict()
                previous = order
                if chunk.embedding is None:
                    continue
                if dimensions is None:
                    dimensions = len(chunk.embedding)
                if len(chunk.embedding) != dimensions:
                    raise Conflict()

    async def sample(self, index_name, *, batch_size=1000, user_id, tenant_id, context=None):
        count = min(batch_size // 5, 200)
        if count <= 0:
            raise ValueError('No documents found in index.')
        context = context or OperationContext('knowledge-summary-sample-' + uuid4().hex,
                                               monotonic() + self.operation_seconds)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                resource = await self._resource(index_name, user_id, tenant_id, context=context)
                result = await self.client.sample_knowledge(KnowledgeSample(knowledge_id=resource.knowledge_id,
                    expected_revision=resource.revision, document_limit=count,
                    native_documents=environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED), user_id, tenant_id)
                self._validate(result, resource, count)
                if await self._resource(index_name, user_id, tenant_id, context=context) != resource:
                    raise Conflict()
                return result
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_summary_sample_timeout operation_id=%s threshold_seconds=%s exception_type=%s',
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error

    @staticmethod
    def _summarize(sample, language, model_id, user_id, tenant_id):
        from management.services.knowledge_base.clustering import (
            kmeans_cluster_documents,
        )
        from management.services.knowledge_base.summary import (
            merge_cluster_summaries,
            sample_documents_for_clustering,
            summarize_clusters_map_reduce,
        )

        documents, embeddings = sample_documents_for_clustering(sample)
        if not documents:
            raise ValueError('No documents found in index.')
        clusters = kmeans_cluster_documents(embeddings, k=None)
        summaries = summarize_clusters_map_reduce(document_samples=documents, clusters=clusters, language=language,
            doc_max_words=100, cluster_max_words=150, model_id=model_id, user_id=user_id, tenant_id=tenant_id)
        return merge_cluster_summaries(summaries)

    async def summarize_sample(self, sample, *, user_id, tenant_id, language='zh', model_id=None):
        """Consume an already authorized sample; the caller owns final publication checks."""
        if not user_id or not tenant_id:
            raise ScopeDenied()
        manager = get_current_thread_manager() or get_default_thread_manager()
        if manager is None:
            raise ThreadManagerNotRunning('Summary execution requires a lifespan-owned manager')
        scope = RunCancellationScope()

        def summarize():
            with worker_model_cancellation(scope):
                value = self._summarize(sample, language, model_id, user_id, tenant_id)
                if scope.cancelled:
                    raise RunTerminated()
                return value

        execution = manager.submit('model-tool-io', ManagedTaskSpec(
            task_name='knowledge-summary', owner='management.knowledge.summary', close_hook=scope.cancel,
            deadline_monotonic=monotonic() + self.operation_seconds), summarize)
        future = asyncio.wrap_future(execution.future)
        try:
            async with asyncio.timeout(self.operation_seconds):
                return await asyncio.shield(future)
        except TimeoutError as error:
            logger.warning('knowledge_summary_model_timeout operation_id=%s phase=model threshold_seconds=%s exception_type=%s',
                           execution.execution_id, self.operation_seconds, type(error).__name__)
            raise DeadlineExceeded(operation_id=execution.execution_id) from error
        finally:
            scope.cancel()
            try:
                if not future.done():
                    manager.cancel(execution.execution_id, reason='summary caller ended', wait_timeout=0,
                                   mark_stuck_on_timeout=False)
                    try:
                        await asyncio.wait({future}, timeout=_MODEL_CLOSE_GRACE_SECONDS)
                    finally:
                        if not future.done():
                            manager.cancel(execution.execution_id, reason='summary close grace exceeded', wait_timeout=0)
            finally:
                # Observe exceptions even if cancellation interrupts the close grace.
                future.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def generate(self, *, index_name, batch_size=1000, user_id, tenant_id, language='zh', model_id=None):
        sample = await self.sample(index_name, batch_size=batch_size, user_id=user_id, tenant_id=tenant_id)
        summary = await self.summarize_sample(sample, language=language, model_id=model_id, user_id=user_id, tenant_id=tenant_id)
        context = OperationContext('knowledge-summary-final-' + uuid4().hex, monotonic() + 10)
        resource = await self._resource(index_name, user_id, tenant_id, context=context)
        self._validate(sample, resource, min(batch_size // 5, 200))
        return summary
