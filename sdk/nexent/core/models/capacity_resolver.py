from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("capacity_resolver")


RESOLVER_VERSION = "1.0.0"
FINGERPRINT_SCHEMA_VERSION = 1


CountingMode = Literal["exact", "estimated"]
WindowShape = Literal["combined", "separate"]
CapacitySource = Literal[
    "operator", "profile", "provider_candidate", "legacy", "default", "unknown"
]
ReasoningWindowBehavior = Literal["none", "reserved", "unknown"]
ProviderOverheadBehavior = Literal["negligible", "bounded", "unknown"]
PromptCacheCapability = Literal["none", "supported", "unknown"]
ProfileConfidence = Literal["high", "medium", "low", "unknown"]


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

    # P1 catalog-governance declarations. They intentionally default to an
    # incomplete/suggestion-only state so old catalog rows cannot silently be
    # promoted to verified automatic facts during rollout.
    aliases: Tuple[str, ...] = ()
    exclusions: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()
    verified_at: Optional[str] = None
    shared_context: Optional[bool] = None
    independent_input: Optional[bool] = None
    max_output: Optional[int] = None
    reasoning_behavior: Optional[ReasoningWindowBehavior] = None
    overhead_behavior: Optional[ProviderOverheadBehavior] = None
    confidence: ProfileConfidence = "unknown"

    def automatic_validation_errors(self) -> Tuple[str, ...]:
        """Return fail-closed reasons preventing automatic catalog use."""
        errors: list[str] = []
        if not self.aliases:
            errors.append("aliases_missing")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            errors.append("evidence_missing")
        if not self.verified_at:
            errors.append("verified_at_missing")
        if self.shared_context is None:
            errors.append("shared_context_missing")
        if self.independent_input is None:
            errors.append("independent_input_missing")
        if self.max_output is None or self.max_output <= 0:
            errors.append("max_output_missing")
        elif self.max_output_tokens is not None and self.max_output != self.max_output_tokens:
            errors.append("max_output_conflict")
        if self.reasoning_behavior is None:
            errors.append("reasoning_behavior_missing")
        if self.overhead_behavior is None:
            errors.append("overhead_behavior_missing")
        if self.confidence != "high":
            errors.append("confidence_not_high")
        if self.shared_context is True and self.window_shape != "combined":
            errors.append("shared_context_conflict")
        if self.independent_input is True and self.max_input_tokens is None:
            errors.append("independent_input_limit_missing")
        return tuple(errors)

    @property
    def auto_applicable(self) -> bool:
        return not self.automatic_validation_errors()


def validate_capability_catalog(
    catalog: Mapping[ProfileKey, CapabilityProfile],
) -> Mapping[ProfileKey, Tuple[str, ...]]:
    """Validate catalog identity and automatic-use declarations.

    Incomplete legacy rows are returned with reasons and remain
    suggestion-only. A row that claims high confidence fails closed because a
    verified label without complete evidence is a catalog authoring error.
    """
    diagnostics: dict[ProfileKey, Tuple[str, ...]] = {}
    for key, profile in catalog.items():
        if key != (profile.provider, profile.model_name):
            raise ValueError(f"catalog_key_mismatch:{key!r}")
        reasons = profile.automatic_validation_errors()
        if profile.confidence == "high" and reasons:
            raise ValueError(
                f"incomplete_verified_profile:{profile.capability_profile_version}:"
                f"{','.join(reasons)}"
            )
        diagnostics[key] = reasons
    return diagnostics


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


_OVERRIDABLE_FIELDS = (
    "context_window_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "default_output_reserve_tokens",
    "tokenizer_family",
)

# Last-resort fallback when neither the agent nor the model record sets a
# requested_output_tokens / default_output_reserve_tokens. 1024 was too small
# in practice: tool-using agents often write multi-hundred-token JSON tool
# calls plus a few hundred tokens of thought per step, and 1024 produced
# mid-JSON truncation that surfaced to users as "tool failed" instead of a
# capacity-config issue. 4096 covers the median single-turn output reliably
# without overshooting tiny-output models — those still get caught by the
# RequestedOutputExceedsCap check (capacity_resolver line 276-283 and
# the agent-edit form rule).
_DEFAULT_REQUESTED_OUTPUT_TOKENS = 4096


def derive_output_protection_tokens(
    *, context_window_tokens: Optional[int], max_output_tokens: Optional[int]
) -> int:
    """Derive context-management headroom without constraining completion output."""
    if max_output_tokens is None or max_output_tokens <= 0:
        raise ProviderCapabilityUnknown("max_output_tokens is required")
    proportional = (
        math.ceil(context_window_tokens * 0.10)
        if context_window_tokens is not None
        else _DEFAULT_REQUESTED_OUTPUT_TOKENS
    )
    return min(max_output_tokens, max(_DEFAULT_REQUESTED_OUTPUT_TOKENS, proportional))


def resolve_capacity(
    *,
    model_id: str,
    provider: str,
    operator_overrides: Optional[Mapping[str, Any]] = None,
    requested_output_tokens: Optional[int] = None,
    capability_profiles: Mapping[ProfileKey, CapabilityProfile],
) -> ModelCapacitySnapshot:
    """Resolve capacity for one model request.

    Precedence per W1 spec: operator override > approved profile > unknown.
    Production dispatch requires known hard capacity; otherwise
    `ProviderCapabilityUnknown` is raised. Provider-discovery candidate metadata
    is not consulted by this implementation — it is recorded by upstream provider
    adapters and surfaced only after operators promote it into an approved
    profile.
    """
    # Lazy import to avoid a static cycle (tokenizer_registry imports CountingMode).
    from . import tokenizer_registry as _tokenizer_registry

    overrides = dict(operator_overrides) if operator_overrides else {}
    profile = capability_profiles.get((provider, model_id))

    field_sources: dict[str, CapacitySource] = {}

    def _pick(field: str) -> Any:
        value = overrides.get(field)
        if value is not None:
            field_sources[field] = "operator"
            return value
        if profile is not None:
            profile_value = getattr(profile, field)
            if profile_value is not None:
                field_sources[field] = "profile"
                return profile_value
        field_sources[field] = "unknown"
        return None

    context_window_tokens = _pick("context_window_tokens")
    max_input_tokens = _pick("max_input_tokens")
    max_output_tokens = _pick("max_output_tokens")
    default_output_reserve_tokens = _pick("default_output_reserve_tokens")
    tokenizer_family = _pick("tokenizer_family")
    capability_profile_version = (
        profile.capability_profile_version if profile is not None else None
    )

    if context_window_tokens is None and max_input_tokens is None:
        raise ProviderCapabilityUnknown(
            f"No known hard capacity for ({provider!r}, {model_id!r}); "
            f"set context_window_tokens or max_input_tokens via operator override "
            f"or add a capability profile entry."
        )

    for name, value in (
        ("context_window_tokens", context_window_tokens),
        ("max_input_tokens", max_input_tokens),
        ("max_output_tokens", max_output_tokens),
        ("default_output_reserve_tokens", default_output_reserve_tokens),
    ):
        if value is not None and value <= 0:
            raise InvalidCapacityConfiguration(
                f"{name} must be a positive integer, got {value}"
            )

    if (
        max_output_tokens is not None
        and context_window_tokens is not None
        and max_output_tokens > context_window_tokens
    ):
        raise InvalidCapacityConfiguration(
            f"max_output_tokens ({max_output_tokens}) exceeds context_window_tokens "
            f"({context_window_tokens})"
        )

    if (
        max_input_tokens is not None
        and context_window_tokens is not None
        and max_input_tokens > context_window_tokens
    ):
        raise InvalidCapacityConfiguration(
            f"max_input_tokens ({max_input_tokens}) exceeds context_window_tokens "
            f"({context_window_tokens}); operators who fill an input cap above the "
            f"window will be silently clipped by the derived provider_input_limit, "
            f"so the override never takes effect"
        )

    # Legacy model/Agent/request reserve values are intentionally ignored.
    # Input is observed and this automatically derived value only decides when
    # context-management actions should run. The provider wire output cap is
    # always max_output_tokens.
    output_protection_tokens = derive_output_protection_tokens(
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
    )
    if output_protection_tokens <= 0:
        raise InvalidCapacityConfiguration(
            f"requested_output_tokens must be positive, got {output_protection_tokens}"
        )
    derived_limits: list[int] = []
    if max_input_tokens is not None:
        derived_limits.append(max_input_tokens)
    if context_window_tokens is not None:
        derived_limits.append(context_window_tokens - output_protection_tokens)
    provider_input_limit_tokens = min(derived_limits)
    if provider_input_limit_tokens <= 0:
        raise InvalidCapacityConfiguration(
            f"derived provider_input_limit_tokens is non-positive: "
            f"{provider_input_limit_tokens}"
        )

    _, counting_mode = _tokenizer_registry.resolve(tokenizer_family)

    unknown_capabilities: list[str] = []
    if profile is None:
        unknown_capabilities.append("capability_profile_missing")
    else:
        if profile.reasoning_window_behavior == "unknown":
            unknown_capabilities.append("reasoning_window_behavior")
        if profile.provider_overhead_behavior == "unknown":
            unknown_capabilities.append("provider_overhead_behavior")
        if profile.prompt_cache == "unknown":
            unknown_capabilities.append("prompt_cache")
    if counting_mode == "estimated":
        unknown_capabilities.append("tokenizer")

    fingerprint = compute_fingerprint(
        resolver_version=RESOLVER_VERSION,
        provider=provider,
        model_name=model_id,
        context_window_tokens=context_window_tokens,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        default_output_reserve_tokens=default_output_reserve_tokens,
        requested_output_tokens=output_protection_tokens,
        provider_input_limit_tokens=provider_input_limit_tokens,
        tokenizer_family=tokenizer_family,
        counting_mode=counting_mode,
        capability_profile_version=capability_profile_version,
        unknown_capabilities=unknown_capabilities,
        field_sources=dict(field_sources),
    )

    return ModelCapacitySnapshot(
        provider=provider,
        model_name=model_id,
        context_window_tokens=context_window_tokens,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        default_output_reserve_tokens=default_output_reserve_tokens,
        requested_output_tokens=output_protection_tokens,
        provider_input_limit_tokens=provider_input_limit_tokens,
        tokenizer_family=tokenizer_family,
        counting_mode=counting_mode,
        unknown_capabilities=unknown_capabilities,
        field_sources=dict(field_sources),
        capability_profile_version=capability_profile_version,
        resolver_version=RESOLVER_VERSION,
        warnings=[],
        fingerprint=fingerprint,
    )
