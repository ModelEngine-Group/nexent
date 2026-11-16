# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime keeps lexical evidence and score components through fusion and rerank."""

from dataclasses import replace

import pytest
from nexent.storage.models import Revision, SearchHit, VectorKey
from runtime.knowledge_base.search import KnowledgeSearchService, rank_candidates


def test_hybrid_merges_highlights_and_scores_only_within_the_same_generation():
    lexical = SearchHit(VectorKey("kb", "one"), 4, "text", {}, Revision("current"), highlights=("router",))
    semantic = replace(lexical, score=0.8, score_kind="dense", highlights=())
    result = rank_candidates([lexical], [semantic], "hybrid", "router")[0]
    assert result.score == pytest.approx(1)
    assert result.highlights == ("router",)
    assert result.scores == {"accurate": 1.0, "semantic": 1.0}
    reranked = KnowledgeSearchService._reranked([{"index": 0, "relevance_score": 0.9}], [result])[0]
    assert reranked.highlights == ("router",) and reranked.scores == result.scores
    assert len(rank_candidates([lexical], [replace(semantic, generation=Revision("new"))], "hybrid", "router")) == 2


def test_agentos_dto_carries_existing_consumer_score_details_without_changing_text():
    payload = {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 0, "content": "router content", "filename": "file.txt"}
    hit = SearchHit(VectorKey("kb", "one"), 0.8, "runtime.hybrid", payload,
                    highlights=("router",), scores={"accurate": 0.3, "semantic": 1.0})
    dto = KnowledgeSearchService._dto(hit)
    assert dto.content == "router content"
    assert dto.score_details == {"accurate": 0.3, "semantic": 1.0, "retrieval_highlight_terms": ["router"]}
