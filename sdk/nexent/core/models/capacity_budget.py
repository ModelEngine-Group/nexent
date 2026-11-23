from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .capacity_resolver import ModelCapacitySnapshot


CONTEXT_BUDGET_RESOLVER_VERSION = "2.0.0"
CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION = 2
LEGACY_W2_RESOLVER_VERSION = "1.0.0"
LEGACY_W2_FINGERPRINT_SCHEMA_VERSION = 1


OutputReserveSource = Literal["model_default", "agent", "request"]
UncertaintyReserveBasis = Literal[
    "context_window_10pct", "approved_profile", "none"
]
CompactionRatioSource = Literal["code_default", "tenant_config", "legacy_payload"]
BudgetFieldSource = Literal[
    "model_default",
    "agent",
    "request",
    "code_default",
    "tenant_config",
    "approved_profile",
    "derived",
]


class BudgetResolverError(Exception):
    """Base class for W2 safe-input-budget resolution failures."""


class InvalidReservePolicy(BudgetResolverError):
    pass


class RequestedOutputExceedsCapacity(BudgetResolverError):
    pass


class UncertaintyReserveBasisUnknown(BudgetResolverError):
    pass


class ReserveExceedsCapacity(BudgetResolverError):
    pass


class NoSafeInputCapacity(BudgetResolverError):
    pass


class ContextBudgetFingerprintMismatch(BudgetResolverError):
    """Raised when a context-budget snapshot fingerprint does not match."""

    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            "context_budget_fingerprint_mismatch: "
            f"expected={expected} actual={actual}"
        )


class CallerMaxTokensOverrideForbidden(BudgetResolverError):
    """Raised when a caller tries to override W2's trusted output cap."""

    def __init__(self, *, snapshot_value: int, caller_value: int) -> None:
        self.snapshot_value = snapshot_value
        self.caller_value = caller_value
        super().__init__(
            "caller_max_tokens_override_forbidden: "
            f"caller max_tokens={caller_value} does not match "
            f"requested_output_tokens={snapshot_value}"
        )


class ContextBudgetCapacityMismatch(BudgetResolverError):
    """Raised when a W2 snapshot's W1 identity disagrees with the active W1.

    Catches the case where a W2 snapshot computed from one model's W1
    capacity is dispatched against a different model (stale cache, mid-flight
    swap, cross-tenant leak). Verified at the trusted dispatch boundary as
    defense-in-depth per CM-013.
    """

    def __init__(self, *, field: str, expected: str, actual: str) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            "context_budget_capacity_mismatch: "
            f"field={field} expected={expected} actual={actual}"
        )


class CapacityReservePolicy(BaseModel):
    """Immutable W2 reserve policy resolved before budget calculation."""

    model_config = ConfigDict(frozen=True)

    compaction_trigger_ratio: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Ratio of Effective Input Limit where proactive compaction begins.",
    )
    compaction_trigger_ratio_source: CompactionRatioSource = "code_default"
    compaction_target_ratio: float = Field(default=0.6, gt=0, le=1)
    compaction_target_ratio_source: CompactionRatioSource = "code_default"
    approved_profile_reserve_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Verified reserve from the selected capability profile. When present, "
            "it may replace the unified 10 percent uncertainty reserve."
        ),
    )


class RequestBudgetOverrides(BaseModel):
    """Per-request W2 budget overrides accepted from trusted backend resolution."""

    model_config = ConfigDict(frozen=True)

    requested_output_tokens: Optional[int] = Field(default=None, gt=0)


class ContextBudgetSnapshot(BaseModel):
    """Immutable canonical W2 contract consumed by runtime and dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    w1_fingerprint: str
    provider: str
    model_name: str

    requested_output_tokens: int
    output_reserve_source: OutputReserveSource

    effective_input_limit_tokens: int
    uncertainty_reserve_tokens: int
    uncertainty_reserve_basis: UncertaintyReserveBasis
    approved_profile_reserve_tokens: Optional[int] = None

    compaction_trigger_ratio: float = Field(gt=0, le=1)
    compaction_trigger_ratio_source: CompactionRatioSource
    compaction_trigger_threshold_tokens: int
    compaction_target_ratio: float = Field(gt=0, le=1)
    compaction_target_ratio_source: CompactionRatioSource
    compaction_target_tokens: int

    field_sources: Mapping[str, str] = Field(default_factory=dict)
    warnings: Sequence[str] = Field(default_factory=list)
    schema_version: Literal[2] = CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION
    resolver_version: Literal["2.0.0"] = CONTEXT_BUDGET_RESOLVER_VERSION
    fingerprint: str


def compute_context_budget_fingerprint(
    *,
    resolver_version: str,
    w1_fingerprint: str,
    provider: str,
    model_name: str,
    requested_output_tokens: int,
    output_reserve_source: str,
    uncertainty_reserve_tokens: int,
    uncertainty_reserve_basis: str,
    approved_profile_reserve_tokens: Optional[int],
    effective_input_limit_tokens: int,
    compaction_trigger_ratio: float,
    compaction_trigger_ratio_source: str,
    compaction_trigger_threshold_tokens: int,
    compaction_target_ratio: float,
    compaction_target_ratio_source: str,
    compaction_target_tokens: int,
    field_sources: Mapping[str, str],
    warnings: Sequence[str] = (),
) -> str:
    """Compute the W2 ADR Decision 1 fingerprint.

    `warnings` is accepted to keep the signature aligned with the ADR, but is
    intentionally excluded from the canonical payload.
    """
    _ = warnings
    payload: dict[str, Any] = {
        "v": CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION,
        "resolver_version": resolver_version,
        "w1_fingerprint": w1_fingerprint,
        "provider": provider,
        "model_name": model_name,
        "requested_output_tokens": requested_output_tokens,
        "output_reserve_source": output_reserve_source,
        "uncertainty_reserve_tokens": uncertainty_reserve_tokens,
        "uncertainty_reserve_basis": uncertainty_reserve_basis,
        "approved_profile_reserve_tokens": approved_profile_reserve_tokens,
        "effective_input_limit_tokens": effective_input_limit_tokens,
        "compaction_trigger_ratio": compaction_trigger_ratio,
        "compaction_trigger_ratio_source": compaction_trigger_ratio_source,
        "compaction_trigger_threshold_tokens": compaction_trigger_threshold_tokens,
        "compaction_target_ratio": compaction_target_ratio,
        "compaction_target_ratio_source": compaction_target_ratio_source,
        "compaction_target_tokens": compaction_target_tokens,
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


def _compute_legacy_w2_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = {
        "v": LEGACY_W2_FINGERPRINT_SCHEMA_VERSION,
        "w2_resolver_version": payload.get("resolver_version", LEGACY_W2_RESOLVER_VERSION),
        "w1_fingerprint": payload["w1_fingerprint"],
        "provider": payload["provider"],
        "model_name": payload["model_name"],
        "requested_output_tokens": payload["requested_output_tokens"],
        "output_reserve_source": payload["output_reserve_source"],
        "uncertainty_reserve_tokens": payload["uncertainty_reserve_tokens"],
        "uncertainty_reserve_basis": payload["uncertainty_reserve_basis"],
        "approved_profile_reserve_tokens": payload.get("approved_profile_reserve_tokens"),
        "soft_limit_ratio": payload["soft_limit_ratio"],
        "soft_limit_ratio_source": payload["soft_limit_ratio_source"],
        "soft_input_budget_tokens": payload["soft_input_budget_tokens"],
        "hard_input_budget_tokens": payload["hard_input_budget_tokens"],
        "field_sources": dict(sorted((payload.get("field_sources") or {}).items())),
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def validate_context_budget_snapshot(snapshot: ContextBudgetSnapshot) -> ContextBudgetSnapshot:
    expected = compute_context_budget_fingerprint(
        resolver_version=snapshot.resolver_version,
        w1_fingerprint=snapshot.w1_fingerprint,
        provider=snapshot.provider,
        model_name=snapshot.model_name,
        requested_output_tokens=snapshot.requested_output_tokens,
        output_reserve_source=snapshot.output_reserve_source,
        uncertainty_reserve_tokens=snapshot.uncertainty_reserve_tokens,
        uncertainty_reserve_basis=snapshot.uncertainty_reserve_basis,
        approved_profile_reserve_tokens=snapshot.approved_profile_reserve_tokens,
        effective_input_limit_tokens=snapshot.effective_input_limit_tokens,
        compaction_trigger_ratio=snapshot.compaction_trigger_ratio,
        compaction_trigger_ratio_source=snapshot.compaction_trigger_ratio_source,
        compaction_trigger_threshold_tokens=snapshot.compaction_trigger_threshold_tokens,
        compaction_target_ratio=snapshot.compaction_target_ratio,
        compaction_target_ratio_source=snapshot.compaction_target_ratio_source,
        compaction_target_tokens=snapshot.compaction_target_tokens,
        field_sources=snapshot.field_sources,
        warnings=snapshot.warnings,
    )
    if snapshot.fingerprint != expected:
        raise ContextBudgetFingerprintMismatch(expected=expected, actual=snapshot.fingerprint)
    return snapshot


def parse_context_budget_snapshot(
    value: ContextBudgetSnapshot | Mapping[str, Any],
) -> ContextBudgetSnapshot:
    """Validate V2 or convert one verified legacy W2 V1 payload."""
    if isinstance(value, ContextBudgetSnapshot):
        return validate_context_budget_snapshot(value)
    data = dict(value)
    if "effective_input_limit_tokens" in data:
        return validate_context_budget_snapshot(ContextBudgetSnapshot.model_validate(data))

    expected_v1 = _compute_legacy_w2_fingerprint(data)
    actual_v1 = str(data.get("fingerprint") or "")
    if actual_v1 != expected_v1:
        raise ContextBudgetFingerprintMismatch(expected=expected_v1, actual=actual_v1)

    effective_input_limit_tokens = int(data["provider_input_limit_tokens"])
    trigger_ratio = float(data["soft_limit_ratio"])
    trigger_threshold = int(data["soft_input_budget_tokens"])
    target_ratio = 0.6
    target_tokens = max(1, math.floor(effective_input_limit_tokens * target_ratio))
    legacy_sources = dict(data.get("field_sources") or {})
    field_sources = {
        key: value
        for key, value in legacy_sources.items()
        if key not in {
            "provider_input_limit_tokens",
            "soft_limit_ratio",
            "soft_input_budget_tokens",
            "hard_input_budget_tokens",
        }
    }
    field_sources.update({
        "effective_input_limit_tokens": legacy_sources.get(
            "provider_input_limit_tokens", "derived"
        ),
        "compaction_trigger_ratio": legacy_sources.get(
            "soft_limit_ratio", "legacy_payload"
        ),
        "compaction_trigger_threshold_tokens": legacy_sources.get(
            "soft_input_budget_tokens", "legacy_payload"
        ),
        "compaction_target_ratio": "code_default",
        "compaction_target_tokens": "derived",
    })
    warnings = [*list(data.get("warnings") or []), "legacy_w2_v1_payload_migrated"]
    fingerprint = compute_context_budget_fingerprint(
        resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION,
        w1_fingerprint=str(data["w1_fingerprint"]),
        provider=str(data["provider"]),
        model_name=str(data["model_name"]),
        requested_output_tokens=int(data["requested_output_tokens"]),
        output_reserve_source=str(data["output_reserve_source"]),
        uncertainty_reserve_tokens=int(data["uncertainty_reserve_tokens"]),
        uncertainty_reserve_basis=str(data["uncertainty_reserve_basis"]),
        approved_profile_reserve_tokens=data.get("approved_profile_reserve_tokens"),
        effective_input_limit_tokens=effective_input_limit_tokens,
        compaction_trigger_ratio=trigger_ratio,
        compaction_trigger_ratio_source="legacy_payload",
        compaction_trigger_threshold_tokens=trigger_threshold,
        compaction_target_ratio=target_ratio,
        compaction_target_ratio_source="code_default",
        compaction_target_tokens=target_tokens,
        field_sources=field_sources,
        warnings=warnings,
    )
    return ContextBudgetSnapshot(
        w1_fingerprint=str(data["w1_fingerprint"]),
        provider=str(data["provider"]),
        model_name=str(data["model_name"]),
        requested_output_tokens=int(data["requested_output_tokens"]),
        output_reserve_source=data["output_reserve_source"],
        effective_input_limit_tokens=effective_input_limit_tokens,
        uncertainty_reserve_tokens=int(data["uncertainty_reserve_tokens"]),
        uncertainty_reserve_basis=data["uncertainty_reserve_basis"],
        approved_profile_reserve_tokens=data.get("approved_profile_reserve_tokens"),
        compaction_trigger_ratio=trigger_ratio,
        compaction_trigger_ratio_source="legacy_payload",
        compaction_trigger_threshold_tokens=trigger_threshold,
        compaction_target_ratio=target_ratio,
        compaction_target_ratio_source="code_default",
        compaction_target_tokens=target_tokens,
        field_sources=field_sources,
        warnings=warnings,
        fingerprint=fingerprint,
    )


class ContextBudgetCalculator:
    """Pure canonical W2 calculator over an immutable W1 capacity snapshot."""

    _UNKNOWN_CAPABILITIES_REQUIRING_RESERVE = frozenset(
        {
            "capability_profile_missing",
            "tokenizer",
            "reasoning_window_behavior",
            "provider_overhead_behavior",
        }
    )

    def calculate_context_budget(
        self,
        *,
        capacity_snapshot: ModelCapacitySnapshot,
        reserve_policy: CapacityReservePolicy,
        request_overrides: Optional[RequestBudgetOverrides] = None,
        requested_output_tokens: Optional[int] = None,
        output_reserve_source: OutputReserveSource = "model_default",
    ) -> ContextBudgetSnapshot:
        effective_output_tokens = (
            requested_output_tokens
            if requested_output_tokens is not None
            else capacity_snapshot.requested_output_tokens
        )
        effective_output_source: OutputReserveSource = output_reserve_source
        if requested_output_tokens is None:
            effective_output_source = "model_default"

        if effective_output_tokens <= 0:
            raise InvalidReservePolicy(
                "requested_output_tokens must be a positive integer"
            )

        if request_overrides and request_overrides.requested_output_tokens is not None:
            if request_overrides.requested_output_tokens < effective_output_tokens:
                raise InvalidReservePolicy(
                    "per-request requested_output_tokens may not lower the "
                    "resolved model or agent output reserve"
                )
            effective_output_tokens = request_overrides.requested_output_tokens
            effective_output_source = "request"

        if (
            capacity_snapshot.max_output_tokens is not None
            and effective_output_tokens > capacity_snapshot.max_output_tokens
        ):
            raise RequestedOutputExceedsCapacity(
                "requested_output_tokens "
                f"({effective_output_tokens}) exceeds max_output_tokens "
                f"({capacity_snapshot.max_output_tokens})"
            )

        provider_input_limit = self._provider_input_limit(
            capacity_snapshot=capacity_snapshot,
            requested_output_tokens=effective_output_tokens,
        )

        uncertainty_reserve_tokens, uncertainty_reserve_basis, warnings = (
            self._uncertainty_reserve(capacity_snapshot, reserve_policy)
        )

        if uncertainty_reserve_tokens > provider_input_limit:
            raise ReserveExceedsCapacity(
                "uncertainty reserve "
                f"({uncertainty_reserve_tokens}) exceeds provider input limit "
                f"({provider_input_limit})"
            )

        compaction_trigger_threshold_tokens = max(
            1, math.floor(provider_input_limit * reserve_policy.compaction_trigger_ratio)
        )
        compaction_target_tokens = max(
            1, math.floor(provider_input_limit * reserve_policy.compaction_target_ratio)
        )

        field_sources = {
            "requested_output_tokens": effective_output_source,
            "compaction_trigger_ratio": reserve_policy.compaction_trigger_ratio_source,
            "compaction_target_ratio": reserve_policy.compaction_target_ratio_source,
            "uncertainty_reserve_tokens": uncertainty_reserve_basis,
            "effective_input_limit_tokens": "derived",
            "compaction_trigger_threshold_tokens": "derived",
            "compaction_target_tokens": "derived",
        }

        fingerprint = compute_context_budget_fingerprint(
            resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION,
            w1_fingerprint=capacity_snapshot.fingerprint,
            provider=capacity_snapshot.provider,
            model_name=capacity_snapshot.model_name,
            requested_output_tokens=effective_output_tokens,
            output_reserve_source=effective_output_source,
            uncertainty_reserve_tokens=uncertainty_reserve_tokens,
            uncertainty_reserve_basis=uncertainty_reserve_basis,
            approved_profile_reserve_tokens=reserve_policy.approved_profile_reserve_tokens,
            effective_input_limit_tokens=provider_input_limit,
            compaction_trigger_ratio=reserve_policy.compaction_trigger_ratio,
            compaction_trigger_ratio_source=reserve_policy.compaction_trigger_ratio_source,
            compaction_trigger_threshold_tokens=compaction_trigger_threshold_tokens,
            compaction_target_ratio=reserve_policy.compaction_target_ratio,
            compaction_target_ratio_source=reserve_policy.compaction_target_ratio_source,
            compaction_target_tokens=compaction_target_tokens,
            field_sources=field_sources,
            warnings=warnings,
        )

        return ContextBudgetSnapshot(
            w1_fingerprint=capacity_snapshot.fingerprint,
            provider=capacity_snapshot.provider,
            model_name=capacity_snapshot.model_name,
            requested_output_tokens=effective_output_tokens,
            output_reserve_source=effective_output_source,
            effective_input_limit_tokens=provider_input_limit,
            uncertainty_reserve_tokens=uncertainty_reserve_tokens,
            uncertainty_reserve_basis=uncertainty_reserve_basis,
            approved_profile_reserve_tokens=reserve_policy.approved_profile_reserve_tokens,
            compaction_trigger_ratio=reserve_policy.compaction_trigger_ratio,
            compaction_trigger_ratio_source=reserve_policy.compaction_trigger_ratio_source,
            compaction_trigger_threshold_tokens=compaction_trigger_threshold_tokens,
            compaction_target_ratio=reserve_policy.compaction_target_ratio,
            compaction_target_ratio_source=reserve_policy.compaction_target_ratio_source,
            compaction_target_tokens=compaction_target_tokens,
            field_sources=field_sources,
            warnings=warnings,
            resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _provider_input_limit(
        *,
        capacity_snapshot: ModelCapacitySnapshot,
        requested_output_tokens: int,
    ) -> int:
        derived_limits: list[int] = []
        if capacity_snapshot.max_input_tokens is not None:
            derived_limits.append(capacity_snapshot.max_input_tokens)
        if capacity_snapshot.context_window_tokens is not None:
            derived_limits.append(
                capacity_snapshot.context_window_tokens - requested_output_tokens
            )
        if not derived_limits:
            raise NoSafeInputCapacity("no provider input limit could be derived")
        provider_input_limit = min(derived_limits)
        if provider_input_limit <= 0:
            raise NoSafeInputCapacity(
                "provider input limit is non-positive after output reserve"
            )
        return provider_input_limit

    def _uncertainty_reserve(
        self,
        capacity_snapshot: ModelCapacitySnapshot,
        reserve_policy: CapacityReservePolicy,
    ) -> tuple[int, UncertaintyReserveBasis, list[str]]:
        unknown_required_behavior = self._UNKNOWN_CAPABILITIES_REQUIRING_RESERVE.intersection(
            capacity_snapshot.unknown_capabilities
        )

        if reserve_policy.approved_profile_reserve_tokens is not None:
            return (
                reserve_policy.approved_profile_reserve_tokens,
                "approved_profile",
                [],
            )

        if not unknown_required_behavior:
            return 0, "none", []

        if capacity_snapshot.context_window_tokens is None:
            raise UncertaintyReserveBasisUnknown(
                "context_window_tokens is required for the unified 10 percent "
                "uncertainty reserve"
            )

        reserve = math.ceil(capacity_snapshot.context_window_tokens * 0.10)
        return reserve, "context_window_10pct", ["uncertainty_reserve_active"]
