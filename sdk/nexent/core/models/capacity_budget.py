from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .capacity_resolver import ModelCapacitySnapshot


W2_RESOLVER_VERSION = "1.0.0"
W2_FINGERPRINT_SCHEMA_VERSION = 1


OutputReserveSource = Literal["model_default", "agent", "request"]
UncertaintyReserveBasis = Literal[
    "context_window_10pct", "approved_profile", "none"
]
SoftLimitRatioSource = Literal["code_default", "tenant_config"]
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


class SafeInputBudgetFingerprintMismatch(BudgetResolverError):
    """Raised when a W2 snapshot fingerprint does not match its payload."""

    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            "safe_input_budget_fingerprint_mismatch: "
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


class SafeInputBudgetCapacityMismatch(BudgetResolverError):
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
            "safe_input_budget_capacity_mismatch: "
            f"field={field} expected={expected} actual={actual}"
        )


class CapacityReservePolicy(BaseModel):
    """Immutable W2 reserve policy resolved before budget calculation."""

    model_config = ConfigDict(frozen=True)

    soft_limit_ratio: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Ratio of hard safe input budget where proactive compaction begins.",
    )
    soft_limit_ratio_source: SoftLimitRatioSource = "code_default"
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


class SafeInputBudgetSnapshot(BaseModel):
    """Immutable W2 budget contract consumed by W3 and trusted dispatch."""

    model_config = ConfigDict(frozen=True)

    w1_fingerprint: str
    provider: str
    model_name: str

    requested_output_tokens: int
    output_reserve_source: OutputReserveSource

    provider_input_limit_tokens: int
    uncertainty_reserve_tokens: int
    uncertainty_reserve_basis: UncertaintyReserveBasis
    approved_profile_reserve_tokens: Optional[int] = None

    soft_limit_ratio: float = Field(gt=0, le=1)
    soft_limit_ratio_source: SoftLimitRatioSource
    soft_input_budget_tokens: int
    hard_input_budget_tokens: int

    field_sources: Mapping[str, str] = Field(default_factory=dict)
    warnings: Sequence[str] = Field(default_factory=list)
    resolver_version: str = W2_RESOLVER_VERSION
    fingerprint: str


def compute_w2_fingerprint(
    *,
    w2_resolver_version: str,
    w1_fingerprint: str,
    provider: str,
    model_name: str,
    requested_output_tokens: int,
    output_reserve_source: str,
    uncertainty_reserve_tokens: int,
    uncertainty_reserve_basis: str,
    approved_profile_reserve_tokens: Optional[int],
    soft_limit_ratio: float,
    soft_limit_ratio_source: str,
    soft_input_budget_tokens: int,
    hard_input_budget_tokens: int,
    field_sources: Mapping[str, str],
    warnings: Sequence[str] = (),
) -> str:
    """Compute the W2 ADR Decision 1 fingerprint.

    `warnings` is accepted to keep the signature aligned with the ADR, but is
    intentionally excluded from the canonical payload.
    """
    _ = warnings
    payload: dict[str, Any] = {
        "v": W2_FINGERPRINT_SCHEMA_VERSION,
        "w2_resolver_version": w2_resolver_version,
        "w1_fingerprint": w1_fingerprint,
        "provider": provider,
        "model_name": model_name,
        "requested_output_tokens": requested_output_tokens,
        "output_reserve_source": output_reserve_source,
        "uncertainty_reserve_tokens": uncertainty_reserve_tokens,
        "uncertainty_reserve_basis": uncertainty_reserve_basis,
        "approved_profile_reserve_tokens": approved_profile_reserve_tokens,
        "soft_limit_ratio": soft_limit_ratio,
        "soft_limit_ratio_source": soft_limit_ratio_source,
        "soft_input_budget_tokens": soft_input_budget_tokens,
        "hard_input_budget_tokens": hard_input_budget_tokens,
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


class SafeInputBudgetCalculator:
    """Pure W2 calculator over an immutable W1 capacity snapshot."""

    _UNKNOWN_CAPABILITIES_REQUIRING_RESERVE = frozenset(
        {
            "capability_profile_missing",
            "tokenizer",
            "reasoning_window_behavior",
            "provider_overhead_behavior",
        }
    )

    def calculate_safe_input_budget(
        self,
        *,
        capacity_snapshot: ModelCapacitySnapshot,
        reserve_policy: CapacityReservePolicy,
        request_overrides: Optional[RequestBudgetOverrides] = None,
        requested_output_tokens: Optional[int] = None,
        output_reserve_source: OutputReserveSource = "model_default",
    ) -> SafeInputBudgetSnapshot:
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

        hard_input_budget_tokens = provider_input_limit - uncertainty_reserve_tokens
        if hard_input_budget_tokens <= 0:
            raise NoSafeInputCapacity(
                "safe input budget is non-positive after applying reserves"
            )

        soft_input_budget_tokens = max(
            1, math.floor(hard_input_budget_tokens * reserve_policy.soft_limit_ratio)
        )

        field_sources = {
            "requested_output_tokens": effective_output_source,
            "soft_limit_ratio": reserve_policy.soft_limit_ratio_source,
            "uncertainty_reserve_tokens": uncertainty_reserve_basis,
            "provider_input_limit_tokens": "derived",
            "hard_input_budget_tokens": "derived",
            "soft_input_budget_tokens": "derived",
        }

        fingerprint = compute_w2_fingerprint(
            w2_resolver_version=W2_RESOLVER_VERSION,
            w1_fingerprint=capacity_snapshot.fingerprint,
            provider=capacity_snapshot.provider,
            model_name=capacity_snapshot.model_name,
            requested_output_tokens=effective_output_tokens,
            output_reserve_source=effective_output_source,
            uncertainty_reserve_tokens=uncertainty_reserve_tokens,
            uncertainty_reserve_basis=uncertainty_reserve_basis,
            approved_profile_reserve_tokens=reserve_policy.approved_profile_reserve_tokens,
            soft_limit_ratio=reserve_policy.soft_limit_ratio,
            soft_limit_ratio_source=reserve_policy.soft_limit_ratio_source,
            soft_input_budget_tokens=soft_input_budget_tokens,
            hard_input_budget_tokens=hard_input_budget_tokens,
            field_sources=field_sources,
            warnings=warnings,
        )

        return SafeInputBudgetSnapshot(
            w1_fingerprint=capacity_snapshot.fingerprint,
            provider=capacity_snapshot.provider,
            model_name=capacity_snapshot.model_name,
            requested_output_tokens=effective_output_tokens,
            output_reserve_source=effective_output_source,
            provider_input_limit_tokens=provider_input_limit,
            uncertainty_reserve_tokens=uncertainty_reserve_tokens,
            uncertainty_reserve_basis=uncertainty_reserve_basis,
            approved_profile_reserve_tokens=reserve_policy.approved_profile_reserve_tokens,
            soft_limit_ratio=reserve_policy.soft_limit_ratio,
            soft_limit_ratio_source=reserve_policy.soft_limit_ratio_source,
            soft_input_budget_tokens=soft_input_budget_tokens,
            hard_input_budget_tokens=hard_input_budget_tokens,
            field_sources=field_sources,
            warnings=warnings,
            resolver_version=W2_RESOLVER_VERSION,
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
