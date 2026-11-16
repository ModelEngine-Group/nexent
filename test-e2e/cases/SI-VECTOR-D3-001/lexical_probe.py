# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compare the old weighted algorithm and scoped VectorStore on the same real corpus."""

from dataclasses import replace

import pytest
from nexent.core.nlp.tokenizer import calculate_term_weights
from nexent.storage.models import (
    Revision,
    SearchQuery,
    StorageScope,
    VectorKey,
    VectorRecord,
)
from nexent.vector_database.utils import (
    HIGHLIGHT_POST_TAG,
    HIGHLIGHT_PRE_TAG,
    build_weighted_query,
    extract_highlight_terms,
)

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_store import ElasticsearchVectorStore, VectorBinding


def probe_lexical(client_factory, owned, context):
    fields = tuple(FieldDefinition(name, "string") for name in ("content", "title", "file_id"))
    binding = VectorBinding("lexical", "lexical-proof", 2, fields, writable=True, additional_text_fields=("title",))
    port = ElasticsearchVectorStore(StorageScope("runtime", "tenant-a", "proof", {"lexical"}), (binding,), client_factory)
    owned.append(port)
    port.ensure_collection("lexical", context=context())
    corpus = [
        ("a", "Router 404", "Check network routes and status report"),
        ("b", "Network handbook", "router error 404 requires route check"),
        ("c", "Manual", "unrelated database guide"),
    ]
    port.upsert(tuple(VectorRecord(VectorKey("lexical", key), (1.0, 0.0), {
        "content": text, "title": title, "file_id": key,
    }, Revision("current")) for key, title, text in corpus), context=context())
    for tenant, collection in (("tenant-b", "lexical"), ("tenant-a", "other")):
        outside = ElasticsearchVectorStore(StorageScope("runtime", tenant, "proof", {collection}),
                                            (replace(binding, collection=collection),), client_factory)
        owned.append(outside)
        outside.upsert((VectorRecord(VectorKey(collection, "outside"), (1.0, 0.0), {
            "content": "router error 404 manual", "title": "Router manual", "file_id": "outside",
        }, Revision("outside")),), context=context())
    for text in ("router 404", "manual"):
        hits = port.search("lexical", SearchQuery(mode="weighted_text", text=text), context=context())
        old = build_weighted_query(text, calculate_term_weights(text), {"payload.content": 1, "payload.title": 1})
        highlight = {"pre_tags": [HIGHLIGHT_PRE_TAG], "post_tags": [HIGHLIGHT_POST_TAG],
                     "fields": {"payload.content": {"fragment_size": 256, "number_of_fragments": 3},
                                "payload.title": {"number_of_fragments": 0}}}
        with client_factory(5) as client:
            reference = client.search(index=binding.index, size=10, query={"bool": {
                "must": [old["query"]], "filter": [{"term": {"_si_tenant": "tenant-a"}}, {"term": {"_si_collection": "lexical"}}],
            }}, highlight=highlight)["hits"]["hits"]
        assert [h.key.key for h in hits] == [h["_source"]["_si_key"] for h in reference]
        assert [h.score for h in hits] == pytest.approx([h["_score"] for h in reference])
        assert [list(h.highlights) for h in hits] == [extract_highlight_terms(h.get("highlight", {})) for h in reference]
        assert hits and all(h.highlights for h in hits)
        if text == "manual":
            assert [h.key.key for h in hits] == ["c"]
    return {"weighted_algorithm_equal": True, "title_fulltext": True,
            "plain_highlights_equal": True, "weighted_scope_isolated": True}
