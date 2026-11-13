# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Finite parameter schema compilation and value validation boundaries."""

import pytest
from nexent.core.model_service.profiles.parameter_schema import (
    ParameterValidationError,
    compile_parameter_schema,
    json_values_equal,
    validate_parameter_value,
)


@pytest.mark.parametrize(
    "schema,value",
    [
        ({"type": "boolean"}, False),
        ({"type": "integer", "minimum": 0, "maximum": 10}, 0),
        ({"type": ["number", "null"]}, None),
        ({"type": "number"}, 0.5),
        ({"type": "string", "minLength": 0, "maxLength": 2}, ""),
        ({"enum": [False, 0, None, "default"]}, False),
        ({"enum": [False, 0, None]}, 0),
        ({"const": None}, None),
        ({"type": "array", "items": {"type": "integer"}}, [1, 2]),
        (
            {
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
                "additionalProperties": False,
            },
            {"enabled": False},
        ),
        (
            {"type": "object", "additionalProperties": {"type": "number"}},
            {"custom": 0.1},
        ),
    ],
)
def test_declared_schema_accepts_valid_boundary_values(schema, value):
    validate_parameter_value(compile_parameter_schema(schema), value)


@pytest.mark.parametrize(
    "schema,value,keyword,path",
    [
        ({"type": "integer"}, True, "type", ""),
        ({"type": "number"}, False, "type", ""),
        ({"type": "integer"}, 1.0, "type", ""),
        ({"type": "boolean"}, 0, "type", ""),
        ({"type": "number", "minimum": 0}, -1, "minimum", ""),
        ({"type": "number", "maximum": 1}, 2, "maximum", ""),
        ({"type": "string", "minLength": 2}, "", "minLength", ""),
        ({"type": "string", "maxLength": 1}, "ab", "maxLength", ""),
        ({"enum": [0]}, False, "enum", ""),
        ({"const": False}, 0, "const", ""),
        ({"type": "array", "items": {"type": "boolean"}}, [False, 0], "type", "/1"),
        ({"type": "object", "required": ["enabled"]}, {}, "required", "/enabled"),
        (
            {"properties": {"a/b~c": {"type": "boolean"}}},
            {"a/b~c": 0},
            "type",
            "/a~1b~0c",
        ),
        (
            {"additionalProperties": False},
            {"extra": "sensitive-marker"},
            "additionalProperties",
            "/extra",
        ),
        ({"additionalProperties": {"type": "boolean"}}, {"extra": 0}, "type", "/extra"),
    ],
)
def test_invalid_values_are_not_coerced_and_diagnostics_are_value_free(
    schema, value, keyword, path
):
    with pytest.raises(ParameterValidationError) as error:
        validate_parameter_value(compile_parameter_schema(schema), value)
    assert error.value.keyword == keyword
    assert error.value.path == path
    assert "sensitive-marker" not in str(error.value)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "unknown"},
        {"type": []},
        {"type": ["boolean", "boolean"]},
        {"type": [False]},
        {"enum": []},
        {"enum": [1, 1.0]},
        {"enum": "values"},
        {"minimum": False},
        {"minimum": 10, "maximum": 1},
        {"maximum": "high"},
        {"minLength": -1},
        {"maxLength": True},
        {"minLength": 5, "maxLength": 2},
        {"required": "field"},
        {"required": [False]},
        {"required": ["field", "field"]},
        {"properties": []},
        {"properties": {"field": True}},
        {"items": []},
        {"additionalProperties": None},
    ],
)
def test_invalid_schema_shapes_and_constraints_fail_before_use(schema):
    with pytest.raises(ParameterValidationError, match="PARAMETER_SCHEMA_INVALID"):
        compile_parameter_schema(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.com/schema"},
        {"format": "email"},
        {"oneOf": []},
        {"properties": {"field": {"pattern": "script"}}},
        {"items": {"default": 0}},
    ],
)
def test_unregistered_keywords_and_remote_references_are_rejected(schema):
    with pytest.raises(ParameterValidationError) as error:
        compile_parameter_schema(schema)
    assert error.value.category == "PARAMETER_SCHEMA_KEYWORD_UNSUPPORTED"


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), {1: "invalid-key"}, object(), "\ud800"]
)
def test_non_json_values_and_invalid_utf8_are_rejected(value):
    with pytest.raises(ParameterValidationError, match="PARAMETER_JSON_INVALID"):
        validate_parameter_value(compile_parameter_schema({}), value)


def test_cyclic_values_are_explicitly_rejected_without_recursion_failure():
    value = []
    value.append(value)
    with pytest.raises(ParameterValidationError, match="PARAMETER_JSON_INVALID"):
        validate_parameter_value(compile_parameter_schema({}), value)


def test_compiled_schema_is_an_independent_immutable_snapshot():
    source = {
        "type": "object",
        "properties": {"field": {"type": "boolean"}},
        "additionalProperties": False,
    }
    schema = compile_parameter_schema(source)
    source["properties"]["field"]["type"] = "number"
    copy = schema.schema
    copy["properties"]["field"]["type"] = "number"
    validate_parameter_value(schema, {"field": False})
    with pytest.raises(ParameterValidationError):
        validate_parameter_value(schema, {"field": 0})


def test_json_equality_preserves_boolean_numeric_and_structural_semantics():
    assert json_values_equal(1, 1.0)
    assert not json_values_equal(False, 0)
    assert not json_values_equal(True, 1)
    assert json_values_equal({"x": [None, False, 1]}, {"x": (None, False, 1.0)})
    assert not json_values_equal({"x": False}, {"x": 0})
    assert not json_values_equal([1], [1, 2])
