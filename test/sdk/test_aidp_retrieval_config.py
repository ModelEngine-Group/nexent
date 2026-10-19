# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit policy boundaries; external protocol evidence lives in the formal Case."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from nexent.core.ext_components.aidp.retrieval_config import (
    CHANNELS, SEARCH_METHODS, active_channels, build_payload, merge_config, normalize_method, resolve_config,
)


@pytest.mark.parametrize("fixture", json.loads((Path(__file__).parents[1] / "fixtures/aidp_retrieval_config.json").read_text()))
def test_shared_frontend_python_policy_fixtures(fixture):
    resolved = resolve_config(fixture["config"])
    for key, value in fixture["expected"].items():
        assert resolved[key] == value, (fixture["name"], key)


@pytest.mark.parametrize("method", sorted(SEARCH_METHODS))
def test_complete_payload_filters_channels(method):
    payload = build_payload({"search_method": method, "top_k": 7, "multi_modal": False}, "query", ["kb"])
    assert payload["topk"] == 7
    assert payload["multi_modal_enable"] is False
    assert not {"top_k", "multi_modal", "candidate_topk", "metadata_condition", "file_reorder_enable"} & payload.keys()
    channels = active_channels(method)
    if channels & set(CHANNELS[:2]):
        hybrid = payload["hybrid_search_config"]
        assert hybrid["hybrid_top_k"] == 0
        for channel, prefix in zip(CHANNELS, ("vector", "full_text")):
            assert (f"{prefix}_candidates" in hybrid) == (channel in channels)
            if channel in channels:
                assert hybrid[f"{prefix}_candidates"] == 7
                assert hybrid[f"{prefix}_score_threshold"] == 0
    else:
        assert "hybrid_search_config" not in payload
    assert ("graph_search_config" in payload) == ("graph_search" in channels)
    if "graph_search" in channels:
        assert payload["graph_search_config"] == {"graph_top_k": 0, "graph_score_threshold": 0, "graph_reranking_enable": True}


def test_follow_explicit_override_and_no_input_mutation():
    base = {"top_k": 10, "vector_candidates": 30, "reranking_enable": False, "multi_modal": False}
    original = deepcopy(base)
    assert resolve_config(merge_config(base, {"top_k": 7}))["vector_candidates"] == 30
    merged = merge_config(base, {"top_k": 7, "vector_candidates": None, "multi_modal": None})
    assert resolve_config(merged)["vector_candidates"] == 7
    assert merged["vector_candidates"] is None
    assert resolve_config(merged)["full_text_candidates"] == 7
    assert resolve_config(merged)["graph_reranking_enable"] is False
    payload = build_payload(merged, "q", ["kb"])
    assert "reranking_mode" not in payload
    assert payload["multi_modal_enable"] is False
    assert base == original


@pytest.mark.parametrize("config,field", [
    ({"top_k":0},"top_k"), ({"top_k":True},"top_k"), ({"top_k":1.5},"top_k"),
    ({"vector_candidates":0},"vector_candidates"), ({"vector_candidates":501},"vector_candidates"),
    ({"full_text_candidates":"7"},"full_text_candidates"), ({"score_threshold":math.nan},"score_threshold"),
    ({"graph_score_threshold":math.inf},"graph_score_threshold"), ({"score_threshold":True},"score_threshold"),
    ({"reranking_enable":False,"graph_reranking_enable":True},"graph_reranking_enable"),
    ({"hybrid_top_k":8,"graph_top_k":5},"hybrid_top_k"),
    ({"hybrid_top_k":8,"graph_top_k":5,"graph_reranking_enable":False},"hybrid_top_k"),
    ({"hybrid_top_k":6,"full_text_candidates":5},"full_text_candidates"),
    ({"search_method":"graph_search","graph_top_k":11},"graph_top_k"),
    ({"search_method":"vector_search|"},"search_method"), ({"search_method":""},"search_method"),
    ({"search_method":"unknown"},"search_method"), ({"query_expansion_enable":1},"query_expansion_enable"),
])
def test_strict_validation(config, field):
    with pytest.raises(ValueError, match=field):
        resolve_config(config)


@pytest.mark.parametrize("k", [1,100])
def test_boundary_zero_caps_and_jargon(k):
    c = resolve_config({"top_k": k, "reranking_mode":"jargon_coverage", "vector_candidates":500, "full_text_candidates":1})
    assert c["top_k"] == k
    assert c["hybrid_top_k"] == c["graph_top_k"] == 0
    assert resolve_config({"hybrid_top_k":5,"graph_top_k":5})["top_k"] == 10


def test_method_normalization_and_inactive_quota():
    assert normalize_method("graph_search|vector_search|graph_search") == "vector_search|graph_search"
    assert normalize_method("graph_search|vector_search|full_text_search") == "hybrid_search"
    p = build_payload({"search_method":"graph_search","hybrid_top_k":100,"vector_candidates":1},"q",["kb"])
    assert "hybrid_search_config" not in p
