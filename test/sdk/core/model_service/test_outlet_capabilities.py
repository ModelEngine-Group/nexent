# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Capability storage ownership preserves tri-state declarations and rejects corruption."""

from copy import deepcopy

import pytest
from nexent.core.model_service.profiles.contracts import ProfileCapabilities
from nexent.core.model_service.profiles.outlet_capabilities import (
    CapabilityStorageError,
    restore_outlet_capabilities,
    split_outlet_capabilities,
)


def restore(stored):
    return restore_outlet_capabilities(
        columns=stored.columns, capability_details=stored.capability_details
    )


@pytest.mark.parametrize(
    "status,column_value",
    [("supported", True), ("unsupported", False), ("unknown", None)],
)
def test_all_support_columns_preserve_tri_state(status, column_value):
    value = ProfileCapabilities.model_validate(
        {
            "reasoning": {"status": status},
            "tools": {"status": status},
            "structured_output": {"status": status},
            "sampling": {
                "temperature": {"status": status},
                "top_p": {"status": status},
            },
        }
    )
    stored = split_outlet_capabilities(value)
    for column in (
        "reasoning_supported",
        "native_tool_call_supported",
        "structured_output_supported",
        "temperature_supported",
        "top_p_supported",
    ):
        assert stored.columns[column] is column_value
    assert restore(stored).model_dump() == value.model_dump()


def test_round_trip_has_no_duplicate_capability_values_and_is_detached():
    value = ProfileCapabilities.model_validate(
        {
            "context": {
                "combined_window": 200000,
                "input_limit": 180000,
                "output_limit": 10000,
            },
            "reasoning": {
                "status": "supported",
                "controls": [{"mode": "toggle", "values": [False, True]}],
                "response_paths": ["reasoning_content"],
            },
            "tools": {
                "status": "supported",
                "schema_constraints": {"ref": "tools_v1", "version": 1},
                "result_format": "tool",
            },
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "response": {
                "supported_finish_reasons": ["stop", "tool_calls"],
                "stream_format": "sse",
            },
            "usage": {
                "semantics_id": "tokens_v1",
                "input_includes_cached": "supported",
                "output_includes_reasoning": "unknown",
            },
        }
    )
    original = value.model_dump()
    stored = split_outlet_capabilities(value)
    assert stored.columns["context_window_tokens"] == 200000
    assert stored.columns["reasoning_controls"][0]["values"] == [False, True]
    assert set(stored.capability_details) == {"reasoning", "tools", "response", "usage"}
    assert set(stored.capability_details["reasoning"]) == {"response_paths"}
    assert set(stored.capability_details["tools"]) == {
        "schema_constraints",
        "result_format",
    }
    assert restore(stored).model_dump() == original
    restored = restore(stored)
    restored.modalities.input.append("audio")
    restored.reasoning.controls[0].values.pop()
    assert value.model_dump() == original
    assert stored.columns["input_modalities"] == ["text", "image"]
    value.modalities.input.append("video")
    assert stored.columns["input_modalities"] == ["text", "image"]


@pytest.mark.parametrize("controls,modalities", [(None, None), ([], [])])
def test_unknown_and_explicit_empty_domains_remain_distinct(controls, modalities):
    value = ProfileCapabilities.model_validate(
        {"reasoning": {"controls": controls}, "modalities": {"input": modalities}}
    )
    restored = restore(split_outlet_capabilities(value))
    assert restored.reasoning.controls == controls
    assert restored.modalities.input == modalities


@pytest.mark.parametrize(
    "column",
    [
        "reasoning_supported",
        "native_tool_call_supported",
        "structured_output_supported",
        "temperature_supported",
        "top_p_supported",
    ],
)
@pytest.mark.parametrize("bad", [0, 1, "false", "unknown", {}, []])
def test_boolean_columns_never_coerce_unknown_or_false(column, bad):
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.columns[column] = bad
    with pytest.raises(CapabilityStorageError, match="^PROFILE_STORAGE_INVALID$"):
        restore(stored)


@pytest.mark.parametrize(
    "group,duplicate",
    [
        ("reasoning", "status"),
        ("reasoning", "controls"),
        ("tools", "status"),
        ("response", "unexpected"),
        ("usage", "unexpected"),
    ],
)
def test_duplicate_or_undeclared_detail_fields_fail(group, duplicate):
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.capability_details[group][duplicate] = "secret-value"
    with pytest.raises(CapabilityStorageError) as captured:
        restore(stored)
    assert "secret-value" not in str(captured.value)


@pytest.mark.parametrize(
    "target,key",
    [
        ("columns", "context_window_tokens"),
        ("columns", "reasoning_controls"),
        ("capability_details", "usage"),
    ],
)
def test_missing_storage_fields_are_not_reconstructed_from_defaults(target, key):
    stored = split_outlet_capabilities(ProfileCapabilities())
    getattr(stored, target).pop(key)
    with pytest.raises(CapabilityStorageError):
        restore(stored)


@pytest.mark.parametrize(
    "column,value",
    [
        ("context_window_tokens", 0),
        ("max_input_tokens", True),
        ("max_output_tokens", 2**31),
        ("input_modalities", ["text", "text"]),
        ("reasoning_controls", [{"mode": "toggle", "values": [0, 1]}]),
    ],
)
def test_invalid_column_values_fail_before_profile_publication(column, value):
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.columns[column] = value
    original = deepcopy(stored)
    with pytest.raises(CapabilityStorageError):
        restore(stored)
    assert stored == original


def test_unsupported_reasoning_with_saved_controls_fails():
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.columns["reasoning_supported"] = False
    stored.columns["reasoning_controls"] = [{"mode": "toggle", "values": [True]}]
    with pytest.raises(CapabilityStorageError):
        restore(stored)


def test_capacity_relationships_are_validated_after_restore():
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.columns["context_window_tokens"] = 100
    stored.columns["max_input_tokens"] = 101
    with pytest.raises(CapabilityStorageError):
        restore(stored)


@pytest.mark.parametrize("details", [None, [], {"unexpected": "secret"}])
def test_invalid_detail_container_is_rejected(details):
    stored = split_outlet_capabilities(ProfileCapabilities())
    with pytest.raises(CapabilityStorageError):
        restore_outlet_capabilities(columns=stored.columns, capability_details=details)


def test_invalid_detail_group_is_rejected():
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.capability_details["usage"] = None
    with pytest.raises(CapabilityStorageError):
        restore(stored)


def test_int4_capacity_bound_and_configuration_size_are_checked_on_save():
    with pytest.raises(CapabilityStorageError):
        split_outlet_capabilities(
            ProfileCapabilities(context={"combined_window": 2**31})
        )
    value = ProfileCapabilities(context={"combined_window": 2**31 - 1})
    assert (
        restore(split_outlet_capabilities(value)).context.combined_window == 2**31 - 1
    )
    with pytest.raises(CapabilityStorageError):
        split_outlet_capabilities(
            ProfileCapabilities(usage={"semantics_id": "x" * (1024 * 1024)})
        )


@pytest.mark.parametrize("bad", [None, {}, "secret"])
def test_save_requires_a_complete_typed_object(bad):
    with pytest.raises(CapabilityStorageError):
        split_outlet_capabilities(bad)


def test_restore_rejects_non_json_and_cyclic_inputs():
    stored = split_outlet_capabilities(ProfileCapabilities())
    stored.capability_details["usage"]["semantics_id"] = float("nan")
    with pytest.raises(CapabilityStorageError):
        restore(stored)
    stored.capability_details["usage"]["semantics_id"] = stored.capability_details
    with pytest.raises(CapabilityStorageError):
        restore(stored)
