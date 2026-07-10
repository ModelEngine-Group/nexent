"""Tool schema normalization helpers for framework-neutral run plans."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from pydantic import BaseModel

from .models import AgentRunPlan, ToolSpec


class ToolSchemaConfigurationError(ValueError):
    """Raised when a persisted tool schema cannot be used safely."""


class AgentRunPlanContractError(ValueError):
    """Raised when an AgentRunPlan contains framework-native runtime objects."""


DEFAULT_HIDDEN_TOOL_INPUT_NAMES = frozenset(
    {
        "observer",
        "message_observer",
        "storage_client",
        "minio_client",
        "minio_client_factory",
        "document_paths",
        "_internal_document_paths",
        "memory_config",
        "memory_user_config",
        "mem0_config",
        "tenant_credentials",
        "tenant_credential",
        "tenant_api_key",
        "authorization",
        "authorization_token",
        "access_token",
        "api_key",
        "secret",
        "secret_key",
        "headers",
        "custom_headers",
        "embedding_model",
        "rerank_model",
        "llm_model",
        "vlm_model",
        "video_model",
        "local_skills_dir",
        "tenant_id",
        "user_id",
        "agent_id",
        "version_no",
    }
)

JSON_SCHEMA_CONTAINER_KEYS = frozenset(
    {
        "$defs",
        "$id",
        "$schema",
        "additionalProperties",
        "allOf",
        "anyOf",
        "description",
        "examples",
        "oneOf",
        "properties",
        "required",
        "title",
        "type",
    }
)

FRAMEWORK_NATIVE_MODULE_PREFIXES = (
    "smolagents",
    "openjiuwen",
    "jiuwen",
    "agent_core",
)


def normalize_tool_input_schema(
    raw_inputs: str | Mapping[str, Any] | None,
    *,
    tool_name: str | None = None,
    hidden_input_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Convert legacy ToolConfig.inputs into a validated model-visible schema."""
    if raw_inputs is None:
        return {}

    if isinstance(raw_inputs, str):
        stripped = raw_inputs.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ToolSchemaConfigurationError(
                _format_tool_error(
                    tool_name,
                    f"ToolConfig.inputs contains invalid JSON: {exc.msg}.",
                )
            ) from exc
    elif isinstance(raw_inputs, Mapping):
        parsed = dict(raw_inputs)
    else:
        raise ToolSchemaConfigurationError(
            _format_tool_error(
                tool_name,
                f"ToolConfig.inputs must be a JSON object string or dict, got {type(raw_inputs).__name__}.",
            )
        )

    if not isinstance(parsed, dict):
        raise ToolSchemaConfigurationError(
            _format_tool_error(
                tool_name,
                f"ToolConfig.inputs must decode to a JSON object, got {type(parsed).__name__}.",
            )
        )

    validate_model_visible_tool_schema(
        parsed,
        tool_name=tool_name,
        hidden_input_names=hidden_input_names,
    )
    return parsed


def validate_model_visible_tool_schema(
    input_schema: Mapping[str, Any],
    *,
    tool_name: str | None = None,
    hidden_input_names: Iterable[str] | None = None,
) -> None:
    """Ensure model-visible schema does not expose system-injected parameters."""
    hidden_names = {
        name.lower()
        for name in (hidden_input_names or DEFAULT_HIDDEN_TOOL_INPUT_NAMES)
    }
    visible_names = {
        name.lower()
        for name in extract_model_visible_input_names(input_schema)
    }
    leaked_names = sorted(visible_names & hidden_names)
    if leaked_names:
        raise ToolSchemaConfigurationError(
            _format_tool_error(
                tool_name,
                "Tool input schema exposes system-injected parameters: "
                + ", ".join(leaked_names)
                + ". Move them to metadata or injected_params.",
            )
        )


def extract_model_visible_input_names(input_schema: Mapping[str, Any]) -> set[str]:
    """Return the top-level model-visible input names from a legacy or JSON schema."""
    properties = input_schema.get("properties")
    if isinstance(properties, Mapping):
        return {str(name) for name in properties}

    return {
        str(name)
        for name in input_schema
        if str(name) not in JSON_SCHEMA_CONTAINER_KEYS
    }


def tool_spec_from_legacy_tool_config(
    tool_config: Any,
    *,
    hidden_input_names: Iterable[str] | None = None,
) -> ToolSpec:
    """Create a neutral ToolSpec from the existing SDK ToolConfig shape."""
    class_name = getattr(tool_config, "class_name", None)
    name = getattr(tool_config, "name", None) or class_name
    if not name:
        raise ToolSchemaConfigurationError("ToolConfig.name or ToolConfig.class_name is required.")

    raw_inputs = getattr(tool_config, "inputs", None)
    input_schema = normalize_tool_input_schema(
        raw_inputs,
        tool_name=str(name),
        hidden_input_names=hidden_input_names,
    )

    return ToolSpec(
        name=str(name),
        description=getattr(tool_config, "description", None) or "",
        input_schema=input_schema,
        raw_inputs=raw_inputs if isinstance(raw_inputs, str) else None,
        output_type=getattr(tool_config, "output_type", None) or "any",
        source=getattr(tool_config, "source", None) or "local",
        class_name=class_name,
        usage=getattr(tool_config, "usage", None),
        params=_dict_or_empty(getattr(tool_config, "params", None), field_name="params", tool_name=str(name)),
        metadata=_dict_or_empty(
            getattr(tool_config, "metadata", None),
            field_name="metadata",
            tool_name=str(name),
        ),
    )


def assert_agent_run_plan_framework_neutral(plan: AgentRunPlan) -> None:
    """Fail if a run plan carries smolagents/openjiuwen native objects."""
    violations = list(_find_framework_native_values(plan))
    if violations:
        raise AgentRunPlanContractError(
            "AgentRunPlan contains framework-native objects: " + "; ".join(violations)
        )


def _dict_or_empty(value: Any, *, field_name: str, tool_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolSchemaConfigurationError(
            _format_tool_error(
                tool_name,
                f"ToolConfig.{field_name} must be a dict when provided, got {type(value).__name__}.",
            )
        )
    return value


def _format_tool_error(tool_name: str | None, message: str) -> str:
    if tool_name:
        return f"Invalid tool schema for '{tool_name}': {message}"
    return message


def _find_framework_native_values(value: Any) -> Iterator[str]:
    visited: set[int] = set()
    yield from _walk_framework_native_values(value, "$", visited)


def _walk_framework_native_values(value: Any, path: str, visited: set[int]) -> Iterator[str]:
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return

    value_id = id(value)
    if value_id in visited:
        return
    visited.add(value_id)

    module_name = value.__class__.__module__
    if module_name.startswith(FRAMEWORK_NATIVE_MODULE_PREFIXES):
        yield f"{path} -> {module_name}.{value.__class__.__qualname__}"
        return

    if isinstance(value, BaseModel):
        for field_name in value.__class__.model_fields:
            yield from _walk_framework_native_values(
                getattr(value, field_name),
                f"{path}.{field_name}",
                visited,
            )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk_framework_native_values(child, f"{path}[{key!r}]", visited)
        return

    if isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            yield from _walk_framework_native_values(child, f"{path}[{index}]", visited)

