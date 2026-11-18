# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Payload maintenance never depends on model dimensions or creates a collection."""

from dataclasses import replace

import pytest
from nexent.storage.errors import CapabilityUnsupported
from nexent.storage.models import Comparison, PageRequest, SearchQuery, VectorKey

from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_store import context, vector
from test.backend.infrastructure.test_vector_store import (
    store as store,  # noqa: PLC0414 - Reuse the protocol fixture.
)


@pytest.fixture
def maintenance(store):
    port, client, factory = store
    binding = replace(port._bindings["kb"], dimensions=None)
    return ElasticsearchVectorStore(port.scope, (binding,), factory), client, factory, binding


@pytest.mark.parametrize("operation", [
    lambda p: p.ensure_collection("kb", context=context()),
    lambda p: p.describe_collection("kb", context=context()),
    lambda p: p.get(VectorKey("kb", "one"), context=context()),
    lambda p: p.upsert((vector(),), context=context()),
    lambda p: p.search("kb", SearchQuery(text="hello"), context=context()),
    lambda p: p.scan("kb", None, PageRequest(), context=context()),
])
def test_dimensionless_binding_rejects_vector_operations_before_transport(maintenance, operation):
    port, _, factory, _ = maintenance
    with pytest.raises(CapabilityUnsupported):
        operation(port)
    factory.assert_not_called()
    assert port.capabilities.supported == {
        "vector.count", "vector.delete", "vector.collection.exists", "vector.scan.payload",
    }


def test_dimensionless_binding_counts_and_deletes_with_the_same_scope(maintenance):
    port, client, _, binding = maintenance
    client.count.return_value = {"count": 0}
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.return_value = {"hits": {"hits": []}}
    where = Comparison("file_id", "eq", "file")
    assert port.count("kb", where, context=context()) == 0
    assert port.delete("kb", where, context=context()) == ()
    query = client.count.call_args.kwargs["query"]
    assert query["bool"]["filter"][:2] == [
        {"term": {"_si_tenant": "tenant-a"}}, {"term": {"_si_collection": "kb"}},
    ]
    assert client.search.call_args.kwargs["query"] == query
    client.indices.create.assert_not_called()
    with pytest.raises(CapabilityUnsupported):
        binding.mapping()
