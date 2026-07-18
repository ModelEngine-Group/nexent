"""Layered policy contract for deterministic context selection."""

from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from .models import ContextItemType


class AuthorityTier(str, Enum):
    """Authority of an item, ordered separately by the effective policy."""

    PLATFORM = "platform"
    TENANT = "tenant"
    AGENT = "agent"
    USER = "user"
    TOOL = "tool"
    RETRIEVED = "retrieved"
    INFERRED = "inferred"


class ContextProcessingMode(str, Enum):
    """Cross-cutting context processing pipeline selection."""

    PASSTHROUGH = "passthrough"
    SEMANTIC_COMPRESS = "semantic_compress"
    REDUCE_THEN_COMPRESS = "reduce_then_compress"


class ContextPolicy(BaseModel):
    """Immutable cross-source policy; item behavior stays on ContextItem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    processing_mode: ContextProcessingMode = ContextProcessingMode.PASSTHROUGH
    enabled_item_types: tuple[ContextItemType, ...] = tuple(ContextItemType)
    authority_order: tuple[AuthorityTier, ...] = tuple(AuthorityTier)
    resolve_conflicts: bool = True

    @field_validator("enabled_item_types")
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
            merged.update(values)
    return ContextPolicy.model_validate(merged)


def policy_fingerprint(policy: ContextPolicy) -> str:
    """Return a stable identifier for the complete effective policy."""

    encoded = json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
