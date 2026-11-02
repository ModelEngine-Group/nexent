# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled body-only extra parameter validation and JSON Pointer application."""

import json
import re
from typing import Mapping, Sequence

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, _json_copy


PROTECTED_CONNECTION_PATHS = ("/api_key", "/authorization", "/headers", "/credentials", "/base_url")

_CONTROLLED_PATHS = ("/model", "/messages", "/tools", "/tool_choice", "/stream", "/stream_options")
_MAX_BYTES, _MAX_DEPTH, _MAX_LEAVES = 64 * 1024, 16, 128


def _clone(value: object):
    try:
        copied = _json_copy(value)
        encoded = json.dumps(copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return copied, encoded
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        if isinstance(error, ParameterValidationError):
            raise
        raise ParameterValidationError("PARAMETER_JSON_INVALID") from None


def _tokens(path: object) -> tuple[str, ...]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ParameterValidationError("API_PATH_INVALID")
    parts = path[1:].split("/")
    if any(re.search(r"~(?![01])", part) for part in parts):
        raise ParameterValidationError("API_PATH_INVALID", path)
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    length = min(len(left), len(right))
    return left[:length] == right[:length]


def _leaves(value: object, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        raise ParameterValidationError("EXTRA_API_PARAMETERS_LIMIT", keyword="depth")
    if isinstance(value, dict):
        return sum(_leaves(item, depth + 1) for item in value.values()) if value else 1
    if isinstance(value, list):
        return sum(_leaves(item, depth + 1) for item in value) if value else 1
    return 1


def _array_index(token: str, size: int, path: str) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", token):
        raise ParameterValidationError("API_PATH_INVALID", path)
    # Bound before integer conversion to reject oversized index strings safely.
    if len(token) > len(str(size)) or int(token) >= size:
        raise ParameterValidationError("API_PATH_INVALID", path)
    return int(token)


def _set(body: dict, tokens: tuple[str, ...], value: object, path: str) -> None:
    current = body
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                current[token] = {}
            current = current[token]
        elif isinstance(current, list):
            current = current[_array_index(token, len(current), path)]
        else:
            raise ParameterValidationError("API_PATH_CONFLICT", path)
    last = tokens[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, list):
        current[_array_index(last, len(current), path)] = value
    else:
        raise ParameterValidationError("API_PATH_CONFLICT", path)


def apply_extra_api_parameters(
    body: Mapping[str, object],
    extras: Sequence[Mapping[str, object]],
    *,
    parameter_paths: Sequence[str] = (),
    protected_paths: Sequence[str] = (),
) -> dict:
    """Apply validated extras to a detached body, never to headers, URL or auth."""
    copied_body, _ = _clone(body)
    copied_extras, encoded = _clone(extras)
    if not isinstance(copied_body, dict) or not isinstance(copied_extras, list):
        raise ParameterValidationError("PARAMETER_JSON_INVALID")
    if len(encoded) > _MAX_BYTES:
        raise ParameterValidationError("EXTRA_API_PARAMETERS_LIMIT", keyword="bytes")
    protected = [_tokens(path) for path in (*_CONTROLLED_PATHS, *parameter_paths, *protected_paths)]
    accepted, leaf_count = [], 0
    for entry in copied_extras:
        if not isinstance(entry, dict) or set(entry) != {"path", "value"}:
            raise ParameterValidationError("EXTRA_API_PARAMETER_INVALID")
        path = entry["path"]
        tokens = _tokens(path)
        if any(_overlap(tokens, controlled) for controlled in protected):
            raise ParameterValidationError("RESERVED_API_PATH", path)
        if any(_overlap(tokens, existing) for existing, _ in accepted):
            raise ParameterValidationError("API_PATH_CONFLICT", path)
        leaf_count += _leaves(entry["value"])
        if leaf_count > _MAX_LEAVES:
            raise ParameterValidationError("EXTRA_API_PARAMETERS_LIMIT", keyword="leaves")
        accepted.append((tokens, entry))
    for tokens, entry in accepted:
        _set(copied_body, tokens, entry["value"], entry["path"])
    return copied_body



def overlay_extra_api_parameters(profile, overrides):
    """Apply historical explicit custom replacements/removals at a boundary."""
    if not isinstance(overrides, Mapping) or any(not isinstance(key, str) or not key for key in overrides):
        raise ParameterValidationError("LEGACY_CUSTOM_PARAMETERS_INVALID")
    extras = list(profile.extra_api_parameters)
    for key, value in overrides.items():
        path = "/" + key.replace("~", "~0").replace("/", "~1")
        extras = [entry for entry in extras if entry["path"] != path and not entry["path"].startswith(path + "/")]
        if value is not None:
            extras.append({"path": path, "value": value})
    apply_extra_api_parameters({}, extras,
        parameter_paths=[rule["api_binding"]["path"] for rule in profile.parameter_rules if rule.get("api_binding")],
        protected_paths=PROTECTED_CONNECTION_PATHS)
    return extras
