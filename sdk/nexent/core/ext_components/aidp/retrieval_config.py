# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Flat persisted retrieval policy and the FusionSearch wire contract."""
from itertools import combinations


CHANNELS = ("vector_search", "full_text_search", "graph_search")
ALL_CHANNELS = "|".join(CHANNELS)
SEARCH_METHODS = frozenset((*CHANNELS, *("|".join(c) for c in combinations(CHANNELS, 2)), ALL_CHANNELS))
RERANK_MODES = frozenset({"performance", "high_accuracy", "jargon_coverage"})
DEFAULTS = {
    "search_method": ALL_CHANNELS, "top_k": 10, "score_threshold": 0.0,
    "reranking_enable": True, "reranking_mode": "performance", "rewrite_enable": False,
    "query_expansion_enable": False, "related_search_enable": False, "multi_modal": True,
    "vector_candidates": 10, "full_text_candidates": 10, "hybrid_top_k": 5,
    "graph_top_k": 5, "vector_score_threshold": 0.0, "full_text_score_threshold": 0.0,
    "graph_score_threshold": 0.0, "graph_reranking_enable": True,
    "ontology_enhance_enable": False, "rule_enable": False,
}
CONFIG_KEYS = frozenset(DEFAULTS)
INTEGER_RANGES = {"top_k": (1, 100), "vector_candidates": (1, 500),
                  "full_text_candidates": (1, 500), "hybrid_top_k": (1, 100), "graph_top_k": (1, 100)}
FIELD_CHANNELS = {
    "hybrid_top_k": ("vector_search", "full_text_search"),
    "graph_top_k": ("graph_search",),
    "vector_candidates": ("vector_search",),
    "full_text_candidates": ("full_text_search",),
    "vector_score_threshold": ("vector_search",),
    "full_text_score_threshold": ("full_text_search",),
    "graph_score_threshold": ("graph_search",),
    "graph_reranking_enable": ("graph_search",),
}


def _field_active(key, channels):
    owners = FIELD_CHANNELS.get(key)
    return owners is None or bool(set(owners) & channels)


def normalize_method(value):
    if value == "hybrid_search":
        return ALL_CHANNELS
    tokens = set(value.split("|"))
    return "|".join(c for c in CHANNELS if c in tokens)


def active_channels(method):
    return set(method.split("|"))


def merge_config(*layers):
    """Apply later fixed values; missing or null leaves the earlier value in place."""
    merged = {}
    for layer in layers:
        for key, value in layer.items():
            if key in CONFIG_KEYS and value is not None:
                merged[key] = value
    return merged


def resolve_config(config):
    """Fill defaults and normalize the method without validation side effects."""
    result = {**DEFAULTS, **merge_config(config)}
    result["search_method"] = normalize_method(result["search_method"])
    if not result["reranking_enable"]:
        result["graph_reranking_enable"] = False
    # Legacy zero caps mean "not set"; treat them as the default so old
    # instances flow through the omit-default-caps path without migration.
    if result["hybrid_top_k"] == 0:
        result["hybrid_top_k"] = DEFAULTS["hybrid_top_k"]
    if result["graph_top_k"] == 0:
        result["graph_top_k"] = DEFAULTS["graph_top_k"]
    return result


BOOLEAN_KEYS = frozenset({"reranking_enable", "rewrite_enable", "query_expansion_enable",
                          "related_search_enable", "multi_modal", "graph_reranking_enable",
                          "ontology_enhance_enable", "rule_enable"})
THRESHOLD_KEYS = frozenset({"score_threshold", "vector_score_threshold",
                            "full_text_score_threshold", "graph_score_threshold"})


def validate_config(config, inherited=None):
    """Check submitted fields before merging them with trusted persisted values."""
    merged = merge_config(inherited or {}, config)
    submitted_method = merged.get("search_method", DEFAULTS["search_method"])
    channels = active_channels(
        normalize_method(submitted_method)
        if isinstance(submitted_method, str)
        else DEFAULTS["search_method"]
    )
    hybrid = bool(channels & {"vector_search", "full_text_search"})
    graph = "graph_search" in channels
    for key, value in config.items():
        if value is None:
            raise ValueError(f"{key}: fixed value required")
        if key == "search_method":
            if not isinstance(value, str) or (
                value != "hybrid_search" and any(token not in CHANNELS for token in value.split("|"))
            ):
                raise ValueError("search_method: invalid retrieval method")
        elif key == "reranking_mode":
            if not isinstance(value, str) or value not in RERANK_MODES:
                raise ValueError("reranking_mode: invalid reranking strategy")
        elif key in BOOLEAN_KEYS:
            if not _field_active(key, channels):
                continue
            if not isinstance(value, bool):
                raise ValueError(f"{key}: expected boolean")
        elif key in INTEGER_RANGES:
            if not _field_active(key, channels):
                continue
            low, high = INTEGER_RANGES[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: expected integer {low}-{high}")
        elif key in THRESHOLD_KEYS:
            if not _field_active(key, channels):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{key}: expected finite number 0-1")
    if (
        graph
        and config.get("graph_reranking_enable") is True
        and merged.get("reranking_enable", DEFAULTS["reranking_enable"]) is False
    ):
        raise ValueError("graph_reranking_enable: requires reranking_enable")
    result = resolve_config(merged)
    if (
        result["ontology_enhance_enable"]
        and result["reranking_enable"]
        and result["reranking_mode"] == "jargon_coverage"
    ):
        raise ValueError(
            "ontology_enhance_enable: change reranking_mode before enabling entity enhancement"
        )
    h, g, k = result["hybrid_top_k"], result["graph_top_k"], result["top_k"]
    if hybrid and h > k:
        raise ValueError("hybrid_top_k: must not exceed top_k")
    if graph and g > k:
        raise ValueError("graph_top_k: must not exceed top_k")
    # Omitted caps are filled by AIDP (H = topk - G, G = 5), so the sum
    # is only enforced when at least one cap is explicitly customized.
    both_default = (h == DEFAULTS["hybrid_top_k"] and g == DEFAULTS["graph_top_k"])
    if not both_default and hybrid and graph and h + g > k:
        raise ValueError("hybrid_top_k + graph_top_k: must not exceed top_k")
    for channel, key in (("vector_search", "vector_candidates"), ("full_text_search", "full_text_candidates")):
        if channel in channels and h > result[key]:
            raise ValueError(f"{key}: must be at least hybrid_top_k")
    return result


def prepare_config(config, inherited):
    """Validate raw fields and return a normalized sparse override."""
    effective = validate_config(config, inherited)
    raw = merge_config(config)
    if "search_method" in raw:
        raw["search_method"] = effective["search_method"]
    if raw.get("reranking_enable") is False and "graph_reranking_enable" not in raw:
        raw["graph_reranking_enable"] = False
    return raw


def build_payload(config, query, kds_list, metadata_condition=None):
    if (
        config.get("ontology_enhance_enable") is True
        and config.get("reranking_enable") is True
        and config.get("reranking_mode") == "jargon_coverage"
    ):
        raise ValueError(
            "ontology_enhance_enable: change reranking_mode before enabling entity enhancement"
        )
    channels = active_channels(config["search_method"])
    payload = {key: config[key] for key in (
        "search_method", "score_threshold", "reranking_enable", "rewrite_enable",
        "query_expansion_enable", "related_search_enable")}
    payload.update(query=query, kds_list=kds_list, topk=config["top_k"], multi_modal_enable=config["multi_modal"])
    if config["reranking_enable"]:
        payload["reranking_mode"] = config["reranking_mode"]
    hybrid = {}
    # Omit caps at their default so AIDP fills in its own values.
    if config["hybrid_top_k"] != DEFAULTS["hybrid_top_k"]:
        hybrid["hybrid_top_k"] = config["hybrid_top_k"]
    for channel, prefix in (("vector_search", "vector"), ("full_text_search", "full_text")):
        if channel in channels:
            for suffix in ("candidates", "score_threshold"):
                key = f"{prefix}_{suffix}"
                hybrid[key] = config[key]
    if channels & {"vector_search", "full_text_search"}:
        payload["hybrid_search_config"] = hybrid
    if "graph_search" in channels:
        graph = {"graph_score_threshold": config["graph_score_threshold"],
                 "graph_reranking_enable": config["graph_reranking_enable"]}
        if config["graph_top_k"] != DEFAULTS["graph_top_k"]:
            graph["graph_top_k"] = config["graph_top_k"]
        payload["graph_search_config"] = graph
    if metadata_condition:
        payload["metadata_condition"] = metadata_condition
    if config.get("ontology_enhance_enable") is True:
        payload["ontology_enhance_enable"] = True
    if config.get("rule_enable") is True:
        payload["rule_enable"] = True
    return payload
