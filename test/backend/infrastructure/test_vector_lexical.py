# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Weighted lexical requests preserve old query semantics inside scoped VectorStore."""

from dataclasses import replace

import pytest
from nexent.storage.errors import InvalidInput
from nexent.storage.models import Comparison, SearchQuery
from nexent.vector_database.utils import build_weighted_query

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_store import context
from test.backend.infrastructure.test_vector_store import (
    store as store,  # noqa: PLC0414 - Reuse the protocol fixture.
)


def test_weighted_query_matches_legacy_and_keeps_scope_and_plain_highlights(store, mocker):
    original, client, factory = store
    binding = replace(original._bindings["kb"], fields=(*original._bindings["kb"].fields, FieldDefinition("title", "string")),
                      additional_text_fields=("title",))
    port = ElasticsearchVectorStore(original.scope, (binding,), factory)
    mocker.patch("infrastructure.vdb.lexical.calculate_term_weights", return_value={"router": 1.0})
    client.search.return_value = {"hits": {"hits": [{
        "_score": 3.0, "_source": {"_si_tenant": "tenant-a", "_si_collection": "kb", "_si_key": "one",
        "payload": {"content": "router error", "file_id": "file", "title": "router"}},
        "highlight": {"payload.content": ["__nexent_hit_start__router__nexent_hit_end__ error"]},
    }]}}
    hits = port.search("kb", SearchQuery(mode="weighted_text", text="router", where=Comparison("file_id", "eq", "file")), context=context())
    query = client.search.call_args.kwargs["query"]
    assert query["bool"]["must"] == [build_weighted_query("router", {"router": 1.0}, {"payload.content": 1, "payload.title": 1})["query"]]
    assert query["bool"]["filter"][0]["bool"]["filter"][:2] == [
        {"term": {"_si_tenant": "tenant-a"}}, {"term": {"_si_collection": "kb"}},
    ]
    assert hits[0].highlights == ("router",) and hits[0].payload["content"] == "router error"
    assert hits[0].score_kind == "elasticsearch.weighted_text"
    assert set(client.search.call_args.kwargs["highlight"]["fields"]) == {"payload.content", "payload.title"}
    client.search.assert_called_once()
    client.close.assert_called_once()
    port.capabilities.require("vector.search.weighted_text")
    assert binding.mapping()["properties"]["payload"]["properties"]["title"]["type"] == "text"


@pytest.mark.parametrize("fields", [("unknown",), ("content",), ("file_id", "file_id")])
def test_invalid_fulltext_declaration_is_refused(store, fields):
    port, _, factory = store
    with pytest.raises(InvalidInput):
        replace(port._bindings["kb"], additional_text_fields=fields)
    factory.assert_not_called()
