from __future__ import annotations

import hashlib
import json
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
    """W2 calculator interface.

    The implementation is intentionally deferred until the W2 ADR is accepted.
    """

    def calculate_safe_input_budget(
        self,
        *,
        capacity_snapshot: ModelCapacitySnapshot,
        reserve_policy: CapacityReservePolicy,
        request_overrides: Optional[RequestBudgetOverrides] = None,
        requested_output_tokens: Optional[int] = None,
        output_reserve_source: OutputReserveSource = "model_default",
    ) -> SafeInputBudgetSnapshot:
        raise NotImplementedError(
            "SafeInputBudgetCalculator body is gated by W2 ADR acceptance"
        )
