# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata, ModelResult
from contracts.agentos_knowledge import KnowledgeSearchHit, KnowledgeSearchResult
from contracts.errors.exceptions import RuntimeUpstreamError
from management.services.knowledge_base import hybrid
from management.services.knowledge_base.common import KnowledgeBaseNeedsModelConfigError
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def query_search(monkeypatch):
    async def run(_action, method, *args, lane, owner, **kwargs):
        assert lane == "control-io" and owner == hybrid.__name__
        return method(*args, **kwargs)

    monkeypatch.setattr(hybrid, "run_blocking", run)
    reader = Mock()
    reader.knowledge.return_value = {"embedding_model_id": 7}
    client = AsyncMock()
    client.get_model.return_value = ModelMetadata(
        model_id=7, revision="r2", model_type="multi_embedding", display_name=None,
    )
    client.invoke_model.return_value = ModelResult(revision="r2", output=[[0.2, 0.3]])
    vectors = Mock()
    vectors.hybrid_search.return_value = [
        {"index": "kb", "score": .8, "document": {"filename": "image", "score_details": {"prior": 7}},
         "scores": {"semantic": .9}, "highlight_terms": ["query"]},
        {"index": "shared", "score": .4, "document": {"arbitrary": [1, "form"]}},
    ]
    return SimpleNamespace(actor=ServicePrincipal("operator", "tenant"), reader=reader, client=client, vectors=vectors)


async def search(s, **options):
    args = {"index_names": ["kb", "shared"], "query": "query", "top_k": 5, "weight_accurate": None} | options
    return await hybrid.search_public_hybrid(
        **args, actor=s.actor, reader=s.reader, client=s.client, vdb_core=s.vectors,
    )


@pytest.fixture
def runtime_search(query_search):
    s = query_search
    s.resources = {name: {"knowledge_id": key, "index_name": name, "embedding_model_id": 7, "tenant_id": "tenant"}
                   for name, key in (("kb", 1), ("shared", 2))}
    s.reader.knowledge.side_effect = lambda name, actor, **kwargs: s.resources[name]
    text = KnowledgeSearchHit(knowledge_id=1, chunk_id="actual", content="text", score=.9,
        score_kind="runtime.hybrid", score_details={"accurate": 1, "retrieval_highlight_terms": ["text"]},
        public_document={"id": "display-id", "score_details": {"source": 9}, "content": "text"})
    image = KnowledgeSearchHit(knowledge_id=2, chunk_id="picture", content="caption", score=.4,
        score_kind="elasticsearch.cosine", public_document={"id": "picture", "content": "caption"})
    s.client.search_knowledge.return_value = KnowledgeSearchResult(hits=[text], image_hits=[image],
        data_revisions={1: "a" * 64, 2: "b" * 64}, embedding_model={"model_id": 7, "revision": "r2"})
    return s


async def runtime_query(s):
    return await hybrid.search_runtime_hybrid(["kb", "shared", "kb"], "query 2", s.actor, top_k=5,
        weight_accurate=None, reader=s.reader, client=s.client)


async def test_runtime_hybrid_preserves_envelope_and_query_authority(runtime_search):
    s = runtime_search
    result = await runtime_query(s)
    request, user, tenant = s.client.search_knowledge.await_args.args
    assert request.knowledge_ids == [1, 2] and set(request.expected_revisions) == {1, 2}
    assert request.embedding_model.revision == "r2" and request.weight_accurate == .7
    assert request.top_k == 5 and request.split_multimodal_candidates and request.merge_display_ids
    assert request.global_hybrid_candidates and request.include_public_document
    assert (user, tenant) == (s.actor.user_id, s.actor.tenant_id)
    assert result["results"] == [
        {"id": "display-id", "index": "kb", "content": "text", "score": .9,
         "score_details": {"source": 9, "accurate": 1, "retrieval_highlight_terms": ["text"]}},
        {"id": "picture", "index": "shared", "content": "caption", "score": .4},
    ]
    assert result["total"] == 2 and result["query_time_ms"] >= 0
    s.client.invoke_model.assert_not_awaited()
    s.vectors.hybrid_search.assert_not_called()


async def test_runtime_hybrid_blocks_mixed_models_before_retrieval(runtime_search):
    s = runtime_search
    s.resources["shared"]["embedding_model_id"] = 8
    with pytest.raises(Conflict):
        await runtime_query(s)
    s.client.search_knowledge.assert_not_awaited()
    s.vectors.hybrid_search.assert_not_called()


@pytest.mark.parametrize("status,error", [(403, ScopeDenied), (409, Conflict)])
async def test_runtime_hybrid_redacts_remote_errors_without_legacy_replay(runtime_search, status, error):
    s = runtime_search
    s.client.search_knowledge.side_effect = RuntimeUpstreamError(status, b"private", {})
    with pytest.raises(error):
        await runtime_query(s)
    s.client.search_knowledge.assert_awaited_once()
    s.vectors.hybrid_search.assert_not_called()


async def test_northbound_cutover_uses_agentos_without_constructing_elasticsearch(monkeypatch):
    from contracts.constants import environment
    from management.db.knowledge_base import repository
    from management.services.knowledge_base import common
    from management.services.northbound import search_hybrid_for_northbound

    monkeypatch.setattr(environment, "KNOWLEDGE_RUNTIME_HYBRID_ENABLED", True)
    monkeypatch.setattr(repository, "get_index_name_by_knowledge_name", lambda name, tenant: "resolved")
    legacy = Mock()
    monkeypatch.setattr(common, "get_vector_db_core", legacy)
    runtime = AsyncMock(return_value={"results": [], "total": 0})
    monkeypatch.setattr(hybrid, "search_runtime_hybrid", runtime)
    ctx = SimpleNamespace(user_id="operator", tenant_id="tenant")
    payload = SimpleNamespace(index_names=["requested"], query="query", weight_accurate=.5, top_k=5)

    assert await search_hybrid_for_northbound(ctx, payload) == {"results": [], "total": 0}
    runtime.assert_awaited_once_with(["resolved"], "query", ServicePrincipal("operator", "tenant"),
                                     top_k=5, weight_accurate=.5, northbound=True)
    legacy.assert_not_called()


@pytest.mark.parametrize(("query", "weight", "expected"), [
    ("query", None, .5), ("query 42", None, .7), ("query", 0, 0), ("query", 1, 1),
])
async def test_first_index_invoke_is_pinned_and_existing_retrieval_projection_is_preserved(query_search, query, weight, expected):
    s = query_search
    result = await search(s, query=query, weight_accurate=weight)

    s.reader.knowledge.assert_called_once()
    assert s.reader.knowledge.call_args.args == ("kb", s.actor)
    s.client.get_model.assert_awaited_once_with(7, user_id="operator", tenant_id="tenant")
    request, user, tenant = s.client.invoke_model.await_args.args
    assert (request.model_id, request.expected_revision, request.input, user, tenant) == (7, "r2", [query], "operator", "tenant")
    s.vectors.hybrid_search.assert_called_once_with(
        index_names=["kb", "shared"], query_text=query, query_embedding=[.2, .3],
        top_k=5, weight_accurate=expected, embedding_model=SimpleNamespace(model_type="multimodal"),
    )
    assert result["total"] == 2 and result["query_time_ms"] >= 0
    assert result["results"] == [
        {"filename": "image", "score": .8, "index": "kb",
         "score_details": {"prior": 7, "semantic": .9, "retrieval_highlight_terms": ["query"]}},
        {"arbitrary": [1, "form"], "score": .4, "index": "shared"},
    ]


@pytest.mark.parametrize("arguments", [
    {"query": " "}, {"index_names": []}, {"top_k": 0}, {"weight_accurate": 1.1},
])
async def test_invalid_search_never_reaches_model_or_storage(query_search, arguments):
    s = query_search
    with pytest.raises(ValueError):
        await search(s, **arguments)
    s.reader.knowledge.assert_not_called()
    s.client.invoke_model.assert_not_awaited()
    s.vectors.hybrid_search.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "gone", "wrong-modality"])
async def test_missing_binding_retains_configuration_error(query_search, fault):
    s = query_search
    if fault == "missing":
        s.reader.knowledge.return_value = {"embedding_model_id": None}
    elif fault == "gone":
        s.client.get_model.side_effect = RuntimeUpstreamError(404, b"", {})
    else:
        s.client.get_model.return_value.model_type = "chat"
    with pytest.raises(KnowledgeBaseNeedsModelConfigError) as error:
        await search(s)
    assert error.value.index_name == "kb"
    s.client.invoke_model.assert_not_awaited()
    s.vectors.hybrid_search.assert_not_called()


async def test_timed_out_model_is_not_replayed_or_passed_to_elasticsearch(query_search):
    s = query_search
    s.client.invoke_model.side_effect = TimeoutError
    with pytest.raises(DeadlineExceeded):
        await search(s)
    s.client.invoke_model.assert_awaited_once()
    s.vectors.hybrid_search.assert_not_called()


async def test_elasticsearch_failure_does_not_reinvoke_model(query_search):
    s = query_search
    s.vectors.hybrid_search.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        await search(s)
    s.client.invoke_model.assert_awaited_once()
    s.vectors.hybrid_search.assert_called_once()


async def test_northbound_passes_original_actor_and_handles_unresolved_name(monkeypatch):
    from contracts.knowledge import HybridSearchRequest
    from management.db.knowledge_base import repository
    from management.services.knowledge_base import common
    from management.services.northbound import search_hybrid_for_northbound

    lookup = Mock(side_effect=["mapped", RuntimeError("lookup failed")])
    monkeypatch.setattr(repository, "get_index_name_by_knowledge_name", lookup)
    vectors = object()
    monkeypatch.setattr(common, "get_vector_db_core", Mock(return_value=vectors))
    search = AsyncMock(return_value={"results": [], "total": 0})
    monkeypatch.setattr(hybrid, "search_public_hybrid", search)
    payload = HybridSearchRequest(index_names=["name", "raw"], query="query", top_k=5)
    ctx = SimpleNamespace(user_id="key-user", tenant_id="asset-tenant")

    assert await search_hybrid_for_northbound(ctx, payload) == {"results": [], "total": 0}
    search.assert_awaited_once_with(["mapped", "raw"], "query", ServicePrincipal("key-user", "asset-tenant"),
                                    top_k=5, weight_accurate=payload.weight_accurate, vdb_core=vectors)
