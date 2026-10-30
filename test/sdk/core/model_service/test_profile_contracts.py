# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-01/02: strict profile primitives, without provider or database I/O."""

import pytest
from nexent.core.model_service.profiles.contracts import (
    AtomicProfileReference,
    BudgetTokensControl,
    ContextCapabilities,
    EffortControl,
    ReasoningCapabilities,
    ToggleControl,
)
from pydantic import ValidationError


def test_context_unknown_and_independent_limits():
    assert ContextCapabilities().model_dump() == {
        "combined_window": None,
        "input_limit": None,
        "output_limit": None,
    }
    profile = ContextCapabilities(
        combined_window=100, input_limit=100, output_limit=100
    )
    assert ContextCapabilities.model_validate_json(profile.model_dump_json()) == profile
    assert ContextCapabilities(output_limit=1).combined_window is None


@pytest.mark.parametrize("value", [True, False, "200000", 1.0, 0, -1])
@pytest.mark.parametrize("field", ["combined_window", "input_limit", "output_limit"])
def test_context_rejects_invalid_token_limits(field, value):
    with pytest.raises(ValidationError):
        ContextCapabilities(**{field: value})


@pytest.mark.parametrize("field", ["input_limit", "output_limit"])
def test_context_rejects_service_limit_above_window(field):
    with pytest.raises(ValidationError):
        ContextCapabilities(combined_window=100, **{field: 101})


def test_reasoning_controls_preserve_declared_values_and_round_trip():
    profile = ReasoningCapabilities(
        status="supported",
        controls=[
            ToggleControl(values=[False, True]),
            EffortControl(values=["low", "xhigh", "provider-specific"]),
            BudgetTokensControl(min=0, max=100, special_values=[-1]),
        ],
        response_paths=["choices[].delta.reasoning_content"],
    )
    assert (
        ReasoningCapabilities.model_validate_json(profile.model_dump_json()) == profile
    )
    assert profile.controls[0].values[0] is False
    assert profile.controls[2].special_values == [-1]
    assert "current_value" not in profile.model_dump_json()


def test_reasoning_unknown_and_explicit_no_controls_remain_distinct():
    assert ReasoningCapabilities().controls is None
    assert ReasoningCapabilities(status="unsupported", controls=[]).controls == []
    assert (
        ReasoningCapabilities(controls=[ToggleControl(values=[True])]).status
        == "unknown"
    )


@pytest.mark.parametrize(
    "control",
    [
        {"mode": "toggle", "values": [1]},
        {"mode": "toggle", "values": [False, False]},
        {"mode": "toggle", "values": []},
        {"mode": "toggle", "values": [True], "parameter_key": "reasoning"},
        {"mode": "effort", "values": ["high", "high"]},
        {"mode": "effort", "values": [" "]},
        {"mode": "effort", "values": [1]},
        {"mode": "effort", "values": []},
        {"mode": "budget_tokens", "min": 10, "max": 9},
        {"mode": "budget_tokens", "min": -1, "max": 9},
        {"mode": "budget_tokens", "min": 0, "max": True},
        {"mode": "budget_tokens", "min": 0, "max": 9, "special_values": [False]},
        {"mode": "budget_tokens", "min": 0, "max": 9, "special_values": [-1, -1]},
        {"mode": "unknown"},
        {"mode": "toggle", "values": [True], "unexpected": 1},
    ],
)
def test_reasoning_rejects_invalid_controls(control):
    with pytest.raises(ValidationError):
        ReasoningCapabilities(controls=[control])


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "unsupported", "controls": [{"mode": "toggle", "values": [True]}]},
        {"status": "unsupported", "response_paths": ["reasoning_content"]},
        {
            "status": "supported",
            "controls": [
                {"mode": "effort", "values": ["low"]},
                {"mode": "effort", "values": ["high"]},
            ],
        },
        {"response_paths": ["reasoning_content", "reasoning_content"]},
        {"response_paths": [""]},
        {"status": True},
        {"status": "unknown", "extra": 1},
    ],
)
def test_reasoning_rejects_conflicting_or_unknown_fields(payload):
    with pytest.raises(ValidationError):
        ReasoningCapabilities(**payload)


def test_reasoning_size_limit_counts_utf8_bytes():
    ReasoningCapabilities(controls=[EffortControl(values=["a" * 65000])])
    with pytest.raises(ValidationError, match="64 KiB"):
        ReasoningCapabilities(controls=[EffortControl(values=["思" * 22000])])


def reference_payload():
    return {
        "key": "qwen/Qwen3.8",
        "catalog_revision": "catalog-v1",
        "file_path": "models/qwen/model.toml",
        "content_sha256": "a" * 64,
    }


def test_atomic_reference_round_trip_preserves_exact_identity():
    profile = AtomicProfileReference(**reference_payload())
    assert (
        AtomicProfileReference.model_validate_json(profile.model_dump_json()) == profile
    )
    assert profile.key == "qwen/Qwen3.8"


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/model.toml",
        "../x.toml",
        "models/../x.toml",
        "models/./x.toml",
        "models//x.toml",
        "C:/x.toml",
        "models\\x.toml",
        "",
        "models/",
        "models/\x00file.toml",
    ],
)
def test_atomic_reference_rejects_unsafe_paths(path):
    with pytest.raises(ValidationError):
        AtomicProfileReference(**{**reference_payload(), "file_path": path})


@pytest.mark.parametrize(
    "updates",
    [
        {"content_sha256": "a" * 63},
        {"content_sha256": "A" * 64},
        {"content_sha256": "g" * 64},
        {"key": " "},
        {"catalog_revision": ""},
        {"unknown": "field"},
    ],
)
def test_atomic_reference_rejects_invalid_provenance(updates):
    with pytest.raises(ValidationError):
        AtomicProfileReference(**{**reference_payload(), **updates})


def test_context_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ContextCapabilities(max_tokens=100)


def test_contract_fields_cannot_be_reassigned_without_validation():
    profile = ContextCapabilities(combined_window=100)
    with pytest.raises(ValidationError):
        profile.combined_window = 0
    assert profile.combined_window == 100


@pytest.mark.parametrize(
    "bounds", [{}, {"max": 81920}, {"min": 1}, {"min": 0}, {"max": 0}]
)
def test_reasoning_budget_preserves_missing_bounds_without_defaults(bounds):
    control = BudgetTokensControl(**bounds)
    assert control.min == bounds.get("min")
    assert control.max == bounds.get("max")
    assert BudgetTokensControl.model_validate_json(control.model_dump_json()) == control
    profile = ReasoningCapabilities(status="supported", controls=[control])
    restored = ReasoningCapabilities.model_validate_json(profile.model_dump_json())
    assert restored.controls[0].min == bounds.get("min")
    assert restored.controls[0].max == bounds.get("max")


@pytest.mark.parametrize("field", ["min", "max"])
@pytest.mark.parametrize("invalid", [True, "100", 1.5, -1])
def test_reasoning_budget_rejects_invalid_partial_bounds(field, invalid):
    with pytest.raises(ValidationError):
        BudgetTokensControl(**{field: invalid})


def test_reasoning_budget_keeps_declared_sentinel_and_known_zero_separate():
    control = BudgetTokensControl(max=0, special_values=[-1])
    assert control.min is None
    assert control.max == 0
    assert control.special_values == [-1]


def test_effort_null_sentinel_is_an_explicit_value_not_absent_control():
    control = EffortControl(values=["none", None, "default"])
    restored = EffortControl.model_validate_json(control.model_dump_json())
    assert restored.values == ["none", None, "default"]
    with pytest.raises(ValueError):
        EffortControl(values=[None, None])
