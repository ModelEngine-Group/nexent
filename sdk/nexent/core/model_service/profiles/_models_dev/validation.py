# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict selected authored schemas pinned to models.dev e69e184.

Submission-only checks of consumed facts; reference metadata is not validated.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, SourceReadError


_REFERENCE_FIELDS = frozenset({"description", "family", "knowledge", "release_date", "last_updated",
    "license", "links", "weights", "benchmarks", "cost", "status", "env", "npm", "doc"})


@dataclass(frozen=True)
class ObjectSchema:
    fields: Mapping[str, object]
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArraySchema:
    item: object


def _error(document: SourceDocument, path: str, category: str = "SOURCE_VALUE_INVALID") -> SourceReadError:
    error = SourceReadError(category, document.file_path, document.kind)
    error.source_path = path
    error.rule_id = "models_dev_authored_v1"
    return error


def _validate(value: object, schema: object, document: SourceDocument, path: str, partial: bool = False) -> None:
    if isinstance(schema, ObjectSchema):
        if not isinstance(value, Mapping):
            raise _error(document, path)
        for key, item in value.items():
            field_path = f"{path}.{key}" if path else key
            if not path and key in _REFERENCE_FIELDS:
                continue
            if key not in schema.fields:
                raise _error(document, field_path, "SOURCE_FIELD_UNHANDLED")
            _validate(item, schema.fields[key], document, field_path, partial)
        if not partial:
            for key in schema.required:
                if key not in value:
                    raise _error(document, f"{path}.{key}" if path else key, "SOURCE_FIELD_REQUIRED")
        return
    if isinstance(schema, ArraySchema):
        if not isinstance(value, (list, tuple)):
            raise _error(document, path)
        for index, item in enumerate(value):
            _validate(item, schema.item, document, f"{path}[{index}]", partial)
        return
    valid = False
    if isinstance(schema, frozenset):
        valid = isinstance(value, str) and value in schema
    elif schema == "boolean":
        valid = type(value) is bool
    elif schema == "string":
        valid = isinstance(value, str)
    elif schema == "nonempty":
        valid = isinstance(value, str) and len(value) > 0
    elif schema in ("number", "nonnegative", "budget_min", "tokens"):
        valid = type(value) is int or (type(value) is float and math.isfinite(value))
        if valid and schema != "number":
            valid = value >= (-1 if schema == "budget_min" else 0)
        if valid and schema in ("tokens", "budget_min"):
            valid = type(value) is int
    elif schema == "score":
        valid = (type(value) is int or (type(value) is float and math.isfinite(value))) or (
            isinstance(value, str) and bool(value)
        )
    elif schema == "interleaved":
        if value is True:
            return
        _validate(
            value,
            ObjectSchema({"field": frozenset({"reasoning_content", "reasoning_details"})}, ("field",)),
            document,
            path,
            partial,
        )
        return
    elif schema == "reasoning_option":
        if not isinstance(value, Mapping) or value.get("type") not in ("toggle", "effort", "budget_tokens"):
            raise _error(document, f"{path}.type")
        mode = value["type"]
        fields = {"type": frozenset({mode})}
        required = ("type",)
        if mode == "effort":
            fields["values"] = ArraySchema(
                frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "default", "null"})
            )
            required += ("values",)
        if mode == "budget_tokens":
            fields.update(min="budget_min", max="tokens")
        _validate(value, ObjectSchema(fields, required), document, path, partial)
        if mode == "budget_tokens" and "min" in value and "max" in value and value["min"] > value["max"]:
            raise _error(document, f"{path}.min", "SOURCE_CONSTRAINT_INVALID")
        return
    if not valid:
        raise _error(document, path)


_MODALITIES = ObjectSchema(
    {
        "input": ArraySchema(frozenset({"text", "audio", "image", "video", "pdf"})),
        "output": ArraySchema(frozenset({"text", "audio", "image", "video", "pdf"})),
    },
    ("input", "output"),
)
_LIMIT = ObjectSchema({"context": "tokens", "input": "tokens", "output": "tokens"}, ("context",))
_COMMON = {
    "name": "nonempty",
    **dict.fromkeys(
        ("attachment", "reasoning", "tool_call", "structured_output", "temperature", "open_weights"), "boolean"
    ),
    "modalities": _MODALITIES,
    "limit": _LIMIT,
}
_MODEL = ObjectSchema(
    {
        **_COMMON,
    },
    ("name",),
)
_PROVIDER_MODEL = ObjectSchema(
    {
        **_COMMON,
        "limit": ObjectSchema(_LIMIT.fields, ("context", "output")),
        "reasoning_options": ArraySchema("reasoning_option"),
        "interleaved": "interleaved",
    },
    (
        "name",
        "attachment",
        "reasoning",
        "tool_call",
        "modalities",
        "open_weights",
        "limit",
    ),
)
_PROVIDER = ObjectSchema(
    {"name": "nonempty", "env": ArraySchema("string"), "npm": "nonempty", "api": "string", "doc": "nonempty"},
    ("name",),
)


def validate_source_document(document: SourceDocument, *, effective: bool = False) -> None:
    """Validate authored overrides separately from complete inherited results.

    Valid upstream fields outside the selected subset fail explicitly until their
    source dispositions are registered. They are never silently ignored.
    """
    schema = {"model": _MODEL, "provider": _PROVIDER, "provider_model": _PROVIDER_MODEL}.get(document.kind)
    if schema is None:
        raise _error(document, "", "SOURCE_MODEL_KIND_INVALID")
    partial = document.kind == "provider_model" and "base_model" in document.data and not effective
    if partial:
        schema = ObjectSchema(
            {**schema.fields, "base_model": "nonempty", "base_model_omit": ArraySchema("nonempty")}, ("base_model",)
        )
    _validate(document.data, schema, document, "", partial)
    if document.kind == "provider_model" and not partial:
        reasoning = document.data["reasoning"]
        options = "reasoning_options" in document.data
        if (reasoning and not options) or (not reasoning and options):
            raise _error(document, "reasoning_options", "SOURCE_CONSTRAINT_INVALID")
