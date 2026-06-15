from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("capacity_resolver")


RESOLVER_VERSION = "1.0.0"
FINGERPRINT_SCHEMA_VERSION = 1


CountingMode = Literal["exact", "estimated"]
WindowShape = Literal["combined", "separate"]
CapacitySource = Literal[
    "operator", "profile", "provider_candidate", "legacy", "unknown"
]
ReasoningWindowBehavior = Literal["none", "reserved", "unknown"]
ProviderOverheadBehavior = Literal["negligible", "bounded", "unknown"]
PromptCacheCapability = Literal["none", "supported", "unknown"]


ProfileKey = Tuple[str, str]


class CapabilityProfile(BaseModel):
    """One row in the approved provider/model capability catalog.

    Identity rules and completeness criteria are defined in
    `doc/working/context-management-workstreams/W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md`.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(description="Provider identifier (e.g. 'openai', 'dashscope', 'silicon')")
    model_name: str = Field(description="Model name as used by the provider API")
    capability_profile_version: str = Field(
        description="Per-entry version, e.g. 'openai/gpt-4o@1'"
    )

    window_shape: WindowShape
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None

    tokenizer_family: Optional[str] = Field(
        default=None,
        description=(
            "Identifier resolved via `tokenizer_registry.resolve`. None forces "
            "counting_mode='estimated'."
        ),
    )
    reasoning_window_behavior: ReasoningWindowBehavior = "unknown"
    provider_overhead_behavior: ProviderOverheadBehavior = "unknown"
    prompt_cache: PromptCacheCapability = "unknown"


class ModelCapacitySnapshot(BaseModel):
    """Immutable per-request capacity resolution result.

    Consumed unchanged by W2 (safe input budget), W3 (final fit), W16 (cache
    assembly), monitoring, and provider dispatch. Fingerprint is recomputed from
    the contract by trusted dispatch to detect tampering or stale snapshots.
    """

    model_config = ConfigDict(frozen=True)

    model_record_id: Optional[int] = None
    provider: str
    model_name: str

    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None

    requested_output_tokens: int
    provider_input_limit_tokens: int

    tokenizer_family: Optional[str] = None
    counting_mode: CountingMode

    unknown_capabilities: List[str] = Field(default_factory=list)
    field_sources: Mapping[str, CapacitySource] = Field(default_factory=dict)

    capability_profile_version: Optional[str] = None
    resolver_version: str = RESOLVER_VERSION

    warnings: List[str] = Field(default_factory=list)
    fingerprint: str


class ResolverError(Exception):
    """Base class for capacity resolution failures.

    Concrete typed failures (see ADR Decision 1 / W1 spec):
      - InvalidCapacityConfiguration
      - ProviderCapabilityUnknown
      - UncertaintyReserveBasisUnknown
      - RequestedOutputExceedsCap
      - ProviderMetadataInvalid
    """


class InvalidCapacityConfiguration(ResolverError):
    pass


class ProviderCapabilityUnknown(ResolverError):
    pass


class UncertaintyReserveBasisUnknown(ResolverError):
    pass


class RequestedOutputExceedsCap(ResolverError):
    pass


class ProviderMetadataInvalid(ResolverError):
    pass


def compute_fingerprint(
    *,
    resolver_version: str,
    provider: str,
    model_name: str,
    context_window_tokens: Optional[int],
    max_input_tokens: Optional[int],
    max_output_tokens: Optional[int],
    default_output_reserve_tokens: Optional[int],
    requested_output_tokens: int,
    provider_input_limit_tokens: int,
    tokenizer_family: Optional[str],
    counting_mode: CountingMode,
    capability_profile_version: Optional[str],
    unknown_capabilities: Sequence[str],
    field_sources: Mapping[str, str],
) -> str:
    """Deterministic 128-bit fingerprint of the resolved capacity contract.

    Algorithm is fixed by W1 ADR Decision 3: canonical JSON over the field set
    below, SHA-256, hex-encoded, truncated to 32 chars. Any change to participating
    fields or serialization requires bumping FINGERPRINT_SCHEMA_VERSION.
    """
    payload: dict[str, Any] = {
        "v": FINGERPRINT_SCHEMA_VERSION,
        "resolver_version": resolver_version,
        "provider": provider,
        "model_name": model_name,
        "context_window_tokens": context_window_tokens,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "default_output_reserve_tokens": default_output_reserve_tokens,
        "requested_output_tokens": requested_output_tokens,
        "provider_input_limit_tokens": provider_input_limit_tokens,
        "tokenizer_family": tokenizer_family,
        "counting_mode": counting_mode,
        "capability_profile_version": capability_profile_version,
        "unknown_capabilities": sorted(unknown_capabilities),
        "field_sources": dict(sorted(field_sources.items())),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def resolve_capacity(
    *,
    model_id: str,
    provider: str,
    operator_overrides: Optional[Mapping[str, Any]] = None,
    requested_output_tokens: Optional[int] = None,
    capability_profiles: Mapping[ProfileKey, CapabilityProfile],
) -> ModelCapacitySnapshot:
    """Resolve capacity for one model request.

    Skeleton only; the full resolver is implemented in a follow-up PR.
    Resolution precedence (per W1 spec): operator override > approved profile >
    provider discovery (candidate) > unknown.
    """
    raise NotImplementedError(
        "ModelCapacityResolver.resolve_capacity is implemented in the W1 follow-up PR."
    )
