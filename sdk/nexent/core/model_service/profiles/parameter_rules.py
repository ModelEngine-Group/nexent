# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit parameter policy shared by outlet and conversation configuration."""

import json
from dataclasses import dataclass, field
from typing import Literal, Mapping

from pydantic import Field, JsonValue, ValidationError

from nexent.core.model_service.profiles.contracts import NonBlankString, ProfileContract
from nexent.core.model_service.profiles.parameter_schema import (
    CompiledParameterSchema,
    ParameterValidationError,
    compile_parameter_schema,
    json_values_equal,
    validate_parameter_value,
)


class ParameterRule(ProfileContract):
    """Declaration only; field presence distinguishes missing from explicit null."""

    key: NonBlankString
    value_schema: dict = Field(alias="schema")
    visible: bool
    editable: bool
    required: bool
    allowed_scopes: list[Literal["outlet", "conversation"]]
    ui_group: NonBlankString
    owner: Literal["model", "provider", "combination"]
    source: dict[str, JsonValue]
    default_value: JsonValue = Field(default=None, repr=False)
    fixed_value: JsonValue = Field(default=None, repr=False)
    condition: dict | None = None
    api_binding: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class CompiledParameterRules:
    """Validated immutable declarations, schemas and dependency ordering."""

    _declarations: bytes = field(repr=False)
    _schemas: tuple[tuple[str, CompiledParameterSchema], ...] = field(repr=False)
    _order: tuple[str, ...]

    @property
    def declarations(self) -> list[dict]:
        return json.loads(self._declarations)


def _pointer(key: str) -> str:
    return "/" + key.replace("~", "~0").replace("/", "~1")


def _check_condition(condition: object, keys: set[str], path: str) -> set[str]:
    if not isinstance(condition, dict):
        raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
    for operator in ("all", "any"):
        if operator in condition:
            children = condition[operator]
            if set(condition) != {operator} or not isinstance(children, list) or not children:
                raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
            dependencies = set()
            for index, child in enumerate(children):
                dependencies.update(_check_condition(child, keys, f"{path}/{operator}/{index}"))
            return dependencies
    if (
        set(condition) != {"key", "op", "value"}
        or not isinstance(condition.get("key"), str)
        or condition["key"] not in keys
    ):
        raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
    operator, value = condition["op"], condition["value"]
    if operator not in ("eq", "in", "exists"):
        raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
    if operator == "exists" and type(value) is not bool:
        raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
    if operator == "in" and (not isinstance(value, list) or not value):
        raise ParameterValidationError("PARAMETER_CONDITION_INVALID", path)
    validate_parameter_value(compile_parameter_schema({}), value, path)
    return {condition["key"]}


def _condition_matches(condition: dict | None, values: dict) -> bool:
    if condition is None:
        return True
    if "all" in condition:
        return all(_condition_matches(child, values) for child in condition["all"])
    if "any" in condition:
        return any(_condition_matches(child, values) for child in condition["any"])
    key, operator, expected = condition["key"], condition["op"], condition["value"]
    if operator == "exists":
        return (key in values) is expected
    if key not in values:
        return False
    if operator == "eq":
        return json_values_equal(values[key], expected)
    return any(json_values_equal(values[key], option) for option in expected)


def compile_parameter_rules(declarations: list[dict]) -> CompiledParameterRules:
    """Reject ambiguous rules before they can accept user configuration."""
    validate_parameter_value(compile_parameter_schema({"type": "array", "items": {"type": "object"}}), declarations)
    encoded = json.dumps(declarations, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    # Work from a detached JSON snapshot, never retain caller-owned containers.
    copied = json.loads(encoded)
    rules, schemas = {}, {}
    for declaration in copied:
        try:
            rule = ParameterRule.model_validate(declaration)
        except ValidationError:
            raise ParameterValidationError("PARAMETER_RULE_INVALID") from None
        if rule.key in rules or len(set(rule.allowed_scopes)) != len(rule.allowed_scopes):
            raise ParameterValidationError("PARAMETER_RULE_INVALID", _pointer(rule.key))
        schema = compile_parameter_schema(rule.value_schema)
        for name in ("default_value", "fixed_value"):
            if name in rule.model_fields_set:
                validate_parameter_value(schema, getattr(rule, name), _pointer(rule.key))
        if {"default_value", "fixed_value"} <= rule.model_fields_set and not json_values_equal(
            rule.default_value, rule.fixed_value
        ):
            raise ParameterValidationError("PARAMETER_RULE_INVALID", _pointer(rule.key))
        rules[rule.key], schemas[rule.key] = rule, schema
    dependencies = {
        key: _check_condition(rule.condition, set(rules), _pointer(key) + "/condition")
        if rule.condition is not None
        else set()
        for key, rule in rules.items()
    }
    order = []
    while dependencies:
        ready = sorted(key for key, parents in dependencies.items() if not parents)
        if not ready:
            raise ParameterValidationError("PARAMETER_CONDITION_CYCLE", _pointer(min(dependencies)))
        order.extend(ready)
        for key in ready:
            del dependencies[key]
        for parents in dependencies.values():
            parents.difference_update(ready)
    return CompiledParameterRules(encoded, tuple(schemas.items()), tuple(order))


def apply_parameter_values(
    compiled: CompiledParameterRules,
    submitted: Mapping[str, object],
    *,
    scope: Literal["outlet", "conversation"],
    saved_values: Mapping[str, object],
) -> dict:
    """Build a detached effective view; never mutate saved values or declarations."""
    if scope not in ("outlet", "conversation"):
        raise ParameterValidationError("PARAMETER_SCOPE_INVALID")
    object_schema = compile_parameter_schema({"type": "object"})
    validate_parameter_value(object_schema, submitted)
    validate_parameter_value(object_schema, saved_values)
    submitted = json.loads(json.dumps(dict(submitted)))
    saved_values = json.loads(json.dumps(dict(saved_values)))
    rules = {rule["key"]: rule for rule in compiled.declarations}
    schemas = dict(compiled._schemas)
    for key in submitted.keys() | saved_values.keys():
        if key not in rules:
            raise ParameterValidationError("PARAMETER_UNKNOWN", _pointer(key))
    values = {}
    for key, rule in rules.items():
        if "fixed_value" in rule:
            values[key] = rule["fixed_value"]
            if key in saved_values and not json_values_equal(saved_values[key], values[key]):
                raise ParameterValidationError("FIXED_PARAMETER", _pointer(key))
        elif key in saved_values:
            values[key] = saved_values[key]
        elif "default_value" in rule:
            values[key] = rule["default_value"]
        if key in submitted:
            if "fixed_value" in rule:
                if not json_values_equal(submitted[key], values[key]):
                    raise ParameterValidationError("FIXED_PARAMETER", _pointer(key))
            elif not rule["editable"] or scope not in rule["allowed_scopes"]:
                raise ParameterValidationError("PARAMETER_NOT_EDITABLE", _pointer(key))
            values[key] = submitted[key]
        if key in values:
            validate_parameter_value(schemas[key], values[key], _pointer(key))
    for key in compiled._order:
        rule = rules[key]
        if not _condition_matches(rule.get("condition"), values):
            if key in submitted:
                raise ParameterValidationError("PARAMETER_DEPENDENCY", _pointer(key))
            values.pop(key, None)
        elif rule["required"] and key not in values:
            raise ParameterValidationError("PARAMETER_VALUE_REQUIRED", _pointer(key))
    return values


def overlay_saved_parameter_values(compiled, submitted, *, scope, saved_values):
    """Apply explicit run choices without creation defaults or silent dependency removal."""
    if scope not in {"outlet", "conversation"}:
        raise ParameterValidationError("PARAMETER_SCOPE_INVALID")
    validate_parameter_value(compile_parameter_schema({"type": "object"}), submitted)
    rules = {rule["key"]: rule for rule in compiled.declarations}
    values = dict(saved_values)
    for key, value in submitted.items():
        if key not in rules:
            raise ParameterValidationError("PARAMETER_UNKNOWN", _pointer(key))
        rule = rules[key]
        if scope == "conversation" and (not rule["editable"] or scope not in rule["allowed_scopes"]):
            raise ParameterValidationError("PARAMETER_NOT_EDITABLE", _pointer(key))
        if "fixed_value" in rule:
            if not json_values_equal(value, rule["fixed_value"]):
                raise ParameterValidationError("FIXED_PARAMETER", _pointer(key))
        elif (not rule["editable"] or scope not in rule["allowed_scopes"]) and not (
                key in saved_values and json_values_equal(value, saved_values[key])):
            raise ParameterValidationError("PARAMETER_NOT_EDITABLE", _pointer(key))
        values[key] = value
    return validate_saved_parameter_values(compiled, values)


def validate_saved_parameter_values(
    compiled: CompiledParameterRules,
    saved_values: Mapping[str, object],
) -> dict:
    """Validate a persisted snapshot without applying defaults or changing presence."""
    validate_parameter_value(compile_parameter_schema({"type": "object"}), saved_values)
    values = json.loads(json.dumps(dict(saved_values)))
    rules = {rule["key"]: rule for rule in compiled.declarations}
    schemas = dict(compiled._schemas)
    for key in values:
        if key not in rules:
            raise ParameterValidationError("PARAMETER_UNKNOWN", _pointer(key))
        validate_parameter_value(schemas[key], values[key], _pointer(key))
    for key in compiled._order:
        rule = rules[key]
        active = _condition_matches(rule.get("condition"), values)
        if not active:
            if key in values:
                raise ParameterValidationError("PARAMETER_DEPENDENCY", _pointer(key))
            continue
        if "fixed_value" in rule:
            if key not in values or not json_values_equal(values[key], rule["fixed_value"]):
                raise ParameterValidationError("FIXED_PARAMETER", _pointer(key))
        elif rule["required"] and key not in values:
            raise ParameterValidationError("PARAMETER_VALUE_REQUIRED", _pointer(key))
    return values


def overlay_profile_parameters(profile, submitted, *, scope):
    """Exclude inactive inherited thinking values, never contradictory explicit input."""
    inherited = dict(profile.parameter_values)
    if submitted.get("enable_thinking") is False:
        for rule in profile.parameter_rules:
            if (rule.get("condition") == {"key": "enable_thinking", "op": "eq", "value": True}
                    and rule["key"] not in submitted):
                inherited.pop(rule["key"], None)
    values = overlay_saved_parameter_values(
        compile_parameter_rules(profile.parameter_rules), submitted, scope=scope, saved_values=inherited,
    )
    data = profile.model_dump(mode="json")
    data["parameter_values"] = values
    return profile.__class__.model_validate(data)


def patch_parameter_values(saved, submitted, deleted):
    """Apply explicit deletions without copying defaults into persistent overrides."""
    if len(set(deleted)) != len(deleted) or set(deleted) & submitted.keys():
        raise ParameterValidationError("PARAMETER_UPDATE_CONFLICT")
    return {**{key: value for key, value in saved.items() if key not in deleted}, **submitted}
