# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Flat persisted retrieval policy and the FusionSearch wire contract."""
import math
from itertools import combinations

from pydantic.fields import FieldInfo


CHANNELS = ("vector_search", "full_text_search", "graph_search")
SEARCH_METHODS = frozenset((*CHANNELS, "hybrid_search", *("|".join(c) for c in combinations(CHANNELS, 2))))
RERANK_MODES = frozenset({"performance", "high_accuracy", "jargon_coverage"})
CANDIDATES = frozenset({"vector_candidates", "full_text_candidates"})
DEFAULTS = {
    "search_method": "hybrid_search", "top_k": 10, "score_threshold": 0.0,
    "reranking_enable": True, "reranking_mode": "performance", "rewrite_enable": False,
    "query_expansion_enable": False, "related_search_enable": False, "multi_modal": True,
    "vector_candidates": None, "full_text_candidates": None, "hybrid_top_k": 0,
    "graph_top_k": 0, "vector_score_threshold": 0.0, "full_text_score_threshold": 0.0,
    "graph_score_threshold": 0.0, "graph_reranking_enable": None,
}
CONFIG_KEYS = frozenset(DEFAULTS)
INTEGER_RANGES = {"top_k": (1, 100), "vector_candidates": (1, 500),
                  "full_text_candidates": (1, 500), "hybrid_top_k": (0, 100), "graph_top_k": (0, 100)}


def normalize_method(value):
    if value == "hybrid_search":
        return value
    if not isinstance(value, str) or any(token not in CHANNELS for token in value.split("|")):
        raise ValueError("search_method: invalid retrieval method")
    tokens = set(value.split("|"))
    return "hybrid_search" if len(tokens) == 3 else "|".join(c for c in CHANNELS if c in tokens)


def active_channels(method):
    method = normalize_method(method)
    return set(CHANNELS if method == "hybrid_search" else method.split("|"))


def merge_config(*layers):
    """Ordinary null inherits; candidate null explicitly clears an inherited integer."""
    merged = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if key in CONFIG_KEYS and (value is not None or key in CANDIDATES):
                merged[key] = value
    return merged


def resolve_config(config=None):
    """Resolve a fresh copy at every runtime boundary; never materialize persisted following."""
    raw = {}
    for key, value in (config or {}).items():
        if key in CONFIG_KEYS:
            raw[key] = value.default if isinstance(value, FieldInfo) else value
    result = {key: raw.get(key) if raw.get(key) is not None else default for key, default in DEFAULTS.items()}
    result["search_method"] = normalize_method(result["search_method"])
    if not isinstance(result["reranking_mode"], str) or result["reranking_mode"] not in RERANK_MODES:
        raise ValueError("reranking_mode: invalid reranking strategy")
    for key, default in DEFAULTS.items():
        value = result[key]
        if key in CANDIDATES and value is None:
            continue
        if key == "graph_reranking_enable" and value is None:
            result[key] = result["reranking_enable"]
            value = result[key]
        if isinstance(default, bool) or key == "graph_reranking_enable":
            if not isinstance(value, bool):
                raise ValueError(f"{key}: expected boolean")
        elif key in INTEGER_RANGES:
            low, high = INTEGER_RANGES[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: expected integer {low}-{high}")
        elif key.endswith("score_threshold"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{key}: expected finite number 0-1")
    for key in CANDIDATES:
        if result[key] is None:
            result[key] = result["top_k"]
    if result["graph_reranking_enable"] and not result["reranking_enable"]:
        raise ValueError("graph_reranking_enable: requires reranking_enable")
    channels = active_channels(result["search_method"])
    hybrid = bool(channels & {"vector_search", "full_text_search"})
    graph = "graph_search" in channels
    h, g, k = result["hybrid_top_k"], result["graph_top_k"], result["top_k"]
    if hybrid and h > k:
        raise ValueError("hybrid_top_k: must not exceed top_k")
    if graph and g > k:
        raise ValueError("graph_top_k: must not exceed top_k")
    if hybrid and graph and h > 0 and g > 0 and h + g > k:
        raise ValueError("hybrid_top_k + graph_top_k: must not exceed top_k")
    for channel, key in (("vector_search", "vector_candidates"), ("full_text_search", "full_text_candidates")):
        if channel in channels and h > result[key]:
            raise ValueError(f"{key}: must be at least hybrid_top_k")
    return result


def build_payload(config, query, kds_list):
    config = resolve_config(config)
    channels = active_channels(config["search_method"])
    payload = {key: config[key] for key in (
        "search_method", "score_threshold", "reranking_enable", "rewrite_enable",
        "query_expansion_enable", "related_search_enable")}
    payload.update(query=query, kds_list=kds_list, topk=config["top_k"], multi_modal_enable=config["multi_modal"])
    if config["reranking_enable"]:
        payload["reranking_mode"] = config["reranking_mode"]
    hybrid = {"hybrid_top_k": config["hybrid_top_k"]}
    for channel, prefix in (("vector_search", "vector"), ("full_text_search", "full_text")):
        if channel in channels:
            for suffix in ("candidates", "score_threshold"):
                key = f"{prefix}_{suffix}"
                hybrid[key] = config[key]
    if len(hybrid) > 1:
        payload["hybrid_search_config"] = hybrid
    if "graph_search" in channels:
        payload["graph_search_config"] = {key: config[key] for key in (
            "graph_top_k", "graph_score_threshold", "graph_reranking_enable")}
    return payload
