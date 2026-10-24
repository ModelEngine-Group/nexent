# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Versioned source dispositions without API bindings or catalog execution."""

import pytest
from nexent.core.model_service.profiles._models_dev.inheritance import (
    resolve_source_model,
)
from nexent.core.model_service.profiles._models_dev.mapping import (
    SOURCE_MAPPING,
    mapping_fingerprint,
    map_source_fields,
)
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
)



def doc(kind, key, data):
    return SourceDocument(kind, key, f"{kind}/{key}.toml", "a" * 64, _freeze(data))


def test_mapping_keeps_unknown_false_and_zero_separate_and_records_rule_origin():
    source = doc(
        "model",
        "lab/model",
        {"name": "Model", "reasoning": False, "limit": {"context": 0, "output": 10}},
    )
    result = map_source_fields(source, SOURCE_MAPPING)
    assert result.values["/reasoning/status"] == "unsupported"
    assert result.values["/tools/status"] == "unknown"
    assert result.values["/context/combined_window"] is None
    assert result.values["/context/input_limit"] is None
    assert result.values["/context/output_limit"] == 10
    origin = result.field_origins["/context/combined_window"]
    assert origin.rule_id == "model.limit.context"
    assert origin.rule_version == 1
    assert origin.source.source_path == "limit.context"
    assert "/tools/status" not in result.field_origins
    assert source.data["limit"]["context"] == 0
    with pytest.raises(TypeError):
        result.values["/reasoning/status"] = "supported"


def test_inherited_field_ownership_is_preserved_through_mapping():
    base = doc("model", "lab/model", {"tool_call": True, "limit": {"context": 100}})
    hosted = doc(
        "provider_model",
        "vendor/model",
        {"base_model": base.key, "limit": {"output": 10}},
    )
    result = map_source_fields(
        resolve_source_model(hosted, (base, hosted)), SOURCE_MAPPING
    )
    assert result.field_origins["/tools/status"].source.file_path == base.file_path
    assert (
        result.field_origins["/context/output_limit"].source.file_path
        == hosted.file_path
    )
    assert result.field_origins["/tools/status"].rule_id == "provider_model.tool_call"


def test_array_reference_fields_and_control_candidates_preserve_exact_values():
    source = doc(
        "provider_model",
        "vendor/model",
        {
            "reasoning_options": [
                {"type": "effort", "values": ["none", "null"]},
                {"type": "budget_tokens", "min": -1},
            ],
            "cost": {"input": 0.1, "output": 0.2},
            "modalities": {"input": ["text", "image"], "output": []},
        },
    )
    result = map_source_fields(source, SOURCE_MAPPING)
    assert result.values["/reasoning/control_candidates/0/values/0"] == "none"
    assert result.values["/reasoning/control_candidates/0/values/1"] == "null"
    assert result.values["/reasoning/control_candidates/1/min"] == -1
    assert result.values["/reference_metadata/cost/input"] == 0.1
    assert result.values["/modalities/output"] == ()
    assert not any("api" in key or "body" in key for key in result.values)


def test_provider_metadata_remains_a_suggestion_without_api_selection():
    source = doc(
        "provider",
        "vendor",
        {"api": "https://example.com", "env": ["PRIVATE_API_KEY"], "npm": "sdk"},
    )
    result = map_source_fields(source, SOURCE_MAPPING)
    assert result.values["/connection_suggestions/base_url"] == "https://example.com"
    assert result.values["/reference_metadata/env/0"] == "PRIVATE_API_KEY"
    assert not any("protocol" in key or "credential" in key for key in result.values)


def test_empty_reference_arrays_and_text_benchmark_scores_remain_reference_data():
    source = doc(
        "model",
        "lab/model",
        {"links": [], "benchmarks": [{"name": "Score", "score": "pass"}]},
    )
    result = map_source_fields(source, SOURCE_MAPPING)
    assert result.values["/reference_metadata/links"] == ()
    assert result.values["/reference_metadata/benchmarks/0/score"] == "pass"
    assert result.values["/reasoning/status"] == "unknown"



def test_policy_fingerprint_is_deterministic_and_versioned():
    from dataclasses import replace
    assert mapping_fingerprint(SOURCE_MAPPING) == mapping_fingerprint(SOURCE_MAPPING)
    assert mapping_fingerprint(replace(SOURCE_MAPPING, mapping_version=2)) != mapping_fingerprint(SOURCE_MAPPING)


def test_unconsumed_fields_are_isolated_reference_data():
    result = map_source_fields(doc("model", "lab/model", {"benchmarks": [{"new_field": "value"}]}))
    assert result.values["/reference_metadata/benchmarks/0/new_field"] == "value"
    assert result.values["/reasoning/status"] == "unknown"
