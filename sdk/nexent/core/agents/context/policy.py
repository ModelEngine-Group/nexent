"""Layered policy contract for deterministic context selection."""

from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import ContextItemType


DEFAULT_POLICY_VERSION = "1.0"


class AuthorityTier(str, Enum):
    """Authority of an item, ordered separately by the effective policy."""

    PLATFORM = "platform"
    TENANT = "tenant"
    AGENT = "agent"
    USER = "user"
    TOOL = "tool"
    RETRIEVED = "retrieved"
    INFERRED = "inferred"


class ContextPolicy(BaseModel):
    """Immutable effective policy.

    The built-in policy is deliberately disabled: an unconfigured tenant or
    caller therefore preserves every Phase 4 item and its existing order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    version: str = Field(default=DEFAULT_POLICY_VERSION, min_length=1)
    enabled_item_types: tuple[ContextItemType, ...] = tuple(ContextItemType)
    required_item_types: tuple[ContextItemType, ...] = (ContextItemType.SYSTEM_PROMPT,)
    authority_order: tuple[AuthorityTier, ...] = tuple(AuthorityTier)
    type_weights: dict[ContextItemType, float] = Field(default_factory=dict)
    source_trust: dict[str, float] = Field(default_factory=dict)
    relevance_weight: float = Field(default=1.0, ge=0)
    recency_weight: float = Field(default=1.0, ge=0)
    resolve_conflicts: bool = True

    @field_validator("enabled_item_types", "required_item_types")
    @classmethod
    def _unique_item_types(cls, value: tuple[ContextItemType, ...]) -> tuple[ContextItemType, ...]:
        if len(set(value)) != len(value):
            raise ValueError("context policy item types must be unique")
        return value

    @field_validator("authority_order")
    @classmethod
    def _complete_authority_order(cls, value: tuple[AuthorityTier, ...]) -> tuple[AuthorityTier, ...]:
        if len(value) != len(set(value)) or set(value) != set(AuthorityTier):
            raise ValueError("authority_order must contain every authority tier exactly once")
        if value[0] is not AuthorityTier.PLATFORM:
            raise ValueError("platform authority must remain highest")
        return value

    @field_validator("version")
    @classmethod
    def _supported_version(cls, value: str) -> str:
        try:
            major = int(value.split(".", 1)[0])
        except ValueError as exc:
            raise ValueError("context policy version must use numeric semantic versioning") from exc
        if major != 1:
            raise ValueError(f"unsupported context policy major version: {major}")
        return value

    @field_validator("type_weights", "source_trust")
    @classmethod
    def _non_negative_weights(cls, value: dict[Any, float]) -> dict[Any, float]:
        if any(weight < 0 for weight in value.values()):
            raise ValueError("context policy weights must be non-negative")
        return value

    @model_validator(mode="after")
    def _required_types_must_be_enabled(self) -> "ContextPolicy":
        disabled = set(self.required_item_types) - set(self.enabled_item_types)
        if disabled:
            names = ", ".join(sorted(item_type.value for item_type in disabled))
            raise ValueError(f"required context item types cannot be disabled: {names}")
        return self


class PolicyLayers(BaseModel):
    """Policy layers in increasing precedence order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: Mapping[str, Any] | ContextPolicy | None = None
    tenant: Mapping[str, Any] | ContextPolicy | None = None
    agent: Mapping[str, Any] | ContextPolicy | None = None
    request: Mapping[str, Any] | ContextPolicy | None = None


def resolve_policy(layers: PolicyLayers | Mapping[str, Any] | None = None) -> ContextPolicy:
    """Merge platform → tenant → agent → request and validate the result."""

    if layers is not None and not isinstance(layers, PolicyLayers):
        layers = PolicyLayers.model_validate(layers)
    merged: dict[str, Any] = ContextPolicy().model_dump(mode="json")
    if layers is not None:
        for layer in (layers.platform, layers.tenant, layers.agent, layers.request):
            if layer is None:
                continue
            values = layer.model_dump(mode="json") if isinstance(layer, ContextPolicy) else dict(layer)
            for key, value in values.items():
                if key in {"type_weights", "source_trust"}:
                    merged[key] = {**merged.get(key, {}), **value}
                else:
                    merged[key] = value
    return ContextPolicy.model_validate(merged)


def policy_fingerprint(policy: ContextPolicy) -> str:
    """Return a stable identifier for the complete effective policy."""

    encoded = json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
