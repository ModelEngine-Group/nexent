"""Secret-reference helpers for Generic Benchmark configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any


ENV_REFERENCE_KEY = "$env"
REDACTED_VALUE = "[REDACTED]"
_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_NON_IDENTIFIER_PATTERN = re.compile(r"[^A-Za-z0-9]+")
_GENERIC_SECRET_NAMES = {
    "API_KEY",
    "APIKEY",
    "AUTHORIZATION",
    "COOKIE",
    "HEADERS",
    "PASSWORD",
    "SECRET",
    "TOKEN",
}


def _normalized_key(value: Any) -> str:
    return _NON_IDENTIFIER_PATTERN.sub("_", str(value).strip().lower()).strip("_")


def is_sensitive_key(key: Any) -> bool:
    """Return whether a mapping key conventionally contains a secret value."""
    normalized = _normalized_key(key)
    compact = normalized.replace("_", "")
    return (
        normalized == "headers"
        or normalized.endswith("_headers")
        or normalized == "cookie"
        or normalized.endswith("_cookie")
        or normalized.startswith("authorization")
        or compact == "apikey"
        or normalized.endswith("_api_key")
        or normalized == "password"
        or normalized.endswith("_password")
        or normalized == "secret"
        or normalized.endswith("_secret")
        or normalized == "token"
        or normalized.endswith("_token")
    )


def resolve_env_references(
    value: Any,
    *,
    environ: Mapping[str, str] | None = None,
    path: str = "$",
) -> Any:
    """Resolve strict ``{"$env": "NAME"}`` references without logging values."""
    environment = os.environ if environ is None else environ

    if isinstance(value, dict):
        if ENV_REFERENCE_KEY in value:
            if set(value) != {ENV_REFERENCE_KEY}:
                raise ValueError(
                    f"Invalid environment reference at {path}: "
                    f"{ENV_REFERENCE_KEY!r} must be the only key"
                )
            variable_name = value[ENV_REFERENCE_KEY]
            if (
                not isinstance(variable_name, str)
                or not _ENV_NAME_PATTERN.fullmatch(variable_name)
            ):
                raise ValueError(
                    f"Invalid environment variable name at {path}: "
                    "use uppercase letters, digits, and underscores"
                )
            resolved = environment.get(variable_name)
            if resolved is None or resolved == "":
                raise ValueError(
                    f"Environment variable {variable_name!r} referenced at "
                    f"{path} is not set or is empty"
                )
            return resolved
        return {
            key: resolve_env_references(
                item,
                environ=environment,
                path=f"{path}.{key}",
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            resolve_env_references(
                item,
                environ=environment,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]

    return value


def environment_name_for_secret(tool_name: str, parameter_name: str) -> str:
    """Build a stable environment variable name for an exported tool secret."""
    parameter_env_name = _normalized_key(parameter_name).upper()
    if parameter_env_name in _GENERIC_SECRET_NAMES:
        tool_env_name = _normalized_key(tool_name).upper()
        return f"{tool_env_name}_{parameter_env_name}"
    return parameter_env_name


def externalize_sensitive_values(
    value: Any,
    *,
    tool_name: str,
) -> tuple[Any, set[str]]:
    """Replace configured scalar secrets with environment references."""
    required_variables: set[str] = set()

    if isinstance(value, dict):
        if set(value) == {ENV_REFERENCE_KEY}:
            variable_name = value[ENV_REFERENCE_KEY]
            if isinstance(variable_name, str):
                required_variables.add(variable_name)
            return dict(value), required_variables

        output = {}
        for key, item in value.items():
            if is_sensitive_key(key) and item not in (None, ""):
                if isinstance(item, (str, int, float, bool)):
                    variable_name = environment_name_for_secret(
                        tool_name,
                        str(key),
                    )
                    output[key] = {ENV_REFERENCE_KEY: variable_name}
                    required_variables.add(variable_name)
                else:
                    output[key] = REDACTED_VALUE
                continue

            safe_item, nested_variables = externalize_sensitive_values(
                item,
                tool_name=tool_name,
            )
            output[key] = safe_item
            required_variables.update(nested_variables)
        return output, required_variables

    if isinstance(value, list):
        output = []
        for item in value:
            safe_item, nested_variables = externalize_sensitive_values(
                item,
                tool_name=tool_name,
            )
            output.append(safe_item)
            required_variables.update(nested_variables)
        return output, required_variables

    return value, required_variables
