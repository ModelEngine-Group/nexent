# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Complete capability contracts preserve unknown state and reject undeclared fields."""

import pytest
from nexent.core.model_service.profiles.contracts import ProfileCapabilities
from pydantic import ValidationError


def test_missing_capabilities_are_unknown_not_supported_or_false():
    capabilities = ProfileCapabilities()
    assert capabilities.context.combined_window is None
    assert capabilities.reasoning.status == "unknown"
    assert capabilities.reasoning.controls is None
    assert capabilities.tools.status == "unknown"
    assert capabilities.modalities.input is None
    assert capabilities.response.supported_finish_reasons is None
    assert capabilities.usage.input_includes_cached == "unknown"
    assert capabilities.usage.output_includes_reasoning == "unknown"
    assert capabilities.sampling.top_p.status == "unknown"


@pytest.mark.parametrize("status", ["supported", "unsupported", "unknown"])
def test_top_p_support_is_independent_of_temperature(status):
    capabilities = ProfileCapabilities.model_validate(
        {"sampling": {"top_p": {"status": status}}}
    )
    assert capabilities.sampling.top_p.status == status
    assert capabilities.sampling.temperature.status == "unknown"


@pytest.mark.parametrize(
    "value",
    [
        True,
        0.5,
        {"status": False},
        {"status": "maybe"},
        {"status": "supported", "value": 0.5},
    ],
)
def test_top_p_rejects_parameter_values_and_undeclared_support(value):
    with pytest.raises(ValidationError):
        ProfileCapabilities.model_validate({"sampling": {"top_p": value}})


@pytest.mark.parametrize(
    "group,field",
    [
        ("modalities", "input"),
        ("modalities", "output"),
        ("response", "supported_finish_reasons"),
    ],
)
def test_empty_list_is_explicit_and_not_missing(group, field):
    value = ProfileCapabilities.model_validate({group: {field: []}})
    assert getattr(getattr(value, group), field) == []
    with pytest.raises(ValidationError):
        ProfileCapabilities.model_validate({group: {field: ["same", "same"]}})


@pytest.mark.parametrize(
    "group",
    [
        "context",
        "reasoning",
        "tools",
        "sampling",
        "structured_output",
        "modalities",
        "response",
        "usage",
    ],
)
def test_all_groups_reject_unknown_nested_fields(group):
    with pytest.raises(ValidationError):
        ProfileCapabilities.model_validate({group: {"unknown": 1}})


def test_sampling_support_is_not_a_numeric_default():
    for invalid in [False, 0.7, {"status": True}]:
        with pytest.raises(ValidationError):
            ProfileCapabilities.model_validate({"sampling": {"temperature": invalid}})
    assert (
        ProfileCapabilities.model_validate(
            {"sampling": {"temperature": {"status": "supported"}}}
        ).sampling.temperature.status
        == "supported"
    )


def test_tool_constraint_reference_is_explicit_and_typed():
    value = ProfileCapabilities.model_validate(
        {
            "tools": {
                "status": "supported",
                "schema_constraints": {"ref": "tools_schema_v1", "version": 1},
                "result_format": "tool_messages_v1",
            }
        }
    )
    assert value.tools.schema_constraints.version == 1
    with pytest.raises(ValidationError):
        ProfileCapabilities.model_validate(
            {"tools": {"schema_constraints": {"ref": "unknown", "version": True}}}
        )


def test_usage_semantics_never_coerce_boolean_to_status():
    with pytest.raises(ValidationError):
        ProfileCapabilities.model_validate({"usage": {"input_includes_cached": True}})
    value = ProfileCapabilities.model_validate(
        {
            "usage": {
                "semantics_id": "usage_v1",
                "input_includes_cached": "supported",
                "output_includes_reasoning": "unsupported",
            }
        }
    )
    assert value.usage.semantics_id == "usage_v1"
    assert value.usage.output_includes_reasoning == "unsupported"
