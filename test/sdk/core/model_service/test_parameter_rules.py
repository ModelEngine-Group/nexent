# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Parameter policy preserves values and enforces explicit permissions."""

from copy import deepcopy

import pytest
from nexent.core.model_service.profiles.parameter_rules import (
    apply_parameter_values,
    compile_parameter_rules,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


def rule(key="temperature", **overrides):
    result = {
        "key": key,
        "schema": {},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "common",
        "owner": "provider",
        "source": {"rule_id": "test-v1"},
    }
    result.update(overrides)
    return result


def apply(rules, submitted=None, saved=None, scope="outlet"):
    return apply_parameter_values(
        compile_parameter_rules(rules),
        submitted or {},
        saved_values=saved or {},
        scope=scope,
    )


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_explicit_values_and_defaults_preserve_presence(value):
    assert apply([rule(default_value="default")], {"temperature": value}) == {
        "temperature": value
    }
    assert apply([rule(default_value=value)]) == {"temperature": value}
    assert apply([rule()], saved={"temperature": value}) == {"temperature": value}
    assert apply([rule()]) == {}


@pytest.mark.parametrize("value", [None, False, 0, "", {"private": "fixed-secret"}])
def test_fixed_value_is_written_and_equal_submission_is_allowed(value):
    fixed = rule(fixed_value=value, visible=False, editable=False, allowed_scopes=[])
    assert apply([fixed]) == {"temperature": value}
    assert apply([fixed], {"temperature": value}, scope="conversation") == {
        "temperature": value
    }
    with pytest.raises(ParameterValidationError) as captured:
        apply([fixed], {"temperature": "different-secret"})
    assert captured.value.category == "FIXED_PARAMETER"
    assert "secret" not in str(captured.value)


def test_fixed_saved_conflict_is_not_silently_overwritten():
    with pytest.raises(ParameterValidationError, match="FIXED_PARAMETER"):
        apply([rule(fixed_value=False)], saved={"temperature": 0})


@pytest.mark.parametrize(
    "overrides",
    [
        {"editable": False},
        {"visible": False, "editable": False},
        {"allowed_scopes": ["outlet"]},
    ],
)
def test_conversation_override_requires_explicit_edit_permission(overrides):
    declaration = rule(default_value=0, **overrides)
    with pytest.raises(ParameterValidationError, match="PARAMETER_NOT_EDITABLE"):
        apply([declaration], {"temperature": 1}, scope="conversation")
    assert apply([declaration], scope="conversation") == {"temperature": 0}


def test_visibility_and_required_flags_are_independent():
    assert apply([rule(visible=False)], {"temperature": 1}) == {"temperature": 1}
    with pytest.raises(ParameterValidationError, match="PARAMETER_VALUE_REQUIRED"):
        apply([rule(required=True)])


@pytest.mark.parametrize(
    "condition,enabled,expected",
    [
        ({"key": "enabled", "op": "eq", "value": True}, True, True),
        ({"key": "enabled", "op": "eq", "value": 1}, True, False),
        ({"key": "enabled", "op": "in", "value": [False, None]}, False, True),
        ({"key": "enabled", "op": "exists", "value": True}, None, True),
        ({"all": [{"key": "enabled", "op": "eq", "value": True}]}, False, False),
        (
            {
                "any": [
                    {"key": "enabled", "op": "eq", "value": True},
                    {"key": "enabled", "op": "eq", "value": False},
                ]
            },
            False,
            True,
        ),
    ],
)
def test_conditions_filter_derived_values_and_reject_explicit_inactive_values(
    condition, enabled, expected
):
    declarations = [
        rule("enabled"),
        rule("budget", condition=condition, default_value=0, required=True),
    ]
    result = apply(declarations, {"enabled": enabled})
    assert ("budget" in result) is expected
    if not expected:
        with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
            apply(declarations, {"enabled": enabled, "budget": 0})


def test_missing_is_distinct_from_null_for_conditions():
    declarations = [
        rule("enabled"),
        rule(
            "budget",
            condition={"key": "enabled", "op": "eq", "value": None},
            default_value=0,
        ),
    ]
    assert apply(declarations) == {}
    assert apply(declarations, {"enabled": None}) == {"enabled": None, "budget": 0}


def test_dependency_order_does_not_depend_on_declaration_order():
    declarations = [
        rule(
            "last",
            default_value=2,
            condition={"key": "middle", "op": "exists", "value": True},
        ),
        rule(
            "middle",
            default_value=1,
            condition={"key": "enabled", "op": "eq", "value": True},
        ),
        rule("enabled", default_value=False),
    ]
    assert apply(declarations) == {"enabled": False}
    assert apply(declarations, {"enabled": True}) == {
        "enabled": True,
        "middle": 1,
        "last": 2,
    }


@pytest.mark.parametrize(
    "condition",
    [
        {},
        {"all": []},
        {"any": []},
        {"all": [{}], "any": [{}]},
        {"key": "unknown", "op": "eq", "value": 1},
        {"key": "temperature", "op": "eval", "value": "secret"},
        {"key": "temperature", "op": "exists", "value": 1},
        {"key": "temperature", "op": "in", "value": []},
        {"key": [], "op": "eq", "value": 1},
    ],
)
def test_invalid_conditions_fail_before_use(condition):
    with pytest.raises(ParameterValidationError, match="PARAMETER_CONDITION_INVALID"):
        compile_parameter_rules([rule(condition=condition)])


def test_cycles_and_duplicate_keys_are_rejected():
    with pytest.raises(ParameterValidationError, match="PARAMETER_CONDITION_CYCLE"):
        compile_parameter_rules(
            [rule(condition={"key": "temperature", "op": "exists", "value": True})]
        )
    with pytest.raises(ParameterValidationError, match="PARAMETER_RULE_INVALID"):
        compile_parameter_rules([rule(), rule()])


def test_nested_condition_must_be_an_object():
    with pytest.raises(ParameterValidationError, match="PARAMETER_CONDITION_INVALID"):
        compile_parameter_rules([rule(condition={"all": [True]})])


def test_empty_rule_set_is_valid_and_still_rejects_unknown_parameters():
    assert apply([]) == {}
    with pytest.raises(ParameterValidationError, match="PARAMETER_UNKNOWN"):
        apply([], {"temperature": 1})


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_scopes": ["outlet", "outlet"]},
        {"editable": "true"},
        {"unknown": 1},
        {"default_value": True, "schema": {"type": "number"}},
        {"fixed_value": None, "schema": {"type": "integer"}},
        {"default_value": 0, "fixed_value": False},
    ],
)
def test_invalid_declarations_do_not_compile(overrides):
    with pytest.raises(ParameterValidationError):
        compile_parameter_rules([rule(**overrides)])


def test_snapshots_and_inputs_are_independent():
    declarations = [rule(default_value={"nested": [1]})]
    original = deepcopy(declarations)
    compiled = compile_parameter_rules(declarations)
    declarations[0]["default_value"]["nested"].append(2)
    view = compiled.declarations
    view[0]["default_value"]["nested"].append(3)
    saved = {"temperature": {"nested": [4]}}
    result = apply_parameter_values(compiled, {}, saved_values=saved, scope="outlet")
    result["temperature"]["nested"].append(5)
    assert saved == {"temperature": {"nested": [4]}}
    assert compiled.declarations == original


@pytest.mark.parametrize(
    "submitted,saved", [({"unknown": 1}, {}), ({}, {"unknown": 1})]
)
def test_unknown_values_fail_explicitly(submitted, saved):
    with pytest.raises(ParameterValidationError, match="PARAMETER_UNKNOWN"):
        apply([rule()], submitted, saved)


def test_values_are_checked_including_saved_values_and_null():
    declarations = [rule(schema={"type": "number", "minimum": 0})]
    for submitted, saved in [({"temperature": None}, {}), ({}, {"temperature": -1})]:
        with pytest.raises(ParameterValidationError, match="PARAMETER_VALUE_INVALID"):
            apply(declarations, submitted, saved)
    with pytest.raises(ParameterValidationError, match="PARAMETER_SCOPE_INVALID"):
        apply(declarations, scope="unknown")
