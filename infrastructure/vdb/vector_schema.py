# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted vector schema and neutral filter compilation; no model or business I/O."""

import json
import math
import re
from dataclasses import dataclass

from nexent.storage.errors import CapabilityUnsupported, InvalidInput
from nexent.storage.models import Comparison, Junction

from infrastructure.storage.catalog import FieldDefinition


@dataclass(frozen=True)
class VectorBinding:
    collection: str
    index: str
    dimensions: int | None
    fields: tuple[FieldDefinition, ...]
    text_field: str = "content"
    metric: str = "cosine"
    writable: bool = False
    additional_text_fields: tuple[str, ...] = ()
    owns_collection: bool = False

    def __post_init__(self):
        object.__setattr__(self, "fields", tuple(self.fields))
        if not isinstance(self.additional_text_fields, (tuple, list)):
            raise InvalidInput()
        object.__setattr__(self, "additional_text_fields", tuple(self.additional_text_fields))
        names = [field.name for field in self.fields]
        if (
            type(self.writable) is not bool
            or type(self.owns_collection) is not bool
            or not self.collection
            or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", self.index)
            or self.dimensions is not None and (
                type(self.dimensions) is not int or self.dimensions < 1
            )
            or len(set(names)) != len(names)
            or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) for name in names)
            or self.text_field not in names
        ):
            raise InvalidInput()
        if self.metric != "cosine":
            raise CapabilityUnsupported()
        if self.schema[self.text_field].kind != "string":
            raise InvalidInput()
        if (len(set(self.additional_text_fields)) != len(self.additional_text_fields)
            or self.text_field in self.additional_text_fields
            or any(name not in self.schema or self.schema[name].kind != "string" for name in self.additional_text_fields)):
            raise InvalidInput()

    @property
    def schema(self):
        return {field.name: field for field in self.fields}

    def mapping(self):
        if self.dimensions is None:
            raise CapabilityUnsupported()
        kinds = {
            "string": "keyword",
            "integer": "long",
            "number": "double",
            "boolean": "boolean",
        }
        payload = {}
        for field in self.fields:
            if field.kind in {"object", "array"}:
                payload[field.name] = {"type": "object", "enabled": False}
            else:
                payload[field.name] = {
                    "type": "text"
                    if field.name in (self.text_field, *self.additional_text_fields)
                    else kinds[field.kind]
                }
        return {
            "dynamic": "strict",
            "properties": {
                "_si_tenant": {"type": "keyword"},
                "_si_key": {"type": "keyword"},
                "_si_collection": {"type": "keyword"},
                "_si_generation": {"type": "keyword"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": self.dimensions,
                    "index": True,
                    "similarity": self.metric,
                },
                "payload": {
                    "type": "object",
                    "dynamic": "strict",
                    "properties": payload,
                },
            },
        }


def matches_mapping(expected, actual):
    if not isinstance(actual, dict):
        return False
    if expected.get("type") == "object" and "type" not in actual and "properties" in actual:
        actual = {"type": "object", **actual}
    return isinstance(actual, dict) and all(
        key in actual
        and (
            matches_mapping(value, actual[key])
            if isinstance(value, dict)
            else value == actual[key]
        )
        for key, value in expected.items()
    )


def validate_value(field, value):
    kinds = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    if value is None:
        if field.nullable:
            return
        raise InvalidInput()
    if (
        not isinstance(value, kinds[field.kind])
        or isinstance(value, bool)
        and field.kind in {"integer", "number"}
        or isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise InvalidInput()


def payload(binding, values, *, partial=False):
    if not isinstance(values, dict) or not set(values) <= set(binding.schema):
        raise InvalidInput()
    for field in binding.fields:
        if field.name in values:
            validate_value(field, values[field.name])
        elif not partial and not field.nullable:
            raise InvalidInput()
    try:
        return json.loads(json.dumps(values, allow_nan=False))
    except (TypeError, ValueError):
        raise InvalidInput() from None


def vector(binding, values):
    if (
        not isinstance(values, (list, tuple))
        or len(values) != binding.dimensions
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in values
        )
        or not any(values)
    ):
        raise InvalidInput()
    return tuple(float(v) for v in values)


def predicate(binding, expression, depth=0, budget=None):
    budget = [64] if budget is None else budget
    budget[0] -= 1
    if depth > 8 or budget[0] < 0:
        raise InvalidInput()
    if isinstance(expression, Junction):
        if expression.operator not in {"and", "or"} or not expression.terms:
            raise InvalidInput()
        terms = [
            predicate(binding, child, depth + 1, budget) for child in expression.terms
        ]
        return (
            {"bool": {"filter": terms}}
            if expression.operator == "and"
            else {"bool": {"should": terms, "minimum_should_match": 1}}
        )
    if not isinstance(expression, Comparison) or expression.field not in binding.schema:
        raise InvalidInput()
    field = binding.schema[expression.field]
    if field.kind in {"object", "array"} or expression.field == binding.text_field:
        raise CapabilityUnsupported()
    name, op, value = "payload." + field.name, expression.operator, expression.value
    if op == "is_null":
        if type(value) is not bool:
            raise InvalidInput()
        return (
            {"bool": {"must_not": [{"exists": {"field": name}}]}}
            if value
            else {"exists": {"field": name}}
        )
    if op == "in":
        if not isinstance(value, list) or not 1 <= len(value) <= 1000:
            raise InvalidInput()
        for item in value:
            validate_value(field, item)
        if None in value:
            raise CapabilityUnsupported()
        return {"terms": {name: value}}
    validate_value(field, value)
    if value is None and op in {"eq", "ne"}:
        return predicate(
            binding, Comparison(field.name, "is_null", op == "eq"), depth + 1, budget
        )
    if op == "eq":
        return {"term": {name: value}}
    if op == "ne":
        return {
            "bool": {
                "filter": [{"exists": {"field": name}}],
                "must_not": [{"term": {name: value}}],
            }
        }
    if op in {"lt", "lte", "gt", "gte"} and value is not None:
        return {"range": {name: {op: value}}}
    raise InvalidInput()
