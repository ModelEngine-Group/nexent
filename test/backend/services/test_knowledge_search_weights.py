# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-HYBRID-WEIGHT-01/02/03 preserve caller and tool ranking policies."""

from dataclasses import replace

import pytest
from contracts.agentos_knowledge import KnowledgeSearch
from nexent.storage.models import Revision, SearchHit, VectorKey
from pydantic import ValidationError
from runtime.knowledge_base.search import rank_candidates

from test.backend.services.test_knowledge_search import (
    search as search,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_worker import (
    setup as setup,  # noqa: PLC0414
)


@pytest.mark.parametrize("weight", [None, 0, 0.5, 0.7, 1])
def test_internal_search_contract_preserves_explicit_fusion_weight(weight):
    request = KnowledgeSearch(knowledge_ids=[1], query="query", embedding_model={"model_id": 2, "revision": "v1"},
                              weight_accurate=weight)
    assert request.weight_accurate == weight
    assert KnowledgeSearch.model_validate_json(request.model_dump_json()).weight_accurate == weight


@pytest.mark.parametrize("weight", [-0.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_internal_search_contract_rejects_invalid_fusion_weight(weight):
    with pytest.raises(ValidationError):
        KnowledgeSearch(knowledge_ids=[1], query="query", embedding_model={"model_id": 2, "revision": "v1"},
                        weight_accurate=weight)


@pytest.mark.parametrize("query,weight", [("ordinary", 0), ("error 404", 0), ("ordinary", 0.5),
                                         ("error 404", 0.5), ("ordinary", 1), ("error 404", 1)])
def test_explicit_weight_overrides_digit_policy_and_keeps_branch_details(query, weight):
    lexical = SearchHit(VectorKey("a", "same"), 10, "text", {"content": "lexical"}, Revision("v1"),
                        highlights=("matched",))
    semantic = SearchHit(VectorKey("b", "same"), 0.5, "dense", {"content": "semantic"}, Revision("v1"))
    rows = rank_candidates([lexical], [semantic], "hybrid", query, weight_accurate=weight)
    assert len(rows) == 2
    by_collection = {row.key.collection: row for row in rows}
    assert by_collection["a"].score == weight and by_collection["b"].score == 1 - weight
    assert by_collection["a"].scores == {"accurate": 1, "semantic": 0}
    assert by_collection["a"].highlights == ("matched",)
    assert rows[0].key.collection == ("b" if weight == 0 else "a")


@pytest.mark.parametrize("mode", ["accurate", "semantic"])
def test_single_branch_modes_keep_native_scores(mode):
    row = SearchHit(VectorKey("a", "same"), 10, "native", {"content": "text"}, Revision("v1"))
    assert rank_candidates([row], [row], mode, "query 404", weight_accurate=0.5) == [row]


@pytest.mark.parametrize("weight,winner", [(0, "two"), (1, "one")])
async def test_actual_search_service_uses_explicit_weight_without_extra_inference(search, weight, winner):
    s, request, _, hit, service = search
    lexical = replace(hit, score=10)
    semantic = replace(hit, key=VectorKey("kb", "two"), score=0.5, payload={**hit.payload, "content": "other"})
    s.vectors.search.side_effect = [(lexical,), (semantic,)]
    request = KnowledgeSearch.model_validate({**request.model_dump(), "search_mode": "hybrid", "weight_accurate": weight})
    result = await service.search(request, s.actor)
    assert result.hits[0].chunk_id == winner
    assert s.models.invoke.await_count == 1 and s.vectors.search.call_count == 2
    assert s.client.authorize_knowledge_search.await_count == 2
