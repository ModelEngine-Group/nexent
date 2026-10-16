"""Immutable Agent prompt template snapshots."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from ...prompts import load_prompt
from .validator import validate_agent_prompt_template


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _digest(template: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _thaw(template), sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class AgentPromptBundle:
    """A validated prompt snapshot supplied to SDK by its caller."""

    role: str
    language: str
    template: Mapping[str, Any]
    system_sections: Mapping[str, str]
    digest: str

    @classmethod
    def from_resource(
        cls, *, role: str, language: str, template_override: Mapping[str, Any] | None = None,
    ) -> "AgentPromptBundle":
        """Load a complete SDK-owned role template or validate an explicit override."""
        if role not in {"manager", "managed"}:
            raise ValueError("unsupported Agent prompt role")
        resource = "agent/agent_manager" if role == "manager" else "agent/agent_worker"
        template = template_override if template_override is not None else load_prompt(language, resource)
        return cls.from_mapping(role=role, language=language, template=template)

    @classmethod
    def from_mapping(
        cls, *, role: str, language: str, template: Mapping[str, Any],
    ) -> "AgentPromptBundle":
        validate_agent_prompt_template(
            role=role,
            language=language,
            template=template,
        )
        snapshot = _freeze(template)
        return cls(
            role=role,
            language=language,
            template=snapshot,
            system_sections=snapshot["system_sections"],
            digest=_digest(snapshot),
        )

    @classmethod
    def _from_compatibility_mapping(
        cls, *, role: str, template: Mapping[str, Any],
    ) -> "AgentPromptBundle":
        """Wrap a legacy stage-template mapping without treating it as YAML."""
        snapshot = _freeze(template)
        return cls(
            role=role,
            language="en",
            template=snapshot,
            system_sections=MappingProxyType({}),
            digest=_digest(snapshot),
        )
