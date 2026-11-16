# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Persisted parameter presence survives the single-location storage boundary."""

from copy import deepcopy

import pytest
from nexent.core.model_service.profiles.outlet_parameters import (
    DEDICATED_PARAMETER_KEYS,
    PARAMETER_COLUMNS,
    restore_outlet_parameters,
    split_outlet_parameters,
)
from nexent.core.model_service.profiles.parameter_rules import (
    apply_parameter_values,
    compile_parameter_rules,
    validate_saved_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


def declaration(key, **changes):
    value = {
        "key": key,
        "schema": {},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "common",
        "owner": "provider",
        "source": {"rule_id": "test"},
    }
    value.update(changes)
    return value


def restore(compiled, stored):
    return restore_outlet_parameters(
        compiled,
        columns=stored.columns,
        parameter_values=stored.parameter_values,
        explicit_null_parameters=stored.explicit_null_parameters,
    )


def test_creation_defaults_are_not_reapplied_on_saved_snapshot_load():
    rules = compile_parameter_rules(
        [declaration("enable_thinking", default_value=True)]
    )
    assert apply_parameter_values(rules, {}, scope="outlet", saved_values={}) == {
        "enable_thinking": True
    }
    assert validate_saved_parameter_values(rules, {}) == {}
    stored = split_outlet_parameters(rules, {})
    assert stored.explicit_null_parameters == []
    assert restore(rules, stored) == {}


@pytest.mark.parametrize("key", ["temperature", "top_p"])
def test_float_columns_reject_integer_rounding(key):
    rules = compile_parameter_rules([declaration(key)])
    with pytest.raises(ParameterValidationError, match="PARAMETER_COLUMN_INVALID"):
        split_outlet_parameters(rules, {key: 2**53 + 1})
    assert restore(rules, split_outlet_parameters(rules, {key: 2**53})) == {key: 2**53}


@pytest.mark.parametrize(
    "key,value",
    [
        ("temperature", 0),
        ("temperature", None),
        ("top_p", 0),
        ("top_p", None),
        ("enable_thinking", False),
        ("enable_thinking", None),
        ("reasoning_effort", "none"),
        ("reasoning_effort", None),
        ("reasoning_budget_tokens", 0),
        ("reasoning_budget_tokens", -1),
        ("reasoning_budget_tokens", None),
        ("custom", None),
        ("custom", False),
        ("max_output_tokens", 4096),
        ("max_output_tokens", None),
    ],
)
def test_round_trip_preserves_value_and_key_presence(key, value):
    rules = compile_parameter_rules([declaration(key)])
    stored = split_outlet_parameters(rules, {key: value})
    assert restore(rules, stored) == {key: value}
    if key in DEDICATED_PARAMETER_KEYS:
        assert key not in stored.parameter_values
        assert stored.explicit_null_parameters == ([key] if value is None else [])
    else:
        assert stored.parameter_values == {key: value}
        assert stored.explicit_null_parameters == []


def test_split_and_restore_return_detached_values_and_never_change_rules():
    declarations = [declaration("custom", default_value={"a": [1]})]
    rules = compile_parameter_rules(declarations)
    values = {"custom": {"a": [2]}}
    stored = split_outlet_parameters(rules, values)
    values["custom"]["a"].append(3)
    result = restore(rules, stored)
    result["custom"]["a"].append(4)
    assert stored.parameter_values == {"custom": {"a": [2]}}
    assert rules.declarations == declarations


@pytest.mark.parametrize(
    "changes",
    [
        {"explicit_null_parameters": ["temperature", "temperature"]},
        {"explicit_null_parameters": ["custom"]},
        {"explicit_null_parameters": [None]},
        {"explicit_null_parameters": "temperature"},
        {"explicit_null_parameters": {"temperature"}},
        {"columns": {}},
        {"columns": None},
        {"parameter_values": {"temperature": None}},
        {"parameter_values": None},
    ],
)
def test_corrupt_storage_is_rejected(changes):
    rules = compile_parameter_rules([declaration("temperature")])
    stored = split_outlet_parameters(rules, {})
    arguments = {
        "columns": stored.columns,
        "parameter_values": stored.parameter_values,
        "explicit_null_parameters": stored.explicit_null_parameters,
    }
    arguments.update(changes)
    with pytest.raises(ParameterValidationError):
        restore_outlet_parameters(rules, **arguments)


def test_non_null_column_cannot_have_a_null_marker():
    rules = compile_parameter_rules([declaration("temperature")])
    stored = split_outlet_parameters(rules, {"temperature": 0})
    stored.explicit_null_parameters = ["temperature"]
    with pytest.raises(
        ParameterValidationError, match="PARAMETER_NULL_MARKERS_INVALID"
    ):
        restore(rules, stored)


@pytest.mark.parametrize(
    "key,value",
    [
        ("temperature", True),
        ("temperature", 10**1000),
        ("top_p", "0.5"),
        ("enable_thinking", 0),
        ("reasoning_effort", "x" * 31),
        ("reasoning_effort", " "),
        ("reasoning_budget_tokens", True),
        ("reasoning_budget_tokens", 1.5),
        ("reasoning_budget_tokens", 2**31),
        ("reasoning_budget_tokens", -(2**31) - 1),
        ("max_output_tokens", True),
        ("max_output_tokens", 0),
        ("max_output_tokens", 2**31),
    ],
)
def test_dedicated_column_types_and_limits_are_enforced(key, value):
    rules = compile_parameter_rules([declaration(key)])
    with pytest.raises(ParameterValidationError, match="PARAMETER_COLUMN_INVALID"):
        split_outlet_parameters(rules, {key: value})
    stored = split_outlet_parameters(rules, {})
    stored.columns[PARAMETER_COLUMNS[key]] = value
    with pytest.raises(ParameterValidationError, match="PARAMETER_COLUMN_INVALID"):
        restore(rules, stored)


@pytest.mark.parametrize("value", [-(2**31), 2**31 - 1])
def test_int4_boundary_values_are_preserved_when_declared(value):
    rules = compile_parameter_rules([declaration("reasoning_budget_tokens")])
    assert restore(
        rules, split_outlet_parameters(rules, {"reasoning_budget_tokens": value})
    ) == {
        "reasoning_budget_tokens": value,
    }


@pytest.mark.parametrize(
    "fields,values,category",
    [
        ([declaration("custom", required=True)], {}, "PARAMETER_VALUE_REQUIRED"),
        ([declaration("custom", fixed_value=0)], {}, "FIXED_PARAMETER"),
        ([declaration("custom", fixed_value=False)], {"custom": 0}, "FIXED_PARAMETER"),
        ([declaration("custom")], {"unknown": "secret"}, "PARAMETER_UNKNOWN"),
        (
            [declaration("custom", schema={"type": "boolean"})],
            {"custom": 0},
            "PARAMETER_VALUE_INVALID",
        ),
    ],
)
def test_saved_validation_rejects_invalid_snapshots_without_repair(
    fields, values, category
):
    original = deepcopy(values)
    with pytest.raises(ParameterValidationError) as captured:
        validate_saved_parameter_values(compile_parameter_rules(fields), values)
    assert captured.value.category == category
    assert "secret" not in str(captured.value)
    assert values == original


def test_saved_inactive_values_fail_instead_of_disappearing():
    rules = compile_parameter_rules(
        [
            declaration("enable_thinking", default_value=True),
            declaration(
                "reasoning_budget_tokens",
                condition={"key": "enable_thinking", "op": "eq", "value": True},
            ),
        ]
    )
    assert validate_saved_parameter_values(rules, {"enable_thinking": False}) == {
        "enable_thinking": False
    }
    for values in (
        {"reasoning_budget_tokens": 0},
        {"enable_thinking": False, "reasoning_budget_tokens": 0},
    ):
        with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
            validate_saved_parameter_values(rules, values)


def test_inactive_fixed_rule_does_not_create_a_value_on_load():
    rules = compile_parameter_rules(
        [
            declaration("enabled"),
            declaration(
                "custom",
                fixed_value=0,
                condition={"key": "enabled", "op": "eq", "value": True},
            ),
        ]
    )
    assert validate_saved_parameter_values(rules, {}) == {}
    assert validate_saved_parameter_values(rules, {"enabled": True, "custom": 0}) == {
        "enabled": True,
        "custom": 0,
    }
