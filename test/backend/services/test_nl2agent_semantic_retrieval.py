# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for optional semantic retrieval, caching and fallback."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import nl2agent_semantic_retrieval as retrieval
from services.nl2agent_state_service import ResourceScope


def resource(index, name=None):
    return {"candidate_ref": f"tool:{index}", "name": name or f"tool_{index}",
            "names": [name or f"tool_{index}"], "description": "Search public webpages",
            "descriptions": ["检索公开网页"], "labels": ["search"], "installed": True,
            "interfaces": [], "quality": 1.0,
            "resource_type": "tool", "source": "LOCAL_TOOL", "config": [{"value": "secret"}]}


@pytest.mark.parametrize("size,expected", [(0, 0), (2, 2), (5, 3), (80, 3), (1000, 3)])
def test_candidate_budget(size, expected):
    assert retrieval.candidate_budget(size) == expected


async def test_es_ranking_threshold_excludes_names_and_caps_ties(environment):
    _, adapter, _ = environment
    adapter.get_embeddings.side_effect = lambda inputs, **kw: [
        [-1., 0.] if text.startswith("deepseek_search\n") else [1., 0.] for text in inputs]
    catalog = [resource(i) for i in range(80)]
    catalog[-1] = resource(79, "deepseek_search")
    model = await retrieval.resolve_model("tenant")
    result = await retrieval.retrieve("tenant", model, {"r1": "Use deepseek_search"}, catalog, [], None)
    ranked = result["r1"]["installed"]
    assert len(ranked) == 3
    assert "tool:79" not in [row[1]["candidate_ref"] for row in ranked]
    assert ranked[0][1]["candidate_ref"] == "tool:0"
    assert len({row[1]["candidate_ref"] for row in ranked}) == 3
    from services.nl2agent_resource_flow import _candidate
    assert _candidate(catalog[-1], -1.0)["retrieval_score"] == 0.0


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]], [[1]], [[True, 1]], []])
def test_invalid_vectors_rejected(vectors):
    with pytest.raises(ValueError):
        retrieval.validate_vectors(vectors, 1, 2)


@pytest.fixture
def environment(mocker):
    async def inline(_name, fn, *args, lane=None, owner=None, **kwargs):
        return fn(*args, **kwargs)
    mocker.patch.object(retrieval, "run_blocking", side_effect=inline)
    cache = {}
    def index_factory(fingerprint, dimension, version, remaining):
        client = MagicMock()
        client.__enter__.return_value = client
        def key(tenant, ref):
            return fingerprint, tenant, ref
        def snapshots(tenant, rows):
            return {r["candidate_ref"]: {"_source": cache.get(key(tenant, r["candidate_ref"]), {})}
                    for r in rows}
        def put(document, vector, snapshot, **kwargs):
            remaining()
            cache[key(document["tenant_id"], document["candidate_ref"])] = {**document, "embedding": vector}
        def search(tenant, documents, vector, size):
            remaining()
            rows = [(sum(a*b for a,b in zip(cache[key(tenant, d["candidate_ref"])]["embedding"], vector)),
                     d["candidate_ref"]) for d in documents]
            return sorted(rows, key=lambda row: (-row[0], row[1]))[:size]
        client.snapshots.side_effect = snapshots
        client.put.side_effect = put
        client.search.side_effect = search
        return client
    mocker.patch.object(retrieval, "ResourceIndex", side_effect=index_factory)
    def async_index_factory(*args):
        client = index_factory(*args)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.search_chunk = AsyncMock(side_effect=client.search.side_effect)
        return client
    mocker.patch.object(retrieval, "AsyncResourceSearch", side_effect=async_index_factory)
    config = {"model_id": 7, "model_name": "embedding", "model_type": "embedding", "api_key": "private"}
    mocker.patch.object(retrieval.tenant_config_manager, "get_model_config", return_value=config)
    adapter = MagicMock()
    adapter.get_embeddings.side_effect = lambda inputs, **kw: [[1.0, 0.0] for _ in inputs]
    mocker.patch.object(retrieval, "create_embedding_model", return_value=adapter)
    return config, adapter, cache


async def test_cache_reuses_resources_but_query_is_fresh(environment):
    config, adapter, cache = environment
    model = await retrieval.resolve_model("tenant")
    catalog = [resource(1)]
    result = await retrieval.retrieve("tenant", model, {"r1": "联网搜索"}, catalog, [], None)
    assert result["r1"]["installed"][0][1]["name"] == "tool_1"
    first = adapter.get_embeddings.call_count
    await retrieval.retrieve("tenant", model, {"r1": "联网搜索"}, catalog, [], None)
    assert adapter.get_embeddings.call_count == first + 1
    assert all("secret" not in json.dumps(call.args) for call in adapter.get_embeddings.call_args_list)
    assert len(cache) == 1
    catalog[0]["description"] = "Changed capability"
    await retrieval.retrieve("tenant", model, {"r1": "联网搜索"}, catalog, [], None)
    assert len(cache) == 1
    await retrieval.retrieve("other-tenant", model, {"r1": "联网搜索"}, catalog, [], None)
    assert len(cache) == 2


async def test_no_model_does_not_build_adapter(environment, mocker):
    mocker.patch.object(retrieval.tenant_config_manager, "get_model_config", return_value={})
    builder = mocker.patch.object(retrieval, "create_embedding_model")
    assert await retrieval.resolve_model("tenant") is None
    builder.assert_not_called()


async def test_provider_error_is_not_silently_empty(environment):
    _, adapter, _ = environment
    model = await retrieval.resolve_model("tenant")
    adapter.get_embeddings.side_effect = TimeoutError("private endpoint")
    with pytest.raises(TimeoutError):
        await retrieval.retrieve("tenant", model, {"r1": "联网搜索"}, [resource(1)], [], None)


def test_progress_is_scoped_bounded_and_safe(mocker):
    from services.nl2agent_retrieval_progress import ProgressPublisher, read_progress
    client = MagicMock()
    client.incr.return_value = 1
    mocker.patch("services.nl2agent_retrieval_progress.get_redis_client", return_value=client)
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    publisher = ProgressPublisher(scope)
    publisher.publish("preparing_embeddings", 1, 4)
    event = json.loads(client.pipeline.return_value.rpush.call_args.args[1])
    assert event["agent_id"] == 1 and event["run_id"] == "run"
    assert event["completed"] == 1 and event["total"] == 4
    client.lrange.return_value = [json.dumps(event)]
    assert read_progress(scope, 0) == [event]
    assert read_progress(scope, 1) == []


async def test_model_change_invalidates_same_dimension_cache(environment):
    config, adapter, cache = environment
    first = await retrieval.resolve_model("tenant")
    await retrieval.retrieve("tenant", first, {"r1": "search"}, [resource(1)], [], None)
    config["model_name"] = "different-model-same-dimension"
    second = await retrieval.resolve_model("tenant")
    assert first[1] != second[1]
    await retrieval.retrieve("tenant", second, {"r1": "search"}, [resource(1)], [], None)
    assert len(cache) == 2 and adapter.get_embeddings.call_count == 4


@pytest.fixture
def workflow(mocker):
    from services import nl2agent_resource_flow as flow
    state = {}
    scope = ResourceScope("tenant", "user", 1, "2", "run")
    async def update(_scope, change):
        value = change(state.copy() if state else None)
        state.clear()
        state.update(value)
        return state.copy()
    mocker.patch.object(flow, "update_resource_state", side_effect=update)
    mocker.patch.object(flow, "read_resource_state", side_effect=lambda _: state.copy())
    mocker.patch.object(flow, "_progress", new=AsyncMock())
    mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", return_value=[resource(i) for i in range(20)])
    mocker.patch.object(flow.legacy, "_load_internal_uninstalled_resource_catalog", return_value=[])
    return flow, state, scope


async def test_hybrid_union_is_not_truncated_after_each_route(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    flow, state, scope = workflow
    mocker.patch.object(flow.semantic, "resolve_model", return_value=object())
    candidates = [(0.8, resource(i)) for i in range(6)]
    mocker.patch.object(flow.semantic, "retrieve", return_value={"r1": {"installed": candidates, "installable": []}})
    lexical = flow._candidate(resource(19), 0.9)
    mocker.patch.object(flow, "_rank", side_effect=lambda *args, **kw: [lexical] if args[2] else [])
    result = await flow.discover(scope, [RequirementDiscoveryInput(
        query="联网搜索", search_queries={"zh": "联网搜索", "en": "web search"})], "recommend")
    assert result["verification_batch_id"]
    assert len(state["requirements"]["r1"]["installed"]) == 7
    assert state["requirements"]["r1"]["installed"][0] == lexical
    assert len(result["requirements"][0]["installed_candidates"]) == 6
    assert state["requirements"]["r1"]["retrieval_method"] == "hybrid"
    assert "accepted" not in state["requirements"]["r1"]


async def test_embedding_failure_resumes_text_without_retrying_embedding(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    flow, state, scope = workflow
    resolver = mocker.patch.object(flow.semantic, "resolve_model", return_value=object())
    provider = mocker.patch.object(flow.semantic, "retrieve", side_effect=TimeoutError("private"))
    result = await flow.discover(scope, [RequirementDiscoveryInput(query="联网搜索")], "recommend")
    assert result["next_step"] == "prepare_search_queries"
    provider.assert_not_called()
    result = await flow.discover(scope, None, "recommend", search_queries={"r1": {"zh": "联网搜索", "en": "web search"}})
    assert result["verification_batch_id"]
    assert provider.call_count == 1
    assert state["requirements"]["r1"]["retrieval_method"] == "text"


def test_name_fragment_does_not_bypass_threshold(workflow, mocker):
    flow, _, _ = workflow
    catalog = [resource(i, f"deepseek_tool_{i}") for i in range(14)]
    mocker.patch.object(flow.legacy, "_score_resource_requirement", return_value=0.01)
    result = flow._rank("r1", "用DeepSeek检索公开网页", catalog)
    assert result == []
    assert flow._rank("r1", "search", [resource(1, "research_helper")]) == []


async def test_hybrid_deduplicates_without_comparing_scores(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    flow, state, scope = workflow
    mocker.patch.object(flow.semantic, "resolve_model", return_value=object())
    mocker.patch.object(flow, "_rank", side_effect=lambda *a, **kw: [flow._candidate(resource(1), .51)] if a[2] else [])
    mocker.patch.object(flow.semantic, "retrieve", return_value={"r1": {
        "installed": [(0.99, resource(1)), (0.7, resource(2))], "installable": []}})
    await flow.discover(scope, [RequirementDiscoveryInput(
        query="search", search_queries={"zh": "搜索", "en": "search"})], "recommend")
    rows = state["requirements"]["r1"]["installed"]
    assert [r["candidate_ref"] for r in rows] == ["tool:1", "tool:2"]
    assert rows[0]["retrieval_score"] == .51


async def test_no_model_flow_never_calls_vector_path(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    flow, state, scope = workflow
    mocker.patch.object(flow.semantic, "resolve_model", return_value=None)
    provider = mocker.patch.object(flow.semantic, "retrieve")
    cache = mocker.patch.object(flow.semantic, "ResourceIndex")
    await flow.discover(scope, [RequirementDiscoveryInput(
        query="search", search_queries={"zh": "搜索", "en": "search"})], "recommend")
    provider.assert_not_called()
    cache.assert_not_called()
    assert state["requirements"]["r1"]["retrieval_method"] == "text"
    assert "fallback_to_text" not in [call.args[1] for call in flow._progress.call_args_list]
    assert "searching_text" in [call.args[1] for call in flow._progress.call_args_list]


async def test_resolution_error_does_not_claim_configured_semantic_failure(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    flow, state, scope = workflow
    mocker.patch.object(flow.semantic, "resolve_model", side_effect=RuntimeError("model config unreadable"))
    provider = mocker.patch.object(flow.semantic, "retrieve")
    await flow.discover(scope, [RequirementDiscoveryInput(
        query="search", search_queries={"zh": "搜索", "en": "search"})], "recommend")
    provider.assert_not_called()
    assert "fallback_to_text" not in [call.args[1] for call in flow._progress.call_args_list]
    assert state["requirements"]["r1"]["retrieval_method"] == "text"


async def test_irrelevant_changes_reuse_documents_without_rewriting(environment):
    config, adapter, cache = environment
    catalog = [resource(1), resource(2)]
    model = await retrieval.resolve_model("tenant")
    await retrieval.retrieve("tenant", model, {"r1": "search"}, catalog, [], None)
    previous = dict(cache)
    config.update(api_key="rotated", display_name="renamed", update_time="later", chunk_batch=2)
    catalog[0].update(config=[{"value": "new private value"}], update_time="later")
    changed_model = await retrieval.resolve_model("tenant")
    assert changed_model[1] == model[1]
    await retrieval.retrieve("tenant", changed_model, {"r1": "search"}, catalog, [], None)
    assert adapter.get_embeddings.call_count == 3
    assert cache == previous
    catalog[0]["description"] = "Changed capability"
    await retrieval.retrieve("tenant", changed_model, {"r1": "search"}, catalog, [], None)
    assert adapter.get_embeddings.call_args.args[0] == [retrieval._text(catalog[0])]
    assert len(cache) == 2 and cache != previous


@pytest.mark.parametrize("field,value", [("model_id", 8), ("model_name", "new"),
    ("base_url", "http://new-provider"), ("embedding_dim", 3), ("model_factory", "new-vendor")])
async def test_embedding_identity_fields_change_fingerprint(environment, field, value):
    config, _, _ = environment
    first = await retrieval.resolve_model("tenant")
    config[field] = value
    second = await retrieval.resolve_model("tenant")
    assert first[1] != second[1]


@pytest.mark.parametrize("value", [{}, {"resource_revision": "old"}])
async def test_missing_or_outdated_document_rebuilt(environment, value):
    _, adapter, cache = environment
    model = await retrieval.resolve_model("tenant")
    await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(1)], [], None)
    key = next(iter(cache))
    cache[key] = value
    await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(1)], [], None)
    assert adapter.get_embeddings.call_count == 4
    assert cache[key]["embedding"] == [1, 0]


async def test_same_request_queries_deduplicated_and_transport_bounded(environment):
    _, adapter, _ = environment
    model = await retrieval.resolve_model("tenant")
    result = await retrieval.retrieve("tenant", model, {"r1": "search", "r2": "search"},
                                      [resource(i) for i in range(17)], [], None)
    assert all(len(c.args[0]) <= 8 for c in adapter.get_embeddings.call_args_list)
    assert adapter.get_embeddings.call_args_list[0].args[0] == ["search"]
    assert result["r1"] == result["r2"]


async def test_duplicate_queries_share_actual_searches_and_one_preparation(environment, mocker):
    _, adapter, _ = environment
    clients = []
    original = retrieval.AsyncResourceSearch.side_effect

    def observed(*args):
        client = original(*args)
        clients.append(client)
        return client

    retrieval.AsyncResourceSearch.side_effect = observed
    model = await retrieval.resolve_model("tenant")
    results = await retrieval.retrieve("tenant", model,
        {"a": "search", "b": "search", "c": "search"}, [resource(1)], [], None)
    assert results["a"] == results["b"] == results["c"]
    assert retrieval.ResourceIndex.call_count == 1
    assert len(clients) == 1 and clients[0].search_chunk.await_count == 1
    assert adapter.get_embeddings.call_args_list[0].args[0] == ["search"]
    clients[0].__aexit__.assert_awaited_once()


async def test_search_chunks_preserve_global_top3_and_threshold(environment, mocker):
    _, adapter, _ = environment
    adapter.get_embeddings.side_effect = lambda texts, **kw: [
        [-1., 0.] if text.startswith("deepseek_search\n") else [1., 0.] for text in texts]
    mocker.patch.object(retrieval, "FILTER_BATCH_SIZE", 3)
    catalog = [resource(i) for i in range(80)]
    catalog[-1] = resource(79, "deepseek_search")
    model = await retrieval.resolve_model("tenant")
    result = await retrieval.retrieve("tenant", model,
        {"a": "Use deepseek_search", "b": "Use deepseek_search"}, catalog, [], None)
    selected = result["a"]["installed"]
    assert result["a"] == result["b"]
    assert len(selected) == 3
    assert [row[1]["candidate_ref"] for row in selected] == sorted(
        row["candidate_ref"] for row in catalog[:-1])[:3]


async def test_empty_authorized_catalog_does_not_open_index_or_embed(environment, mocker):
    _, adapter, _ = environment
    index = mocker.patch.object(retrieval, "ResourceIndex")
    model = await retrieval.resolve_model("tenant")
    assert await retrieval.retrieve("tenant", model, {"r1": "search"}, [], [], None) == {
        "r1": {"installed": [], "installable": []}}
    index.assert_not_called()
    adapter.get_embeddings.assert_not_called()


async def test_budget_prevents_later_batches_but_retains_completed_cache(environment, mocker):
    _, adapter, cache = environment
    clock = [0.0]
    mocker.patch.object(retrieval, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def slow(inputs, **kwargs):
        if inputs != ["search"]:
            clock[0] += 45
        return [[1., 0.] for _ in inputs]
    adapter.get_embeddings.side_effect = slow
    model = await retrieval.resolve_model("tenant")
    with pytest.raises(TimeoutError):
        await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(i) for i in range(17)], [], None)
    assert adapter.get_embeddings.call_count == 4
    assert len(cache) == 16
    retrieval.AsyncResourceSearch.assert_not_called()


async def test_cold_initialization_has_independent_search_budget(environment, mocker):
    _, adapter, cache = environment
    clock = [0.0]
    mocker.patch.object(retrieval, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    budgets = []
    def embed(inputs, **kwargs):
        budgets.append(kwargs["timeout"])
        if inputs != ["search"]:
            clock[0] += 4
        return [[1., 0.] for _ in inputs]
    adapter.get_embeddings.side_effect = embed
    original = retrieval.AsyncResourceSearch.side_effect
    search_budgets = []
    def observe_search(*args):
        search_budgets.append(args[-1]())
        return original(*args)
    retrieval.AsyncResourceSearch.side_effect = observe_search
    model = await retrieval.resolve_model("tenant")
    result = await retrieval.retrieve("tenant", model, {"r1": "search"},
                                      [resource(i) for i in range(17)], [], None)
    assert clock[0] == 12 and len(cache) == 17
    assert result["r1"]["installed"]
    assert budgets == [120, 120, 116, 112]
    assert search_budgets == [10]


async def test_search_outer_timeout_closes_client_and_identifies_phase(environment, mocker):
    model = await retrieval.resolve_model("tenant")
    original = retrieval.AsyncResourceSearch.side_effect
    clients = []
    async def stalled(*args):
        await asyncio.Event().wait()
    def observe_search(*args):
        client = original(*args)
        client.search_chunk.side_effect = stalled
        clients.append(client)
        return client
    retrieval.AsyncResourceSearch.side_effect = observe_search
    mocker.patch.object(retrieval, "RETRIEVAL_TIMEOUT", .02)
    with pytest.raises(TimeoutError) as caught:
        await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(1)], [], None)
    assert caught.value.phase == "search"
    assert caught.value.threshold_seconds == .02
    clients[0].__aexit__.assert_awaited_once()


async def test_outer_deadline_stops_worker_and_cancellation_propagates(mocker):
    captured = []
    async def waiting(*args, **kwargs):
        captured.append(args[-1])
        await asyncio.Event().wait()
    mocker.patch.object(retrieval, "run_blocking", side_effect=waiting)
    mocker.patch.object(retrieval, "PREPARATION_TIMEOUT", 0.02, create=True)
    with pytest.raises(TimeoutError) as caught:
        await retrieval.retrieve("tenant", object(), {"r1": "search"}, [], [], None)
    assert caught.value.phase == "preparation"
    assert caught.value.threshold_seconds == .02
    assert captured[-1].is_set()
    task = asyncio.create_task(retrieval.retrieve("tenant", object(), {"r1": "search"}, [], [], None))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captured[-1].is_set()


async def test_index_error_propagates_for_authorized_lexical_fallback(environment, mocker):
    _, adapter, _ = environment
    mocker.patch.object(retrieval, "ResourceIndex", side_effect=TimeoutError("index unavailable"))
    model = await retrieval.resolve_model("tenant")
    with pytest.raises(TimeoutError) as caught:
        await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(1)], [], None)
    assert caught.value.phase == "preparation"
    assert str(caught.value.__cause__) == "index unavailable"
    assert adapter.get_embeddings.call_count == 1


@pytest.mark.parametrize("reason", ["capacity", "queue_timeout"])
async def test_managed_preparation_rejection_does_not_start_search(mocker, reason):
    from nexent.core.concurrency import ThreadCapacityExceeded, ThreadQueueTimedOut

    error = (ThreadCapacityExceeded("model-tool-io", 1, 0) if reason == "capacity"
             else ThreadQueueTimedOut("model-tool-io", .01))
    managed = mocker.patch.object(retrieval, "run_blocking", side_effect=error)
    preparation = mocker.patch.object(retrieval, "ResourceIndex")
    search = mocker.patch.object(retrieval, "AsyncResourceSearch")
    with pytest.raises(type(error)):
        await retrieval.retrieve("tenant", object(), {"r": "search"}, [resource(1)], [], None)
    assert managed.call_args.args[-1].is_set()
    preparation.assert_not_called()
    search.assert_not_called()


async def test_removed_resource_is_not_reintroduced_by_cache(environment):
    _, adapter, _ = environment
    model = await retrieval.resolve_model("tenant")
    await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(1), resource(2)], [], None)
    result = await retrieval.retrieve("tenant", model, {"r1": "search"}, [resource(2)], [], None)
    assert [r[1]["candidate_ref"] for r in result["r1"]["installed"]] == ["tool:2"]
    assert adapter.get_embeddings.call_count == 3


async def test_candidate_revoked_during_es_search_is_not_disclosed(workflow, mocker):
    from contracts.nl2agent_resources import RequirementDiscoveryInput
    from services.nl2agent_state_service import ResourceStateError
    flow, state, scope = workflow
    initial = [resource(1)]
    mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", side_effect=[initial, []])
    mocker.patch.object(flow.semantic, "resolve_model", return_value=object())
    mocker.patch.object(flow.semantic, "retrieve", return_value={"r1": {
        "installed": [(1., resource(1))], "installable": []}})
    with pytest.raises(ResourceStateError, match="resource_evidence_changed"):
        await flow.discover(scope, [RequirementDiscoveryInput(
            query="search", search_queries={"zh": "搜索", "en": "search"})], "recommend")
    assert "installed" not in state["requirements"]["r1"]


async def test_adapter_and_fingerprint_use_one_configuration_snapshot(environment):
    config, _, _ = environment
    model = await retrieval.resolve_model("tenant")
    supplied = retrieval.create_embedding_model.call_args.args[0]
    assert supplied == config and supplied is not config
    config["model_name"] = "changed-after-resolution"
    assert supplied["model_name"] == "embedding"
    assert model[1] != (await retrieval.resolve_model("tenant"))[1]
