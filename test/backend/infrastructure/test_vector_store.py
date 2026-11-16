# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped vector protocol and provider write outcomes, without any model calls."""

from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    OutcomeUnknown,
    PartialFailure,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    Comparison,
    OperationContext,
    SearchQuery,
    StorageScope,
    VectorKey,
    VectorRecord,
    WriteOutcome,
)

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_store import ElasticsearchVectorStore, VectorBinding


def context():
    return OperationContext("vector-proof", monotonic() + 5)


@pytest.fixture
def store():
    client = Mock()
    client.options.return_value = client
    binding = VectorBinding(
        "kb",
        "proof-index",
        2,
        (
            FieldDefinition("content", "string"),
            FieldDefinition("file_id", "string"),
        ),
        writable=True,
    )
    factory = Mock(return_value=client)
    value = ElasticsearchVectorStore(
        StorageScope("runtime", "tenant-a", "user", {"kb"}), (binding,), factory
    )
    return value, client, factory


def vector(key="one", values=(1.0, 0.0)):
    return VectorRecord(
        VectorKey("kb", key), values, {"content": "hello", "file_id": "file"}
    )


def test_invalid_vector_batch_never_opens_provider(store):
    port, _, factory = store
    with pytest.raises(InvalidInput):
        port.upsert((vector(), vector("bad", (True, 0.0))), context=context())
    factory.assert_not_called()


def test_bulk_partial_failure_preserves_each_input_result(store):
    port, client, _ = store
    client.bulk.return_value = {
        "items": [
            {"index": {"status": 201}},
            {"index": {"status": 400, "error": {"reason": "private"}}},
        ]
    }
    with pytest.raises(PartialFailure) as error:
        port.upsert((vector(), vector("two")), context=context())
    assert [receipt.outcome for receipt in error.value.results] == [
        WriteOutcome.CONFIRMED,
        WriteOutcome.FAILED,
    ]
    assert "private" not in str(error.value)
    client.bulk.assert_called_once()
    client.close.assert_called_once()
    assert client.options.call_args.kwargs["max_retries"] == 0
    assert client.options.call_args.kwargs["retry_on_timeout"] is False


def test_dense_filter_is_tenant_scoped_and_hybrid_is_rejected(store):
    port, client, _ = store
    client.search.return_value = {"hits": {"hits": []}}
    assert (
        port.search(
            "kb",
            SearchQuery(vector=(1.0, 0.0), where=Comparison("file_id", "eq", "file")),
            context=context(),
        )
        == ()
    )
    query = client.search.call_args.kwargs["knn"]["filter"]
    assert query["bool"]["filter"][0] == {"term": {"_si_tenant": "tenant-a"}}
    assert "_si_collection" in client.search.call_args.kwargs["source"]
    with pytest.raises(CapabilityUnsupported):
        port.search(
            "kb",
            SearchQuery(vector=(1.0, 0.0), text="hello", mode="hybrid"),
            context=context(),
        )
    assert client.search.call_count == 1


def test_unknown_collection_never_opens_provider(store):
    port, _, factory = store
    with pytest.raises(ScopeDenied):
        port.count("other", None, context=context())
    factory.assert_not_called()


def test_readonly_binding_cannot_write_or_create_collection(store):
    from dataclasses import replace

    port, _, factory = store
    readonly = ElasticsearchVectorStore(
        port.scope, (replace(port._bindings["kb"], writable=False),), factory
    )
    for action in (
        lambda: readonly.upsert((vector(),), context=context()),
        lambda: readonly.ensure_collection("kb", context=context()),
        lambda: readonly.delete(
            "kb", Comparison("file_id", "eq", "file"), context=context()
        ),
    ):
        with pytest.raises(ScopeDenied):
            action()
    factory.assert_not_called()


def test_count_always_filters_tenant_and_collection(store):
    port, client, _ = store
    client.count.return_value = {"count": 2}
    assert port.count("kb", None, context=context()) == 2
    assert client.count.call_args.kwargs["query"] == {
        "bool": {
            "filter": [
                {"term": {"_si_tenant": "tenant-a"}},
                {"term": {"_si_collection": "kb"}},
            ]
        }
    }


def test_partial_delete_keeps_confirmed_page_when_next_page_is_unavailable(store):
    from elastic_transport import ConnectionError

    port, client, _ = store
    client.open_point_in_time.return_value = {"id": "snapshot"}
    client.search.side_effect = [
        {
            "hits": {
                "hits": [
                    {
                        "_id": port._key("kb", "one"),
                        "_seq_no": 4,
                        "_primary_term": 1,
                        "sort": [1],
                        "_source": {
                            "_si_tenant": "tenant-a",
                            "_si_collection": "kb",
                            "_si_key": "one",
                        },
                    }
                ]
            }
        },
        ConnectionError("controlled read failure"),
    ]
    client.bulk.return_value = {"items": [{"delete": {"status": 200}}]}
    with pytest.raises(PartialFailure) as error:
        port.delete("kb", Comparison("file_id", "eq", "file"), context=context())
    assert len(error.value.results) == 1 and error.value.results[0].deleted
    assert client.bulk.call_count == 1 and client.search.call_count == 2
    client.close_point_in_time.assert_called_once()


def test_partial_delete_numbers_failed_page_after_confirmed_items(store):
    port, client, _ = store
    client.open_point_in_time.return_value = {"id": "snapshot"}
    client.search.side_effect = [
        {
            "hits": {
                "hits": [
                    {
                        "_id": port._key("kb", key),
                        "_seq_no": 1,
                        "_primary_term": 1,
                        "sort": [index],
                        "_source": {
                            "_si_tenant": "tenant-a",
                            "_si_collection": "kb",
                            "_si_key": key,
                        },
                    }
                ]
            }
        }
        for index, key in enumerate(("one", "two"))
    ]
    client.bulk.side_effect = [
        {"items": [{"delete": {"status": status}}]} for status in (200, 409)
    ]
    ctx = context()
    with pytest.raises(PartialFailure) as error:
        port.delete("kb", Comparison("file_id", "eq", "file"), context=ctx)
    assert [row.operation_id for row in error.value.results] == [
        ctx.operation_id + ":0",
        ctx.operation_id + ":1",
    ]


def test_get_uses_a_tenant_specific_physical_identifier(store):
    port, client, _ = store
    client.get.return_value = {
        "_source": {
            "_si_tenant": "tenant-b",
            "_si_key": "one",
            "embedding": [1.0, 0.0],
            "payload": vector().payload,
        }
    }
    with pytest.raises(ScopeDenied):
        port.get(VectorKey("kb", "one"), context=context())
    assert client.get.call_args.kwargs["id"] != "one"
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "values", [(0.0, 0.0), (1.0,), (float("nan"), 0.0), (True, 0.0)]
)
def test_invalid_dimensions_or_values_rejected_before_io(store, values):
    port, _, factory = store
    with pytest.raises(InvalidInput):
        port.upsert((vector(values=values),), context=context())
    factory.assert_not_called()


def test_bulk_transport_failure_is_unknown_and_never_retried(store):
    from elastic_transport import ConnectionError

    port, client, _ = store
    client.bulk.side_effect = ConnectionError("private provider detail")
    with pytest.raises(OutcomeUnknown) as error:
        port.upsert((vector(),), context=context())
    assert "private" not in str(error.value)
    client.bulk.assert_called_once()
    client.close.assert_called_once()


def test_existing_collection_mismatch_is_not_recreated(store):
    port, client, _ = store
    binding = port._bindings["kb"]
    mapping = binding.mapping()
    mapping["properties"]["embedding"]["dims"] = 3
    client.indices.exists.return_value = True
    client.indices.get_mapping.return_value = {binding.index: {"mappings": mapping}}
    with pytest.raises(Conflict):
        port.ensure_collection("kb", context=context())
    client.indices.create.assert_not_called()


def test_collection_description_accepts_elasticsearch_implicit_object_type(store):
    port, client, _ = store
    binding = port._bindings["kb"]
    mapping = binding.mapping()
    mapping["properties"]["payload"].pop("type")
    client.indices.get_mapping.return_value = {binding.index: {"mappings": mapping}}
    assert port.describe_collection("kb", context=context()).dimensions == 2


def test_partial_shard_result_is_not_a_successful_search(store):
    port, client, _ = store
    client.search.return_value = {"_shards": {"failed": 1}, "hits": {"hits": []}}
    with pytest.raises(Unavailable):
        port.search("kb", SearchQuery(vector=(1.0, 0.0)), context=context())


def test_delete_preserves_conflict_and_closes_snapshot(store):
    port, client, _ = store
    client.open_point_in_time.return_value = {"id": "snapshot"}
    client.options.return_value = client
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": port._key("kb", "one"),
                    "_seq_no": 4,
                    "_primary_term": 1,
                    "sort": [1],
                    "_source": {
                        "_si_tenant": "tenant-a",
                        "_si_collection": "kb",
                        "_si_key": "one",
                    },
                }
            ]
        }
    }
    client.bulk.return_value = {"items": [{"delete": {"status": 409}}]}
    with pytest.raises(PartialFailure) as error:
        port.delete("kb", Comparison("file_id", "eq", "file"), context=context())
    assert error.value.results[0].outcome == WriteOutcome.FAILED
    assert error.value.results[0].deleted is False
    delete = client.bulk.call_args.kwargs["operations"][0]["delete"]
    assert delete["if_seq_no"] == 4 and delete["if_primary_term"] == 1
    client.close_point_in_time.assert_called_once_with(id="snapshot")
    client.close.assert_called_once()
