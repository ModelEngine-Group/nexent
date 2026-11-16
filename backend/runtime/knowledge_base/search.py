# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorized Runtime retrieval and reranking with final manifest visibility checks."""

import asyncio
import logging
import math
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from contracts.agentos import EmbeddingInvocation, RerankInvocation
from contracts.agentos_knowledge import (
    KnowledgeSearch,
    KnowledgeSearchAuthorization,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
)
from nexent.core.concurrency import run_blocking
from nexent.core.utils.constants import RERANK_OVERSEARCH_MULTIPLIER
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
)
from nexent.storage.models import Comparison, Junction, OperationContext, SearchQuery
from runtime.knowledge_base.ingestion import embedding_vectors
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.agent_model_config import normalize_model_revision
from infrastructure.knowledge_runtime import knowledge_search_ports

logger = logging.getLogger(__name__)


def _identity(hit):
    return hit.key.collection, hit.key.key, hit.generation.value if hit.generation else ""


def rank_candidates(lexical, semantic, mode, query):
    if mode != "hybrid":
        return sorted(lexical if mode == "accurate" else semantic, key=lambda h: (-h.score, _identity(h)))
    weight = 0.7 if any(char.isdigit() for char in query) else 0.3
    maxima = [max((hit.score for hit in branch), default=1) for branch in (lexical, semantic)]
    merged = {}
    for branch, maximum, factor, name in zip((lexical, semantic), maxima, (weight, 1 - weight), ("accurate", "semantic"), strict=True):
        for hit in branch:
            key = _identity(hit)
            normalized = hit.score / maximum if maximum > 0 else 0
            previous = merged.get(key)
            scores = {"accurate": 0.0, "semantic": 0.0} if previous is None else dict(previous.scores)
            scores[name] = normalized
            highlights = tuple(dict.fromkeys((previous.highlights if previous else ()) + hit.highlights))
            merged[key] = replace(hit, score=factor * normalized + (previous.score if previous else 0),
                                  score_kind="runtime.hybrid", scores=scores, highlights=highlights)
    return sorted(merged.values(), key=lambda h: (-h.score, _identity(h)))


class KnowledgeSearchService:
    def __init__(self, authorization_client, models, *, ports=knowledge_search_ports, operation_seconds=180):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
            raise InvalidInput()
        self.client, self.models, self.ports, self.operation_seconds = authorization_client, models, ports, operation_seconds

    async def _blocking(self, method, *args, context):
        def execute():
            context.remaining()
            value = method(*args, context=context)
            context.remaining()
            return value
        return await run_blocking("knowledge-search", execute, lane="control-io", owner="runtime.knowledge_base")

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_search(
            KnowledgeSearchAuthorization(knowledge_ids=request.knowledge_ids), actor.user_id, actor.tenant_id)
        if ([g.knowledge_id for g in grant.knowledge_bases] != request.knowledge_ids
                or len({g.collection for g in grant.knowledge_bases}) != len(grant.knowledge_bases)):
            raise ScopeDenied()
        if any(g.embedding_model_id != request.embedding_model.model_id for g in grant.knowledge_bases):
            raise Conflict()
        return grant

    async def _invoke(self, payload, actor):
        result = await self.models.invoke(payload, actor)
        if normalize_model_revision(result.revision) != normalize_model_revision(payload.expected_revision):
            raise Conflict()
        return result.output

    @staticmethod
    def _dto(hit):
        details = dict(hit.scores)
        if hit.highlights:
            details["retrieval_highlight_terms"] = list(hit.highlights)
        return KnowledgeSearchHit(
            **{name: hit.payload[name] for name in ("knowledge_id", "file_id", "file_version", "content")},
            filename=hit.payload.get("filename", ""), location=hit.payload.get("location", {}),
            chunk_id=hit.key.key, score=hit.score, score_kind=hit.score_kind,
            score_details=details,
        )

    def _visible(self, records, grant, request, hits, *, context):
        policy = KnowledgeJobs(records, authorize=lambda *a, **kw: None)
        allowed = {g.collection: g.knowledge_id for g in grant.knowledge_bases}
        result = []
        for hit in hits:
            reference = self._dto(hit)
            if allowed.get(hit.key.collection) != reference.knowledge_id:
                raise ScopeDenied()
            if request.file_ids and reference.file_id not in request.file_ids:
                raise ScopeDenied()
            if (hit.payload.get("embedding_model_id") != request.embedding_model.model_id
                or normalize_model_revision(hit.payload.get("embedding_revision"))
                != normalize_model_revision(request.embedding_model.revision)):
                continue
            if hit.generation and policy.is_visible(reference, hit.generation.value, context=context):
                result.append(hit)
        return result

    @staticmethod
    def _collect(vectors, grant, request, query_vector, limit, *, context):
        lexical, semantic = [], []
        for resource in grant.knowledge_bases:
            port = vectors[resource.collection]
            try:
                port.describe_collection(resource.collection, context=context)
            except NotFound:
                continue
            terms = [Comparison("knowledge_id", "eq", resource.knowledge_id),
                     Comparison("embedding_model_id", "eq", request.embedding_model.model_id)]
            if request.file_ids:
                terms.append(Comparison("file_id", "in", request.file_ids))
            where = Junction("and", tuple(terms))
            if request.search_mode in {"accurate", "hybrid"}:
                lexical.extend(port.search(resource.collection, SearchQuery(text=request.query, mode="weighted_text", where=where, limit=limit), context=context))
            if request.search_mode in {"semantic", "hybrid"}:
                semantic.extend(port.search(resource.collection, SearchQuery(vector=query_vector, where=where, limit=limit), context=context))
        return lexical, semantic

    @staticmethod
    def _reranked(output, candidates):
        if not isinstance(output, list) or len(output) > len(candidates):
            raise InvalidInput()
        seen, ranked = set(), []
        for item in output:
            if not isinstance(item, dict):
                raise InvalidInput()
            index, score = item.get("index"), item.get("relevance_score")
            if (type(index) is not int or not 0 <= index < len(candidates) or index in seen
                or type(score) not in {int, float}):
                raise InvalidInput()
            try:
                score = float(score)
            except OverflowError as error:
                raise InvalidInput() from error
            if not math.isfinite(score):
                raise InvalidInput()
            seen.add(index)
            ranked.append(replace(candidates[index], score=score, score_kind="model.rerank"))
        return ranked

    async def search(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeSearch):
            raise InvalidInput()
        context = context or OperationContext("knowledge-search-" + uuid4().hex, monotonic() + self.operation_seconds)
        threshold = context.remaining()
        try:
            async with asyncio.timeout(threshold):
                grant = await self._grant(request, actor)
                dimensions = await self.models.embedding_dimensions(request.embedding_model, actor)
                if request.rerank_model:
                    binding = request.rerank_model
                    model = await self.models.get(binding.model_id, actor)
                    if (model.model_type != "rerank" or model.model_id != binding.model_id
                        or normalize_model_revision(model.revision) != normalize_model_revision(binding.revision)):
                        raise Conflict()
                query_vector = None
                if request.search_mode != "accurate":
                    output = await self._invoke(EmbeddingInvocation(
                        model_id=request.embedding_model.model_id, expected_revision=request.embedding_model.revision,
                        input=[request.query]), actor)
                    query_vector = embedding_vectors(output, 1, dimensions)[0]
                limit = request.top_k * (RERANK_OVERSEARCH_MULTIPLIER if request.rerank_model else 1)
                with self.ports(actor, grant, dimensions, context=context) as (records, vectors):
                    lexical, semantic = await self._blocking(self._collect, vectors, grant, request, query_vector, limit, context=context)
                    lexical = await self._blocking(self._visible, records, grant, request, lexical, context=context)
                    semantic = await self._blocking(self._visible, records, grant, request, semantic, context=context)
                    candidates = rank_candidates(lexical, semantic, request.search_mode, request.query)[:limit]
                    if request.rerank_model and candidates:
                        output = await self._invoke(RerankInvocation(
                            model_id=request.rerank_model.model_id, expected_revision=request.rerank_model.revision,
                            input={"query": request.query, "documents": [h.payload["content"] for h in candidates]},
                            options={"top_n": request.top_k}), actor)
                        candidates = self._reranked(output, candidates)
                    if await self._grant(request, actor) != grant:
                        raise Conflict()
                    candidates = await self._blocking(self._visible, records, grant, request, candidates, context=context)
                    return KnowledgeSearchResult(hits=[self._dto(h) for h in candidates[:request.top_k]],
                                                 embedding_model=request.embedding_model, rerank_model=request.rerank_model)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning("knowledge_search_timeout operation_id=%s phase=query timeout_seconds=%s exception_type=%s",
                           context.operation_id, threshold, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
