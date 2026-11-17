# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model-scoped tool retrieval over the standard Runtime KnowledgeBase service."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos import RerankInvocation
from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeSearch,
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from nexent.core.utils.constants import RERANK_OVERSEARCH_MULTIPLIER
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext
from runtime.knowledge_base.search import rerank_indexes

from infrastructure.agent_model_config import normalize_model_revision

logger = logging.getLogger(__name__)


def _identity(hit):
    return hit.knowledge_id, hit.file_id, hit.file_version, hit.chunk_id


class KnowledgeToolSearch:
    """Bindings and file restrictions come from authorized assembly, never tool input."""

    def __init__(self, service, actor, bindings, *, file_refs=None):
        self.service, self.actor = service, actor
        self.bindings = {}
        ids = set()
        for resource, model in bindings:
            if (resource.collection in self.bindings or resource.knowledge_id in ids
                    or resource.embedding_model_id != model.model_id):
                raise ValueError("Invalid knowledge tool binding")
            ids.add(resource.knowledge_id)
            self.bindings[resource.collection] = (resource.model_copy(deep=True), model.model_copy(deep=True))
        self.files = None if file_refs is None else tuple(
            KnowledgeFileReference.model_validate(ref.model_dump()) for ref in file_refs
        )
        if self.files is not None and (len(self.files) > 1000 or len({f.file_id for f in self.files}) != len(self.files)
                                      or any(f.knowledge_id not in ids for f in self.files)):
            raise ValueError("Invalid fixed file references")

    @staticmethod
    def _merge(results, limit):
        if len(results) == 1:
            return results[0][:limit]
        ranked = []
        for rows in results:
            for position, hit in enumerate(rows, 1):
                ranked.append(hit.model_copy(update={
                    "score": 1 / (60 + position), "score_kind": "runtime.model_rrf",
                    "score_details": {**hit.score_details, "model_score": hit.score,
                                      "model_score_kind": hit.score_kind, "model_rank": position},
                }))
        return sorted(ranked, key=lambda hit: (-hit.score, _identity(hit)))[:limit]

    async def _reauthorize(self, resources):
        grant = await self.service.client.authorize_knowledge_search(
            KnowledgeSearchAuthorization(knowledge_ids=[r.knowledge_id for r in resources]),
            self.actor.user_id, self.actor.tenant_id,
        )
        if grant.knowledge_bases != resources:
            raise Conflict()

    async def search(self, query, collections, *, search_mode="hybrid", top_k=3, rerank_model=None, context=None):
        if (not isinstance(query, str) or not query or type(top_k) is not int or not 1 <= top_k <= 100
                or search_mode not in {"accurate", "semantic", "hybrid"}):
            raise InvalidInput()
        names = list(dict.fromkeys(collections))
        if any(name not in self.bindings for name in names):
            raise ScopeDenied()
        if not names or self.files == ():
            return []
        if len(names) > 100:
            raise InvalidInput()
        context = context or OperationContext("knowledge-tool-" + uuid4().hex, monotonic() + 180)
        groups = {}
        resources = []
        for name in names:
            resource, model = self.bindings[name]
            resources.append(resource)
            groups.setdefault((model.model_id, model.revision), []).append(resource)
        limit = min(100, top_k * (RERANK_OVERSEARCH_MULTIPLIER if rerank_model else 1))
        threshold, phase = context.remaining(), "query"
        try:
            async with asyncio.timeout(context.remaining()):
                results = []
                for (model_id, revision), scoped in groups.items():
                    context.remaining()
                    scope_ids = {r.knowledge_id for r in scoped}
                    files = None if self.files is None else [f for f in self.files if f.knowledge_id in scope_ids]
                    if files == []:
                        continue
                    response = await self.service.search(KnowledgeSearch(
                        knowledge_ids=[r.knowledge_id for r in scoped], query=query, search_mode=search_mode, top_k=limit,
                        embedding_model=ModelVersion(model_id=model_id, revision=revision),
                        file_ids=[f.file_id for f in files or ()],
                        file_versions={f.file_id: f.file_version for f in files or ()},
                        expected_revisions={r.knowledge_id: r.revision for r in scoped},
                    ), self.actor, context=context)
                    if any(h.knowledge_id not in scope_ids
                           or (files is not None and not any(h.knowledge_id == f.knowledge_id and h.file_id == f.file_id
                                                            and h.file_version == f.file_version for f in files))
                           for h in response.hits):
                        raise ScopeDenied()
                    results.append(response.hits)
                candidates = self._merge(results, limit)
                if candidates and rerank_model:
                    phase = "rerank"
                    output = await self.service.models.invoke(RerankInvocation(
                        model_id=rerank_model.model_id, expected_revision=rerank_model.revision,
                        input={"query": query, "documents": [h.content for h in candidates]}, options={"top_n": top_k},
                    ), self.actor)
                    if normalize_model_revision(output.revision) != normalize_model_revision(rerank_model.revision):
                        raise Conflict()
                    # The same response validator governs direct KB and tool reranking.
                    candidates = [candidates[index].model_copy(update={"score": score, "score_kind": "model.rerank"})
                                  for index, score in rerank_indexes(output.output, len(candidates))]
                phase = "reauthorize"
                await self._reauthorize(resources)
                context.remaining()
                return candidates[:top_k]
        except TimeoutError as error:
            logger.warning("knowledge_tool_timeout operation_id=%s phase=%s timeout_seconds=%s exception_type=%s",
                           context.operation_id, phase, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
