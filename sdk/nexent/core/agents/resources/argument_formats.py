# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deterministic representations of public MCP arguments approved for one agent binding."""
import re
from datetime import date
from functools import wraps
from inspect import iscoroutinefunction

from nexent.core.agents.resources.tool_user_context import USER_CONTEXT_FIELDS


def format_rule(schema):
    """Infer a single supported representation from the registered property schema."""
    if not isinstance(schema, dict) or schema.get("type") != "string":
        raise ValueError("A public string argument with a declared format or enum is required")
    choices = schema.get("enum")
    if choices is not None:
        if (schema.get("format") or not isinstance(choices, list) or not 1 <= len(choices) <= 128
                or not all(isinstance(value, str) and 0 < len(value) <= 256 for value in choices)
                or len({value.strip().casefold() for value in choices}) != len(choices)):
            raise ValueError("Ambiguous or unsupported MCP enumeration")
        return {"kind": "enum", "values": list(choices)}
    if schema.get("format") == "date":
        return {"kind": "iso_date"}
    raise ValueError("No supported representation in the registered MCP schema")


def supported_public_formats(properties):
    rules = {}
    if not isinstance(properties, dict):
        return rules
    for field, schema in properties.items():
        if field not in USER_CONTEXT_FIELDS:
            try:
                rules[field] = format_rule(schema)
            except ValueError:
                continue
    return rules


def validate_live_formats(formats, live):
    if any(live.get(field) != rule for field, rule in formats.items()):
        raise ValueError("The live MCP tool no longer declares the tested argument format")


def formatted_value(rule, value):
    if not isinstance(value, str):
        raise ValueError("A mapped MCP argument requires a single string value")
    if rule["kind"] == "iso_date":
        match = re.fullmatch(r"([0-9]{4})([-/]?)([0-9]{2})\2([0-9]{2})", value)
        if not match:
            raise ValueError("The date requires an unambiguous year, month and day")
        return date(int(match[1]), int(match[3]), int(match[4])).isoformat()
    if rule["kind"] == "enum":
        matches = [item for item in rule["values"] if item.strip().casefold() == value.strip().casefold()]
        if len(matches) == 1:
            return matches[0]
    raise ValueError("The supplied value has no unique representation")


def format_arguments(values, formats):
    updated = dict(values)
    for field, rule in formats.items():
        if field in USER_CONTEXT_FIELDS:
            raise ValueError("Caller identity fields cannot be mapped")
        if field in values:
            updated[field] = formatted_value(rule, values[field])
    return updated


def bind_argument_formats(tool, formats):
    if not formats:
        return tool
    if not set(formats).issubset(tool.inputs) or set(formats).intersection(USER_CONTEXT_FIELDS):
        raise ValueError("A mapped argument is absent from the public MCP schema")
    validate_live_formats(formats, getattr(tool, "_nexent_mcp_formats", {}))
    names = list(tool.inputs)
    forward = tool.forward

    def mapped(args, kwargs):
        if len(args) == 1 and isinstance(args[0], dict) and not kwargs:
            return (format_arguments(args[0], formats),), {}
        if len(args) > len(names) or set(names[:len(args)]).intersection(kwargs):
            raise TypeError("Conflicting MCP argument positions")
        return (), format_arguments({**dict(zip(names, args)), **kwargs}, formats)

    @wraps(forward)
    def sync_forward(*args, **kwargs):
        args, kwargs = mapped(args, kwargs)
        return forward(*args, **kwargs)

    @wraps(forward)
    async def async_forward(*args, **kwargs):
        args, kwargs = mapped(args, kwargs)
        return await forward(*args, **kwargs)

    tool.forward = async_forward if iscoroutinefunction(forward) else sync_forward
    return tool
