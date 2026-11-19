# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded AgentOS KB admission and inspection with fresh Management authorization."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    KnowledgeAuthorizationRequest,
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
)
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput
from nexent.storage.models import OperationContext
from runtime.knowledge_base.base_deletion_service import KnowledgeBaseDeletionService
from runtime.knowledge_base.composition import knowledge_jobs, require_knowledge_grant
from runtime.knowledge_base.search import KnowledgeSearchService

from infrastructure.agent_model_config import normalize_model_revision

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(
        self, authorization_client, models, *, jobs=knowledge_jobs, operation_seconds=10
    ):
        if (
            type(operation_seconds) not in {int, float}
            or not 0 < operation_seconds <= 30
        ):
            raise InvalidInput()
        self.client, self.models, self.jobs, self.operation_seconds = (
            authorization_client,
            models,
            jobs,
            operation_seconds,
        )

    async def upload(self, payload, actor, *, context=None):
        return await self._dispatch(payload, actor, "upload", context)

    async def inspect(self, payload, actor, *, context=None):
        return await self._dispatch(payload, actor, "inspect", context)

    async def delete(self, payload, actor, *, context=None):
        return await self._dispatch(payload, actor, "delete", context)

    async def search(self, payload, actor, *, context=None):
        return await KnowledgeSearchService(self.client, self.models).search(payload, actor, context=context)

    async def sample(self, payload, actor, *, context=None):
        from runtime.knowledge_base.sample import KnowledgeSampleService

        return await KnowledgeSampleService(self.client, self.models).sample(payload, actor, context=context)

    async def chunks(self, payload, actor, *, context=None):
        from runtime.knowledge_base.chunks import KnowledgeChunksService

        return await KnowledgeChunksService(self.client).chunks(payload, actor, context=context)

    async def list_sources(self, payload, actor, *, context=None):
        from runtime.knowledge_base.sources import KnowledgeSourcesService

        return await KnowledgeSourcesService(self.client).list_sources(payload, actor, context=context)

    async def mutate_chunk(self, payload, actor, *, context=None):
        from runtime.knowledge_base.chunk_write import ChunkMutationService

        return await ChunkMutationService(self.client, self.models).mutate(payload, actor, context=context)

    async def append_documents(self, payload, actor, *, context=None):
        from runtime.knowledge_base.chunk_write import ChunkMutationService
        from runtime.knowledge_base.document_append import KnowledgeDocumentAppender

        return await KnowledgeDocumentAppender(ChunkMutationService(self.client, self.models)).append(payload, actor, context=context)

    async def inspect_chunk(self, payload, actor, *, context=None):
        from runtime.knowledge_base.chunk_write import ChunkMutationService

        return await ChunkMutationService(self.client, self.models).lookup(payload, actor, context=context)

    async def inspect_base(self, payload, actor, *, context=None):
        from runtime.knowledge_base.manifest import KnowledgeManifestService

        return await KnowledgeManifestService(self.client).inspect(payload, actor, context=context)

    async def ensure_collection(self, payload, actor, *, context=None):
        from runtime.knowledge_base.collection_service import KnowledgeCollectionService

        return await KnowledgeCollectionService(self.client, self.models).ensure(payload, actor, context=context)

    async def inspect_collection(self, payload, actor, *, context=None):
        from runtime.knowledge_base.collection_service import KnowledgeCollectionService

        return await KnowledgeCollectionService(self.client, self.models).inspect(payload, actor, context=context)

    async def delete_base(self, payload, actor, *, context=None):
        return await KnowledgeBaseDeletionService(self.client).delete(payload, actor, context=context)

    async def describe_collections(self, payload, actor, *, context=None):
        from runtime.knowledge_base.collection_metadata import (
            KnowledgeCollectionMetadataService,
        )

        return await KnowledgeCollectionMetadataService(self.client).describe(payload, actor, context=context)

    async def inspect_base_deletion(self, payload, actor, *, context=None):
        return await KnowledgeBaseDeletionService(self.client).inspect(payload, actor, context=context)

    async def _dispatch(self, payload, actor, action, context):
        schema = {
            "upload": KnowledgeFileUpload,
            "inspect": KnowledgeJobLookup,
            "delete": KnowledgeFileDelete,
        }[action]
        if not isinstance(payload, schema):
            raise InvalidInput()
        context = context or OperationContext(
            "knowledge-" + uuid4().hex, monotonic() + self.operation_seconds
        )
        try:
            async with asyncio.timeout(context.remaining()):
                request = KnowledgeAuthorizationRequest(
                    knowledge_id=payload.knowledge_id,
                    file_id=payload.file_id,
                    file_version=payload.file_version,
                    action=action,
                    **(
                        {
                            "artifact": payload.artifact,
                            "parser_version": payload.parser_version,
                        }
                        if action == "upload"
                        else {}
                    ),
                )
                grant = await self.client.authorize_knowledge(
                    request, actor.user_id, actor.tenant_id
                )
                require_knowledge_grant(payload, grant, action=action)
                if action == "upload":
                    for binding, modalities in (
                        (payload.embedding_model, {"embedding", "multi_embedding"}),
                        (payload.rerank_model, {"rerank"}),
                    ):
                        if binding is not None:
                            model = await self.models.get(binding.model_id, actor)
                            if (
                                model.model_id != binding.model_id
                                or model.model_type not in modalities
                                or normalize_model_revision(model.revision)
                                != normalize_model_revision(binding.revision)
                            ):
                                raise Conflict()

                def execute():
                    context.remaining()
                    with self.jobs(actor, grant, context=context) as jobs:
                        return (jobs.inspect if action == "inspect" else jobs.submit)(
                            payload, context=context
                        )

                return await run_blocking(
                    "agentos-knowledge-" + action,
                    execute,
                    lane="control-io",
                    owner="runtime.knowledge_base",
                )
        except RuntimeServiceTimeoutError as exc:
            # The transport already records the timeout without request content.
            raise DeadlineExceeded(operation_id=context.operation_id) from exc
        except (TimeoutError, DeadlineExceeded) as exc:
            logger.warning(
                "knowledge_request_timeout operation_id=%s phase=%s exception_type=%s",
                context.operation_id,
                action,
                type(exc).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from exc
