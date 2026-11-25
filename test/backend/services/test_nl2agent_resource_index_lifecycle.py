# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resource-index client configuration, complete snapshots and maintenance failures."""

import asyncio
from unittest.mock import MagicMock

import pytest
from elasticsearch import BadRequestError, NotFoundError

from management.services.conversation import nl2agent_resource_index as storage


@pytest.mark.parametrize("factory,constructor", [("create_client", "Elasticsearch"),
                                                 ("create_async_client", "AsyncElasticsearch")])
def test_client_factory_requires_host_and_disables_hidden_retries(mocker, factory, constructor):
    client = mocker.patch.object(storage, constructor)
    mocker.patch.object(storage, "ES_HOST", "")
    with pytest.raises(ValueError, match="not configured"):
        getattr(storage, factory)()
    client.assert_not_called()
    mocker.patch.object(storage, "ES_HOST", "http://es.invalid")
    mocker.patch.object(storage, "ES_API_KEY", "")
    assert getattr(storage, factory)() is client.return_value
    assert client.call_args.args == ("http://es.invalid",)
    assert client.call_args.kwargs["api_key"] is None
    assert client.call_args.kwargs["max_retries"] == 0
    assert client.call_args.kwargs["retry_on_timeout"] is False


@pytest.fixture
def index():
    client = MagicMock()
    client.options.return_value = client
    return storage.ResourceIndex("model", 2, 3, lambda: 2.0, client=client), client


def test_non_collision_mapping_error_closes_client_without_waiting(index):
    store, client = index
    client.indices.create.side_effect = BadRequestError("mapping_error", MagicMock(), {})
    with pytest.raises(BadRequestError):
        store.__enter__()
    client.close.assert_called_once()
    client.cluster.health.assert_not_called()


def test_snapshots_chunk_full_results_and_do_not_read_empty_scope(mocker, index):
    store, client = index
    mocker.patch.object(storage, "FILTER_BATCH_SIZE", 1)
    client.mget.side_effect = [{"docs": [{"found": False}]}, {"docs": [{"found": True, "_seq_no": 3}]}]
    assert store.snapshots("tenant", []) == {}
    client.mget.assert_not_called()
    assert store.snapshots("tenant", [{"candidate_ref": "tool:1"}, {"candidate_ref": "skill:2"}]) == {
        "tool:1": {"found": False}, "skill:2": {"found": True, "_seq_no": 3},
    }
    assert client.mget.call_count == 2
    assert client.mget.call_args.kwargs["ids"] == [storage.document_id("tenant", "skill:2")]


def test_snapshot_item_errors_are_rejected_even_if_count_matches(index):
    store, client = index
    client.mget.return_value = {"docs": [{"error": "shard unavailable"}]}
    with pytest.raises(ValueError, match="Incomplete"):
        store.snapshots("tenant", [{"candidate_ref": "tool:1"}])


@pytest.mark.parametrize("failed", [0, 1])
def test_refresh_requires_all_shards_to_succeed(index, failed):
    store, client = index
    client.indices.refresh.return_value = {"_shards": {"failed": failed}}
    if failed:
        with pytest.raises(ValueError, match="refresh failed"):
            store.refresh()
    else:
        store.refresh()
    client.indices.refresh.assert_called_once_with(index=store.name)


@pytest.mark.parametrize("missing", [False, True])
def test_delete_is_idempotent_and_scoped_to_single_document(index, missing):
    store, client = index
    if missing:
        client.delete.side_effect = NotFoundError("missing", MagicMock(), {})
    store.delete("tenant", "tool:1")
    client.delete.assert_called_once_with(index=store.name, id=storage.document_id("tenant", "tool:1"), refresh="wait_for")


@pytest.mark.asyncio
async def test_cancel_during_close_waits_for_transport_cleanup():
    entered, release = asyncio.Event(), asyncio.Event()

    async def close():
        entered.set()
        await release.wait()

    client = MagicMock()
    client.close = close
    store = storage.AsyncResourceSearch("model", 2, 3, lambda: 1, client=client)
    task = asyncio.create_task(store.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
