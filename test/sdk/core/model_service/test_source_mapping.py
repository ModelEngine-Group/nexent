"""Versioned source dispositions without API bindings or catalog execution."""

from pathlib import Path

import pytest
from nexent.core.model_service.profiles._models_dev.inheritance import (
    resolve_source_model,
)
from nexent.core.model_service.profiles._models_dev.mapping import (
    load_mapping_rules,
    map_source_fields,
)
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
)

RULE_PATH = (
    Path(__file__).parents[4]
    / "sdk/nexent/core/model_service/profiles/rules/mappings/models_dev/v1.toml"
)


def doc(kind, key, data):
    return SourceDocument(kind, key, f"{kind}/{key}.toml", "a" * 64, _freeze(data))


def test_mapping_keeps_unknown_false_and_zero_separate_and_records_rule_origin():
    source = doc(
        "model",
        "lab/model",
        {"name": "Model", "reasoning": False, "limit": {"context": 0, "output": 10}},
    )
    result = map_source_fields(source, load_mapping_rules(RULE_PATH))
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
        resolve_source_model(hosted, (base, hosted)), load_mapping_rules(RULE_PATH)
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
    result = map_source_fields(source, load_mapping_rules(RULE_PATH))
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
    result = map_source_fields(source, load_mapping_rules(RULE_PATH))
    assert result.values["/connection_suggestions/base_url"] == "https://example.com"
    assert result.values["/reference_metadata/env/0"] == "PRIVATE_API_KEY"
    assert not any("protocol" in key or "credential" in key for key in result.values)


@pytest.mark.parametrize(
    "data,category,path",
    [
        ({"reasoning_effort": "high"}, "SOURCE_FIELD_UNHANDLED", "reasoning_effort"),
        ({"reasoning": "true"}, "SOURCE_VALUE_INVALID", "reasoning"),
    ],
)
def test_mapping_rejects_unregistered_aliases_and_wrong_types(data, category, path):
    with pytest.raises(SourceReadError) as error:
        map_source_fields(
            doc("model", "lab/model", data), load_mapping_rules(RULE_PATH)
        )
    assert error.value.category == category
    assert error.value.source_path == path


@pytest.mark.parametrize(
    "replacement", ["mapping_version = true", "mapping_version = 2"]
)
def test_registry_version_is_strict_and_explicit(tmp_path, replacement):
    path = tmp_path / "mapping.toml"
    path.write_text(RULE_PATH.read_text().replace("mapping_version = 1", replacement))
    with pytest.raises(SourceReadError, match="SOURCE_MAPPING_INVALID"):
        load_mapping_rules(path)


@pytest.mark.parametrize(
    "before,after,category",
    [
        (
            'rule_id = "model.name"',
            'rule_id = "model.description"',
            "SOURCE_MAPPING_DUPLICATE",
        ),
        (
            'source_path = "name"',
            'source_path = "description"',
            "SOURCE_MAPPING_DUPLICATE",
        ),
        (
            'transform_ref = "identity_v1"',
            'transform_ref = "guess_v1"',
            "SOURCE_MAPPING_INVALID",
        ),
        ('source_path = "name"', 'source_path = "*"', "SOURCE_MAPPING_INVALID"),
        (
            'target_path = "/identity/name"',
            'target_path = "name"',
            "SOURCE_MAPPING_INVALID",
        ),
        ('source_type = "string"', 'source_type = "boolean"', "SOURCE_MAPPING_INVALID"),
    ],
)
def test_invalid_registry_rules_fail_explicitly(tmp_path, before, after, category):
    path = tmp_path / "mapping.toml"
    # The final variant makes the identity transform legal, so test its effect below.
    if before == 'source_type = "string"':
        before = 'source_type = "boolean"\ntarget_path = "/reasoning/status"'
        after = 'source_type = "string"\ntarget_path = "/reasoning/status"'
    path.write_text(RULE_PATH.read_text().replace(before, after, 1))
    with pytest.raises(SourceReadError, match=category):
        load_mapping_rules(path)


def test_registry_rejects_conflicting_target_ownership(tmp_path):
    path = tmp_path / "mapping.toml"
    path.write_text(
        RULE_PATH.read_text().replace(
            'target_path = "/identity/name"', 'target_path = "/identity/description"', 1
        )
    )
    with pytest.raises(SourceReadError, match="SOURCE_TARGET_CONFLICT"):
        load_mapping_rules(path)


def test_registry_rejects_policy_inconsistent_with_registered_transform(tmp_path):
    path = tmp_path / "mapping.toml"
    path.write_text(
        RULE_PATH.read_text().replace(
            'special_value_policy = "strict_boolean"',
            'special_value_policy = "preserve"',
            1,
        )
    )
    with pytest.raises(SourceReadError, match="SOURCE_MAPPING_INVALID"):
        load_mapping_rules(path)


def test_empty_reference_arrays_and_text_benchmark_scores_remain_reference_data():
    source = doc(
        "model",
        "lab/model",
        {"links": [], "benchmarks": [{"name": "Score", "score": "pass"}]},
    )
    result = map_source_fields(source, load_mapping_rules(RULE_PATH))
    assert result.values["/reference_metadata/links"] == ()
    assert result.values["/reference_metadata/benchmarks/0/score"] == "pass"
    assert result.values["/reasoning/status"] == "unknown"


def test_scalar_target_cannot_own_a_descendant_field(tmp_path):
    path = tmp_path / "mapping.toml"
    path.write_text(
        RULE_PATH.read_text().replace(
            'target_path = "/identity/name"', 'target_path = "/identity"', 1
        )
    )
    with pytest.raises(SourceReadError, match="SOURCE_TARGET_CONFLICT"):
        load_mapping_rules(path)


def test_missing_rule_file_is_an_explicit_mapping_error(tmp_path):
    with pytest.raises(SourceReadError, match="SOURCE_MAPPING_INVALID"):
        load_mapping_rules(tmp_path / "missing.toml")
