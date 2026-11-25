# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit boundaries for ES authorization, identity, freshness and concurrency."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from elasticsearch import BadRequestError, ConflictError

from management.services.conversation import nl2agent_resource_index as storage


def document(ref="tool:1", tenant="tenant", text="Safe capability"):
    return storage.projection(tenant, {"candidate_ref": ref, "resource_type": "tool",
        "source": "LOCAL_TOOL", "config": {"token": "private"}}, text, "model", 3)


@pytest.fixture
def index():
    client = MagicMock()
    client.options.return_value = client
    client.cluster.health.return_value = {"status": "yellow", "timed_out": False,
                                          "active_primary_shards": 1, "unassigned_primary_shards": 0}
    store = storage.ResourceIndex("model", 2, 3, lambda: 2.0, client=client)
    return store, client


def response(documents, scores=None):
    return {"hits": {"total": {"value": len(documents)}, "hits": [
        {"_source": d, "_score": score} for d, score in zip(documents, scores or [1.5]*len(documents))]},
        "_shards": {"failed": 0}, "timed_out": False}


def test_identity_and_projection_exclude_private_fields():
    assert storage.document_id("tenant", "tool:1") != storage.document_id("other", "tool:1")
    assert storage.document_id("tenant", "tool:1") != storage.document_id("tenant", "skill:1")
    assert "private" not in str(document()) and "config" not in document()
    assert document()["resource_revision"] != document(text="Changed")["resource_revision"]


def test_search_filters_before_scoring_and_restores_cosine(index):
    store, client = index
    doc = document()
    client.search.return_value = response([doc], [0.25])
    assert store.search("tenant", [doc], [1., 0.], 1) == [(-.75, "tool:1")]
    args = client.search.call_args.kwargs
    filters = args["query"]["script_score"]["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant"}} in filters
    assert {"terms": {"candidate_ref": ["tool:1"]}} in filters
    assert {"terms": {"resource_revision": [doc["resource_revision"]]}} in filters
    assert args["allow_partial_search_results"] is False
    assert "embedding" not in args["source_includes"]
    assert client.options.call_args.kwargs == {
        "request_timeout": 2., "max_retries": 0, "retry_on_timeout": False}


def test_empty_scope_does_not_call_es(index):
    store, client = index
    assert store.search("tenant", [], [1., 0.], 5) == []
    client.search.assert_not_called()


@pytest.mark.parametrize("change", ["tenant", "ref", "revision", "timeout", "shards", "missing", "nan"])
def test_invalid_or_partial_results_are_rejected(index, change):
    store, client = index
    doc = document()
    value = response([dict(doc)])
    if change == "tenant":
        value["hits"]["hits"][0]["_source"]["tenant_id"] = "other"
    elif change == "ref":
        value["hits"]["hits"][0]["_source"]["candidate_ref"] = "tool:private"
    elif change == "revision":
        value["hits"]["hits"][0]["_source"]["resource_revision"] = "old"
    elif change == "timeout":
        value["timed_out"] = True
    elif change == "shards":
        value["_shards"]["failed"] = 1
    elif change == "missing":
        value["hits"]["total"]["value"] = 0
    else:
        value["hits"]["hits"][0]["_score"] = float("nan")
    client.search.return_value = value
    with pytest.raises((ValueError, TimeoutError)):
        store.search("tenant", [doc], [1., 0.], 1)


def test_chunked_scopes_preserve_global_top_k(index, monkeypatch):
    store, client = index
    monkeypatch.setattr(storage, "FILTER_BATCH_SIZE", 1)
    docs = [document("tool:1"), document("tool:2"), document("tool:3")]
    client.search.side_effect = [response([doc], [score]) for doc, score in zip(docs, [1.1, 1.9, 1.5])]
    assert store.search("tenant", docs, [1., 0.], 2) == [(pytest.approx(.9), "tool:2"), (.5, "tool:3")]
    assert client.search.call_count == 3
    assert all(len(call.kwargs["query"]["script_score"]["query"]["bool"]["filter"][3]["terms"]["candidate_ref"]) == 1
               for call in client.search.call_args_list)


def test_update_uses_cas_and_waits_for_search_visibility(index):
    store, client = index
    doc = document()
    store.put(doc, [1., 0.], {"found": True, "_seq_no": 4, "_primary_term": 2})
    args = client.index.call_args.kwargs
    assert args["id"] == storage.document_id("tenant", "tool:1")
    assert args["if_seq_no"] == 4 and args["if_primary_term"] == 2
    assert args["refresh"] == "wait_for" and "ttl" not in args


def test_concurrent_newer_write_is_not_overwritten(index, monkeypatch):
    store, client = index
    client.index.side_effect = ConflictError("conflict", MagicMock(), {})
    monkeypatch.setattr(store, "snapshots", lambda *a: {"tool:1": {"_source": document(text="Newer")}})
    with pytest.raises(ValueError, match="changed"):
        store.put(document(), [1., 0.], {"found": False})
    assert client.index.call_count == 1


def test_snapshots_do_not_fetch_vectors_and_reject_partial_mget(index):
    store, client = index
    client.mget.return_value = {"docs": []}
    with pytest.raises(ValueError, match="Incomplete"):
        store.snapshots("tenant", [document()])
    assert "embedding" not in client.mget.call_args.kwargs["source_includes"]


def test_worker_closes_its_client(index):
    store, client = index
    with store:
        pass
    client.close.assert_called_once()


def test_concurrent_index_creation_waits_for_primary_with_shared_budget(index):
    store, client = index
    client.indices.create.side_effect = BadRequestError("resource_already_exists_exception", MagicMock(), {})
    with store:
        pass
    assert client.cluster.health.call_args.kwargs == {
        "index": store.name, "wait_for_status": "yellow", "wait_for_active_shards": "1",
        "wait_for_no_initializing_shards": True, "timeout": "2000ms"}
    client.close.assert_called_once()


@pytest.mark.parametrize("health", [{"status": "red"}, {"status": "yellow", "timed_out": True},
    {"status": "yellow", "timed_out": False, "active_primary_shards": 0, "unassigned_primary_shards": 1}])
def test_unready_primary_fails_and_closes_client(index, health):
    store, client = index
    client.cluster.health.return_value = health
    with pytest.raises(TimeoutError, match="primary shard"):
        with store:
            pytest.fail("Unready index must not be used")
    client.close.assert_called_once()


async def test_async_transport_preserves_filters_timeout_and_closes():
    client = MagicMock()
    client.options.return_value = client
    client.search = AsyncMock(return_value=response([document()], [1.75]))
    client.close = AsyncMock()
    async with storage.AsyncResourceSearch("model", 2, 3, lambda: .8, client=client) as index:
        assert await index.search_chunk("tenant", [document()], [1., 0.], 1) == [(.75, "tool:1")]
    filters = client.search.call_args.kwargs["query"]["script_score"]["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant"}} in filters
    assert {"terms": {"candidate_ref": ["tool:1"]}} in filters
    assert {"terms": {"resource_revision": [document()["resource_revision"]]}} in filters
    assert client.options.call_args.kwargs["request_timeout"] == .8
    client.close.assert_awaited_once()


async def test_async_transport_closed_when_cancelled():
    client = MagicMock()
    entered = asyncio.Event()

    async def blocked(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    client.options.return_value = client
    client.search = AsyncMock(side_effect=blocked)
    client.close = AsyncMock()

    async def run():
        async with storage.AsyncResourceSearch("model", 2, 3, lambda: 1, client=client) as index:
            await index.search_chunk("tenant", [document()], [1., 0.], 1)

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.close.assert_awaited_once()
