"""SDK Tool Registry filter for versioned, run-local policy snapshots."""

import json
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class EffectivePromptTools:
    tools: Mapping[str, Any]
    execution_tools: Mapping[str, Any]
    audit: Mapping[str, Any]


@dataclass(frozen=True)
class PromptToolPolicySnapshot:
    """Run-local values supplied by Management through Runtime."""

    enabled: frozenset[str]
    allowed: frozenset[str]
    system_default_hidden: frozenset[str]
    policy_version: str
    tool_schema_version: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]):
        if not isinstance(values, Mapping):
            raise ValueError("Agent prompt tool policy snapshot is invalid")
        for key in ("policy_version", "tool_schema_version"):
            if not isinstance(values.get(key), str) or not values[key].strip():
                raise ValueError(f"Agent prompt tool policy {key} is missing")
        collections = {}
        for key in ("enabled", "allowed", "system_default_hidden"):
            raw = values.get(key, ())
            if not isinstance(raw, (list, tuple, set, frozenset)) or any(
                not isinstance(name, str) or not name for name in raw
            ):
                raise ValueError(f"Agent prompt tool policy {key} is invalid")
            collections[key] = frozenset(raw)
        return cls(**collections, policy_version=values["policy_version"], tool_schema_version=values["tool_schema_version"])


def filter_effective_prompt_tools(
    registry: Mapping[str, Any], *, enabled: set[str], allowed: set[str],
    policy_version: str, tool_schema_version: str,
    system_default_hidden: set[str] | None = None,
) -> EffectivePromptTools:
    """Select prompt-visible tools after policy intersection and schema checking."""
    hidden = system_default_hidden or set()
    def matching_schema(value: Any) -> bool:
        if isinstance(value, Mapping):
            return value.get("schema_version", tool_schema_version) == tool_schema_version
        metadata = getattr(value, "metadata", None) or {}
        return metadata.get("schema_version", tool_schema_version) == tool_schema_version

    executable = {
        name: value for name, value in registry.items()
        if name in ((enabled & allowed) | hidden) and matching_schema(value)
    }
    visible = {
        name: value for name, value in executable.items() if name not in hidden
    }
    names = tuple(sorted(visible))
    def schema_digest_fields(value: Any) -> dict[str, Any]:
        fields = {
            field: value.get(field) if isinstance(value, Mapping) else getattr(value, field, None)
            for field in ("description", "inputs", "output_type", "schema_version")
        }
        if fields["schema_version"] is None and not isinstance(value, Mapping):
            fields["schema_version"] = (getattr(value, "metadata", None) or {}).get("schema_version")
        return fields

    payload = json.dumps(
        {name: schema_digest_fields(value) for name, value in sorted(visible.items())},
        sort_keys=True, default=str,
    )
    digest = sha256(payload.encode()).hexdigest()
    return EffectivePromptTools(
        tools=MappingProxyType(visible),
        execution_tools=MappingProxyType(executable),
        audit=MappingProxyType({
            "registry_hash": digest, "policy_version": policy_version,
            "tool_schema_version": tool_schema_version, "visible_tools": names,
        }),
    )
