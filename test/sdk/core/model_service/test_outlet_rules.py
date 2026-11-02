# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Same-row domain and fixed-value references preserve rule semantics."""

from copy import deepcopy

import pytest
from nexent.core.model_service.profiles.outlet_rules import (
    RuleStorageError,
    restore_parameter_rules,
    store_parameter_rules,
)
from nexent.core.model_service.profiles.parameter_rules import (
    compile_parameter_rules,
    validate_saved_parameter_values,
)


def declaration(key="enable_thinking", **changes):
    result = {
        "key": key,
        "schema": {},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "common",
        "owner": "provider",
        "source": {"rule_id": "fixture"},
    }
    result.update(changes)
    return result


@pytest.mark.parametrize(
    "key,control,schema,value,keywords",
    [
        (
            "enable_thinking",
            {"mode": "toggle", "values": [False, True]},
            {"type": "boolean", "enum": [False, True]},
            False,
            ["enum"],
        ),
        (
            "reasoning_effort",
            {"mode": "effort", "values": [None, "low", "high"]},
            {"type": ["string", "null"], "enum": [None, "low", "high"]},
            None,
            ["enum"],
        ),
        (
            "reasoning_budget_tokens",
            {"mode": "budget_tokens", "min": 0, "max": 81920},
            {"type": "integer", "minimum": 0, "maximum": 81920},
            0,
            ["maximum", "minimum"],
        ),
    ],
)
def test_declared_domains_are_stored_once_and_restore_exact_schema(
    key, control, schema, value, keywords
):
    declarations = [declaration(key, schema=schema)]
    compiled = compile_parameter_rules(declarations)
    stored = store_parameter_rules(
        compiled, reasoning_controls=[control], saved_values={key: value}
    )
    assert stored[0]["value_domain_ref"] == {
        "mode": control["mode"],
        "keywords": keywords,
    }
    assert not set(keywords) & stored[0]["schema"].keys()
    restored = restore_parameter_rules(
        stored, reasoning_controls=[control], saved_values={key: value}
    )
    assert restored.declarations == declarations
    assert validate_saved_parameter_values(restored, {key: value}) == {key: value}
    assert compiled.declarations == declarations


def test_more_restrictive_limits_and_unknown_bounds_are_not_expanded():
    controls = [{"mode": "budget_tokens", "max": 81920}]
    schema = {"type": "integer", "minimum": 0, "maximum": 40000}
    compiled = compile_parameter_rules(
        [declaration("reasoning_budget_tokens", schema=schema)]
    )
    stored = store_parameter_rules(
        compiled, reasoning_controls=controls, saved_values={}
    )
    assert "value_domain_ref" not in stored[0]
    assert stored[0]["schema"] == schema
    assert (
        restore_parameter_rules(
            stored, reasoning_controls=controls, saved_values={}
        ).declarations
        == compiled.declarations
    )


@pytest.mark.parametrize("value", [False, 0, None, "", {"a": [1]}])
def test_fixed_values_use_saved_presence_and_round_trip_without_value_copy(value):
    compiled = compile_parameter_rules([declaration("custom", fixed_value=value)])
    stored = store_parameter_rules(
        compiled, reasoning_controls=None, saved_values={"custom": value}
    )
    assert "fixed_value" not in stored[0]
    assert stored[0]["fixed_to_saved_value"] is True
    restored = restore_parameter_rules(
        stored, reasoning_controls=None, saved_values={"custom": value}
    )
    assert restored.declarations == compiled.declarations
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(stored, reasoning_controls=None, saved_values={})


def test_inactive_fixed_constraint_is_preserved_and_default_is_not_applied():
    compiled = compile_parameter_rules(
        [
            declaration("enabled", default_value=True),
            declaration(
                "custom",
                fixed_value=0,
                condition={"key": "enabled", "op": "eq", "value": True},
            ),
        ]
    )
    stored = store_parameter_rules(compiled, reasoning_controls=[], saved_values={})
    assert stored[1]["fixed_value"] == 0
    assert "fixed_to_saved_value" not in stored[1]
    restored = restore_parameter_rules(stored, reasoning_controls=[], saved_values={})
    assert restored.declarations == compiled.declarations
    assert validate_saved_parameter_values(restored, {}) == {}


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"mode": "effort", "keywords": ["enum"]},
        {"mode": "toggle", "keywords": []},
        {"mode": "toggle", "keywords": ["enum", "enum"]},
        {"mode": "toggle", "keywords": [None]},
        {"mode": "toggle", "keywords": ["maximum"]},
        {"mode": "toggle", "keywords": ["enum"], "extra": True},
    ],
)
def test_invalid_domain_references_are_rejected(reference):
    rule = declaration(value_domain_ref=reference)
    with pytest.raises(RuleStorageError, match="^PROFILE_STORAGE_INVALID$"):
        restore_parameter_rules(
            [rule],
            reasoning_controls=[{"mode": "toggle", "values": [False, True]}],
            saved_values={},
        )


def test_duplicate_domain_constraint_cannot_override_the_reference():
    rule = declaration(
        schema={"enum": [False]},
        value_domain_ref={"mode": "toggle", "keywords": ["enum"]},
    )
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(
            [rule],
            reasoning_controls=[{"mode": "toggle", "values": [False, True]}],
            saved_values={},
        )


@pytest.mark.parametrize(
    "key,controls,reference",
    [
        (
            "custom",
            [{"mode": "toggle", "values": [False, True]}],
            {"mode": "toggle", "keywords": ["enum"]},
        ),
        (
            "reasoning_budget_tokens",
            [{"mode": "budget_tokens", "max": 10}],
            {"mode": "budget_tokens", "keywords": ["minimum"]},
        ),
        ("enable_thinking", None, {"mode": "toggle", "keywords": ["enum"]}),
    ],
)
def test_missing_or_wrong_control_domain_is_not_inferred(key, controls, reference):
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(
            [declaration(key, value_domain_ref=reference)],
            reasoning_controls=controls,
            saved_values={},
        )


@pytest.mark.parametrize(
    "rule",
    [
        declaration(fixed_to_saved_value=False),
        declaration(fixed_to_saved_value=1),
        declaration(fixed_to_saved_value=True, fixed_value=False),
    ],
)
def test_fixed_reference_marker_is_strict_and_cannot_duplicate_values(rule):
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(
            [rule], reasoning_controls=None, saved_values={"enable_thinking": False}
        )


@pytest.mark.parametrize(
    "controls",
    [
        [{"mode": "toggle", "values": [True]}] * 2,
        [{"mode": "toggle", "values": [1]}],
        {},
    ],
)
def test_invalid_control_domains_fail_on_both_boundaries(controls):
    compiled = compile_parameter_rules([declaration()])
    with pytest.raises(RuleStorageError):
        store_parameter_rules(compiled, reasoning_controls=controls, saved_values={})
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(
            compiled.declarations, reasoning_controls=controls, saved_values={}
        )


def test_failed_restore_does_not_mutate_declarations_or_include_private_values():
    rules = [declaration("private", schema={"type": "integer"})]
    original = deepcopy(rules)
    with pytest.raises(RuleStorageError) as captured:
        restore_parameter_rules(
            rules,
            reasoning_controls=None,
            saved_values={"private": "credential-secret"},
        )
    assert rules == original
    assert "credential-secret" not in str(captured.value)


@pytest.mark.parametrize(
    "rules",
    [None, {}, [None], [{"key": "x", "schema": None}], [declaration(unknown=True)]],
)
def test_invalid_stored_rule_structure_fails(rules):
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(rules, reasoning_controls=None, saved_values={})


def test_oversized_rules_fail_with_sanitized_storage_error():
    compiled = compile_parameter_rules(
        [declaration(source={"note": "x" * (1024 * 1024)})]
    )
    with pytest.raises(RuleStorageError):
        store_parameter_rules(compiled, reasoning_controls=None, saved_values={})
    with pytest.raises(RuleStorageError):
        restore_parameter_rules(
            compiled.declarations, reasoning_controls=None, saved_values={}
        )
