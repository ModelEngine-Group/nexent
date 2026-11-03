# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated source-schema rules before component normalization is connected."""

import pytest
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
)
from nexent.core.model_service.profiles._models_dev.validation import (
    validate_source_document,
)


def document(kind, data):
    return SourceDocument(
        kind, "lab/model", "models/lab/model.toml", "a" * 64, _freeze(data)
    )


@pytest.fixture
def hosted():
    return {
        "name": "Model",
        "description": "Description",
        "attachment": False,
        "reasoning": True,
        "tool_call": True,
        "release_date": "2024-02-29",
        "last_updated": "2026-10",
        "modalities": {"input": ["text"], "output": ["text"]},
        "open_weights": True,
        "limit": {"context": 200000, "output": 20000},
        "reasoning_options": [
            {"type": "toggle"},
            {"type": "budget_tokens", "max": 10000},
        ],
    }


def test_complete_hosted_definition_accepts_missing_budget_min_without_mutation(hosted):
    source = document("provider_model", hosted)
    validate_source_document(source, effective=True)
    assert "min" not in source.data["reasoning_options"][1]
    assert hosted["reasoning_options"] == [
        {"type": "toggle"},
        {"type": "budget_tokens", "max": 10000},
    ]


def test_raw_override_allows_partial_nested_objects_but_complete_result_does_not():
    source = document(
        "provider_model", {"base_model": "lab/base", "limit": {"output": 10}}
    )
    validate_source_document(source)
    with pytest.raises(SourceReadError) as error:
        validate_source_document(
            document("provider_model", {"limit": {"output": 10}}), effective=True
        )
    assert error.value.category == "SOURCE_FIELD_REQUIRED"
    assert error.value.source_path == "limit.context"


@pytest.mark.parametrize(
    "field,value,path",
    [
        ("reasoning", "true", "reasoning"),
        (
            "modalities",
            {"input": ["unknown"], "output": ["text"]},
            "modalities.input[0]",
        ),
        ("limit", {"context": True, "output": 10}, "limit.context"),
        ("limit", {"context": 1.5, "output": 10}, "limit.context"),
        ("limit", {"context": -1, "output": 10}, "limit.context"),
        (
            "reasoning_options",
            [{"type": "effort", "values": ["super"]}],
            "reasoning_options[0].values[0]",
        ),
        (
            "reasoning_options",
            [{"type": "budget_tokens", "min": -2}],
            "reasoning_options[0].min",
        ),
        (
            "reasoning_options",
            [{"type": "budget_tokens", "min": 20, "max": 10}],
            "reasoning_options[0].min",
        ),
        ("reasoning_options", [{"type": "invented"}], "reasoning_options[0].type"),
        ("reasoning_options", False, "reasoning_options"),
        ("interleaved", False, "interleaved"),
        ("limit", [], "limit"),
    ],
)
def test_invalid_values_report_exact_path_without_echoing_input(
    hosted, field, value, path
):
    hosted[field] = value
    with pytest.raises(SourceReadError) as error:
        validate_source_document(document("provider_model", hosted), effective=True)
    assert error.value.source_path == path
    assert error.value.rule_id == "models_dev_authored_v1"
    assert str(value) not in str(error.value)


@pytest.mark.parametrize(
    "update,path",
    [
        ({"reasoning_effort": "high"}, "reasoning_effort"),
        ({"limit": {"context": 100, "output": 10, "extra": 1}}, "limit.extra"),
        (
            {"reasoning_options": [{"type": "toggle", "default": True}]},
            "reasoning_options[0].default",
        ),
    ],
)
def test_unregistered_fields_are_not_aliases_or_silently_ignored(hosted, update, path):
    hosted.update(update)
    with pytest.raises(SourceReadError) as error:
        validate_source_document(document("provider_model", hosted))
    assert error.value.category == "SOURCE_FIELD_UNHANDLED"
    assert error.value.source_path == path


@pytest.mark.parametrize("reasoning,options", [(True, None), (False, [])])
def test_reasoning_options_follow_explicit_upstream_cross_field_contract(
    hosted, reasoning, options
):
    hosted["reasoning"] = reasoning
    if options is None:
        del hosted["reasoning_options"]
    else:
        hosted["reasoning_options"] = options
    with pytest.raises(SourceReadError) as error:
        validate_source_document(document("provider_model", hosted))
    assert error.value.source_path == "reasoning_options"
    assert error.value.category == "SOURCE_CONSTRAINT_INVALID"


def test_atomic_model_has_optional_capabilities_and_separate_schema():
    raw = {"name": "Model", "description": "Description"}
    validate_source_document(document("model", raw))
    raw["reasoning_options"] = []
    with pytest.raises(SourceReadError, match="SOURCE_FIELD_UNHANDLED"):
        validate_source_document(document("model", raw))


@pytest.mark.parametrize("kind,raw", [
    ("provider", {"name": "Provider", "env": [], "npm": "unknown", "api": "https://example.com"}),
    ("model", {"name": "Model", "family": "future-family", "release_date": "free-form", "links": [{"url": "free text", "new_field": True}], "benchmarks": [{"new_score": 5}]}),
])
def test_unused_reference_metadata_has_no_submission_schema(kind, raw):
    validate_source_document(document(kind, raw))


def test_atomic_reference_metadata_is_checked_without_becoming_runtime_capability():
    raw = {
        "name": "Model",
        "description": "Description",
        "family": "qwen",
        "links": [{"url": "https://example.com/docs", "type": "docs"}],
        "weights": [{"url": "https://example.com/weights"}],
        "benchmarks": [{"name": "Test", "score": 99.5, "date": "2024-02"}],
    }
    validate_source_document(document("model", raw))
    raw["benchmarks"][0]["score"] = "pass"
    validate_source_document(document("model", raw))
    assert "reasoning" not in raw


def test_explicit_interleaved_and_effort_values_are_schema_checked(hosted):
    hosted["interleaved"] = {"field": "reasoning_content"}
    hosted["reasoning_options"] = [
        {"type": "effort", "values": ["none", "default", "null"]}
    ]
    hosted["cost"] = {"input": 0.1, "output": 0.2}
    validate_source_document(document("provider_model", hosted))
    hosted["interleaved"] = True
    validate_source_document(document("provider_model", hosted))
    hosted["reasoning_options"] = [{"type": "effort"}]
    with pytest.raises(SourceReadError) as error:
        validate_source_document(document("provider_model", hosted))
    assert error.value.source_path == "reasoning_options[0].values"
