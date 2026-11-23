"""Two-mode context processing policy."""

from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict


class ContextProcessingMode(str, Enum):
    """Whether this request may create compact representations."""

    PASSTHROUGH = "passthrough"
    ADAPTIVE_COMPACT = "adaptive_compact"


class ContextPolicy(BaseModel):
    """Only controls compression activation; item behavior stays on each item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    processing_mode: ContextProcessingMode = ContextProcessingMode.PASSTHROUGH


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
