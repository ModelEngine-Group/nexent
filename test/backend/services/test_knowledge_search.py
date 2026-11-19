# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime retrieval calls Model.invoke and checks authoritative visibility twice."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelResult
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeSearch,
    KnowledgeSearchGrant,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import (
    OperationContext,
    Revision,
    SearchHit,
    VectorCollectionInfo,
    VectorKey,
)
from runtime.knowledge_base.search import KnowledgeSearchService

from infrastructure.rdb.knowledge_jobs import JOBS
from test.backend.services.test_knowledge_worker import (
    setup as setup,  # noqa: PLC0414 - Actual jobs and ThreadManager.
)


def with_rerank(request):
    return KnowledgeSearch.model_validate({**request.model_dump(), "rerank_model": {"model_id": 3, "revision": "v1"}})


@pytest.fixture
async def search(setup):
    s = setup
    await s.worker.process(s.lookup, s.actor, owner_id="writer", context=s.context)
    row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    s.closed.clear()
    s.models.invoke.reset_mock()
    s.models.embedding_dimensions.reset_mock()
    request = KnowledgeSearch(knowledge_ids=[1], query="worker", embedding_model={"model_id": 2, "revision": "v1"})
    grant = KnowledgeSearchGrant(knowledge_bases=[{"knowledge_id": 1, "collection": "kb", "resource_tenant_id": s.actor.tenant_id, "embedding_model_id": 2, "revision": "a" * 64}])
    s.client.authorize_knowledge_search = AsyncMock(return_value=grant)
    hit = SearchHit(VectorKey("kb", "one"), 0.8, "elasticsearch.cosine", {
        "knowledge_id": 1, "file_id": s.request.file_id, "file_version": 0, "content": "worker content",
        "embedding_model_id": 2, "embedding_revision": "v1", "filename": "source.txt", "location": {},
    }, Revision(row["attempt_id"]))
    s.vectors.search.return_value = (hit,)
    s.vectors.describe_collection.return_value = VectorCollectionInfo('kb', 2, 'cosine')

    async def invoke(payload, actor):
        assert actor == s.actor
        return ModelResult(revision=payload.expected_revision, output=(
            [[1.0, 0.5]] if payload.operation == "embedding" else [{"index": 0, "relevance_score": 0.9}]))

    s.models.invoke.side_effect = invoke
    s.models.get.side_effect = lambda model_id, actor: type("Metadata", (), {
        "model_id": model_id, "revision": "v1", "model_type": "embedding" if model_id == 2 else "rerank"})()

    @contextmanager
    def ports(*args, **kwargs):
        try:
            yield {1: s.records}, {"kb": s.vectors}
        finally:
            s.closed.append(True)

    service = KnowledgeSearchService(s.client, s.models, ports=ports)
    return s, request, grant, hit, service


@pytest.mark.parametrize("mode,operations", [("semantic", ["embedding"]), ("accurate", []), ("hybrid", ["embedding"])])
async def test_modes_use_model_invoke_and_return_only_authoritative_generation(search, mode, operations):
    s, request, _, _, service = search
    result = await service.search(request.model_copy(update={"search_mode": mode}), s.actor)
    assert len(result.hits) == 1 and result.hits[0].content == "worker content"
    assert result.hits[0].filename == "source.txt" and result.hits[0].file_version == 0
    assert [c.args[0].operation for c in s.models.invoke.call_args_list] == operations
    assert s.closed == [True]
    assert s.client.authorize_knowledge_search.await_count == 2
    assert all(c.args[1:] == ("user", "tenant") for c in s.client.authorize_knowledge_search.call_args_list)


async def test_stale_candidates_never_reach_rerank(search):
    s, request, _, hit, service = search
    s.vectors.search.return_value = (replace(hit, generation=Revision("stale"), payload={**hit.payload, "content": "stale secret"}), hit)
    result = await service.search(with_rerank(request), s.actor)
    rerank = s.models.invoke.call_args.args[0]
    assert rerank.operation == "rerank" and rerank.input.documents == ["worker content"]
    assert result.hits[0].score == 0.9 and result.hits[0].score_kind == "model.rerank"
    assert s.vectors.search.call_args.args[1].limit == request.top_k * 10


@pytest.mark.parametrize("output", [[{"index": True, "relevance_score": 0.1}], [{"index": 1, "relevance_score": 0.1}],
                                     [{"index": 0, "relevance_score": float("nan")}], [{"index": 0, "relevance_score": 0.1}] * 2])
async def test_invalid_rerank_is_rejected_without_original_order_fallback(search, output):
    s, request, _, _, service = search
    s.models.invoke.side_effect = [ModelResult(revision="v1", output=[[1.0, 0.5]]), ModelResult(revision="v1", output=output)]
    with pytest.raises(InvalidInput):
        await service.search(with_rerank(request), s.actor)


async def test_delete_after_rerank_prevents_returning_the_old_generation(search):
    s, request, _, _, service = search
    invoke = s.models.invoke.side_effect

    async def deleting(payload, actor):
        if payload.operation == "rerank":
            await s.db(s.policy.submit, KnowledgeFileDelete(knowledge_id=1, file_id=s.request.file_id, file_version=0, idempotency_key="delete"), context=s.context)
        return await invoke(payload, actor)

    s.models.invoke.side_effect = deleting
    result = await service.search(with_rerank(request), s.actor)
    assert result.hits == []


async def test_grant_mismatch_is_refused_before_model_or_storage(search):
    s, request, grant, _, service = search
    s.client.authorize_knowledge_search.return_value = grant.model_copy(update={"knowledge_bases": []})
    with pytest.raises(ScopeDenied):
        await service.search(request, s.actor)
    s.models.invoke.assert_not_awaited()
    assert s.closed == []


async def test_grant_revision_change_before_return_refuses_all_content(search):
    s, request, grant, _, service = search
    changed = grant.model_copy(update={"knowledge_bases": [grant.knowledge_bases[0].model_copy(update={"revision": "b" * 64})]})
    s.client.authorize_knowledge_search.side_effect = [grant, changed]
    with pytest.raises(Conflict):
        await service.search(request, s.actor)
    assert s.closed == [True]


async def test_query_deadline_cancels_model_and_never_queries_vectors(search):
    s, request, _, _, service = search

    async def blocked(*a):
        await asyncio.Event().wait()

    s.models.invoke.side_effect = blocked
    with pytest.raises(DeadlineExceeded):
        await service.search(request, s.actor, context=OperationContext("deadline", monotonic() + 0.05))
    s.models.invoke.assert_awaited_once()
    s.vectors.search.assert_not_called()


@pytest.mark.parametrize("query,winner", [("worker", "semantic"), ("error 404", "lexical")])
def test_hybrid_preserves_existing_digit_weight_and_keeps_collection_identity(query, winner):
    from runtime.knowledge_base.search import rank_candidates
    payload = {"content": "text"}
    lexical = SearchHit(VectorKey("one", "same"), 10, "text", payload, Revision("v1"))
    semantic = SearchHit(VectorKey("two", "same"), 0.5, "dense", payload, Revision("v1"))
    result = rank_candidates([lexical], [semantic], "hybrid", query)
    assert len(result) == 2
    assert result[0].key.collection == ("one" if winner == "lexical" else "two")


async def test_file_filter_is_applied_in_storage_before_visibility(search):
    s, request, _, _, service = search
    await service.search(request.model_copy(update={"file_ids": [s.request.file_id]}), s.actor)
    assert any(getattr(t, "field", None) == "file_id" and t.value == [s.request.file_id]
               for t in s.vectors.search.call_args.args[1].where.terms)


async def test_file_version_filter_precedes_top_k_and_refuses_new_generation(search):
    from contracts.agentos_knowledge import KnowledgeSearch

    s, request, _, hit, service = search
    payload = request.model_dump() | {"file_ids": [s.request.file_id], "file_versions": {s.request.file_id: 0}}
    request = KnowledgeSearch.model_validate(payload)
    await service.search(request, s.actor)
    terms = s.vectors.search.call_args.args[1].where.terms
    pair = terms[-1].terms[0]
    assert [(t.field, t.value) for t in pair.terms] == [("file_id", s.request.file_id), ("file_version", 0)]
    s.vectors.search.return_value = (replace(hit, payload=hit.payload | {"file_version": 1}),)
    with pytest.raises(ScopeDenied):
        await service.search(request, s.actor)


async def test_wrong_embedding_model_is_refused_before_provider_or_storage(search):
    s, request, grant, _, service = search
    s.client.authorize_knowledge_search.return_value = grant.model_copy(update={"knowledge_bases": [
        grant.knowledge_bases[0].model_copy(update={"embedding_model_id": 9})]})
    with pytest.raises(Conflict):
        await service.search(request, s.actor)
    s.models.invoke.assert_not_awaited()
    s.vectors.search.assert_not_called()


async def test_changed_resource_revision_is_refused_before_models_and_vectors(search):
    s, request, _, _, service = search
    with pytest.raises(Conflict):
        await service.search(request.model_copy(update={"expected_revisions": {1: "b" * 64}}), s.actor)
    s.models.invoke.assert_not_awaited()
    s.vectors.search.assert_not_called()


async def test_embedding_revision_or_shape_never_reaches_vectors(search):
    s, request, _, _, service = search
    for revision, output, error in [("wrong", [[1.0, 0.5]], Conflict), ("v1", [[1.0]], InvalidInput)]:
        s.models.invoke.return_value = ModelResult(revision=revision, output=output)
        s.models.invoke.side_effect = None
        with pytest.raises(error):
            await service.search(request, s.actor)
    s.vectors.search.assert_not_called()
