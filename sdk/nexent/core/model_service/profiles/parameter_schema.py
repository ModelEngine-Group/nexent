# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Finite parameter schema validation without evaluation or remote resolution."""

import json
import math
from dataclasses import dataclass, field
from typing import Mapping


_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "items",
        "properties",
        "required",
        "additionalProperties",
    }
)
_TYPES = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})


class ParameterValidationError(ValueError):
    """A value-free diagnostic suitable for configuration error projection."""

    def __init__(self, category: str, path: str = "", keyword: str = ""):
        self.category = category
        self.path = path
        self.keyword = keyword
        super().__init__(f"{category}: {path}: {keyword}")


@dataclass(frozen=True)
class CompiledParameterSchema:
    """Canonical immutable schema bytes; callers receive independent copies."""

    _json: bytes = field(repr=False)

    @property
    def schema(self) -> dict:
        return json.loads(self._json)


def _path(parent: str, key: object) -> str:
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _json_copy(value: object, path: str = "", ancestors: frozenset[int] = frozenset()):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
    elif isinstance(value, (Mapping, list, tuple)):
        if id(value) in ancestors:
            raise ParameterValidationError("PARAMETER_JSON_INVALID", path)
        ancestors = ancestors | {id(value)}
        if isinstance(value, Mapping):
            copied = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ParameterValidationError("PARAMETER_JSON_INVALID", path)
                copied[key] = _json_copy(item, _path(path, key), ancestors)
            return copied
        return [_json_copy(item, _path(path, index), ancestors) for index, item in enumerate(value)]
    raise ParameterValidationError("PARAMETER_JSON_INVALID", path)


def json_values_equal(left: object, right: object) -> bool:
    """JSON numeric equality never conflates booleans with numbers."""
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(json_values_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(json_values_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _check_schema(schema: object, path: str = "") -> None:
    if not isinstance(schema, dict):
        raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", path)
    for key in schema:
        if key not in _KEYWORDS:
            raise ParameterValidationError("PARAMETER_SCHEMA_KEYWORD_UNSUPPORTED", _path(path, key), key)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if (
            not types
            or any(not isinstance(kind, str) or kind not in _TYPES for kind in types)
            or len(set(types)) != len(types)
        ):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, "type"), "type")
    if "enum" in schema:
        values = schema["enum"]
        if (
            not isinstance(values, list)
            or not values
            or any(
                json_values_equal(value, previous) for index, value in enumerate(values) for previous in values[:index]
            )
        ):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, "enum"), "enum")
    for key in ("minimum", "maximum"):
        if key in schema and type(schema[key]) not in (int, float):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, key), key)
    for key in ("minLength", "maxLength"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, key), key)
    for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", path, lower)
    if "required" in schema:
        keys = schema["required"]
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, "required"), "required")
    if "items" in schema:
        _check_schema(schema["items"], _path(path, "items"))
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise ParameterValidationError("PARAMETER_SCHEMA_INVALID", _path(path, "properties"), "properties")
        for key, child in schema["properties"].items():
            _check_schema(child, _path(_path(path, "properties"), key))
    if "additionalProperties" in schema and type(schema["additionalProperties"]) is not bool:
        _check_schema(schema["additionalProperties"], _path(path, "additionalProperties"))


def compile_parameter_schema(schema: Mapping[str, object]) -> CompiledParameterSchema:
    """Reject unsupported syntax before parameter values can use this schema."""
    try:
        copied = _json_copy(schema)
        _check_schema(copied)
        encoded = json.dumps(
            copied, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (RecursionError, UnicodeError, TypeError, ValueError) as error:
        if isinstance(error, ParameterValidationError):
            raise
        raise ParameterValidationError("PARAMETER_JSON_INVALID") from None
    return CompiledParameterSchema(encoded)


def _matches(value: object, kind: str) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[kind]


def _validate(schema: dict, value: object, path: str) -> None:
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_matches(value, kind) for kind in kinds):
            raise ParameterValidationError("PARAMETER_VALUE_INVALID", path, "type")
    if "enum" in schema and not any(json_values_equal(value, option) for option in schema["enum"]):
        raise ParameterValidationError("PARAMETER_VALUE_INVALID", path, "enum")
    if "const" in schema and not json_values_equal(value, schema["const"]):
        raise ParameterValidationError("PARAMETER_VALUE_INVALID", path, "const")
    if type(value) in (int, float):
        for keyword in ("minimum", "maximum"):
            if keyword in schema and (
                (keyword == "minimum" and value < schema[keyword])
                or (keyword == "maximum" and value > schema[keyword])
            ):
                raise ParameterValidationError("PARAMETER_VALUE_INVALID", path, keyword)
    if isinstance(value, str):
        for keyword in ("minLength", "maxLength"):
            if keyword in schema and (
                (keyword == "minLength" and len(value) < schema[keyword])
                or (keyword == "maxLength" and len(value) > schema[keyword])
            ):
                raise ParameterValidationError("PARAMETER_VALUE_INVALID", path, keyword)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(schema["items"], item, _path(path, index))
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                raise ParameterValidationError("PARAMETER_VALUE_REQUIRED", _path(path, key), "required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                _validate(properties[key], item, _path(path, key))
            elif additional is False:
                raise ParameterValidationError(
                    "PARAMETER_ADDITIONAL_PROPERTY", _path(path, key), "additionalProperties"
                )
            elif isinstance(additional, dict):
                _validate(additional, item, _path(path, key))


def validate_parameter_value(schema: CompiledParameterSchema, value: object, path: str = "") -> None:
    """Validate the submitted JSON value without defaulting or coercion."""
    try:
        copied = _json_copy(value, path)
        # Validate UTF-8 serializability as well as the Python structure.
        json.dumps(copied, ensure_ascii=False, allow_nan=False).encode("utf-8")
        _validate(schema.schema, copied, path)
    except (RecursionError, UnicodeError, TypeError, ValueError) as error:
        if isinstance(error, ParameterValidationError):
            raise
        raise ParameterValidationError("PARAMETER_JSON_INVALID", path) from None
