# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .capacity_resolver import ModelCapacitySnapshot


CONTEXT_BUDGET_RESOLVER_VERSION = "3.0.0"
CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION = 3
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

    remaining_window_ratio: float = Field(default=0.2, gt=0, lt=1)
    remaining_window_max_tokens: int = Field(default=20000, gt=0)
    maintenance_target_multiplier: float = Field(default=2.0, gt=1, allow_inf_nan=False)

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

    requested_output_tokens: Optional[int] = None
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
    schema_version: Literal[3] = CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION
    resolver_version: Literal["3.0.0"] = CONTEXT_BUDGET_RESOLVER_VERSION
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

    raise NoSafeInputCapacity(
        "Legacy context budgets must be rebuilt from the current combined and output capabilities"
    )


class ContextBudgetCalculator:
    """Derive post-response maintenance thresholds without output reservations."""

    def calculate_context_budget(
        self, *, capacity_snapshot: ModelCapacitySnapshot,
        reserve_policy: CapacityReservePolicy,
        request_overrides: Optional[RequestBudgetOverrides] = None,
        requested_output_tokens: Optional[int] = None,
        output_reserve_source: OutputReserveSource = "model_default",
    ) -> ContextBudgetSnapshot:
        window = capacity_snapshot.context_window_tokens
        if window is None or window < 2:
            raise NoSafeInputCapacity("a combined context window of at least two tokens is required")
        ratio = reserve_policy.remaining_window_ratio
        # Preserve an explicitly configured legacy strategy ratio, not legacy
        # model output budgets. Defaults use the remaining-space policy.
        if (reserve_policy.compaction_trigger_ratio_source != "code_default"
                and "remaining_window_ratio" not in reserve_policy.model_fields_set):
            ratio = 1 - reserve_policy.compaction_trigger_ratio
        if not 0 < ratio < 1:
            raise InvalidReservePolicy("remaining context ratio must be in (0, 1)")
        headroom = min(window - 1, math.ceil(min(
            ratio * window, reserve_policy.remaining_window_max_tokens,
        )))
        target_headroom = min(window - 1, math.ceil(
            headroom * reserve_policy.maintenance_target_multiplier,
        ))
        trigger = window - headroom
        target = window - target_headroom
        fields = {
            "effective_input_limit_tokens": "derived",
            "compaction_trigger_threshold_tokens": "derived",
            "compaction_target_tokens": "derived",
        }
        values = dict(
            w1_fingerprint=capacity_snapshot.fingerprint,
            provider=capacity_snapshot.provider, model_name=capacity_snapshot.model_name,
            requested_output_tokens=None, output_reserve_source="model_default",
            uncertainty_reserve_tokens=0, uncertainty_reserve_basis="none",
            approved_profile_reserve_tokens=None,
            effective_input_limit_tokens=window,
            compaction_trigger_ratio=trigger / window,
            compaction_trigger_ratio_source=reserve_policy.compaction_trigger_ratio_source,
            compaction_trigger_threshold_tokens=trigger,
            compaction_target_ratio=target / window,
            compaction_target_ratio_source="code_default",
            compaction_target_tokens=target, field_sources=fields, warnings=[],
        )
        fingerprint = compute_context_budget_fingerprint(
            resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION, **values,
        )
        return ContextBudgetSnapshot(**values, fingerprint=fingerprint)


def verify_context_budget_capacity(
    *, budget_snapshot: ContextBudgetSnapshot, capacity_snapshot: Optional[Mapping[str, Any]],
) -> None:
    """Reuse the legacy dispatch identity check without provider or HTTP dependencies."""
    if not capacity_snapshot:
        return
    w1_fingerprint = capacity_snapshot.get("capacity_fingerprint")
    provider = capacity_snapshot.get("provider")
    model_name = capacity_snapshot.get("model_name")
    if not w1_fingerprint and not provider and not model_name:
        return
    if w1_fingerprint and w1_fingerprint != budget_snapshot.w1_fingerprint:
        raise ContextBudgetCapacityMismatch(
            field="w1_fingerprint",
            expected=w1_fingerprint,
            actual=budget_snapshot.w1_fingerprint,
        )
    # Provider IDs are normalized when legacy records become resolved outlets.
    if provider and str(provider).casefold() != budget_snapshot.provider.casefold():
        raise ContextBudgetCapacityMismatch(
            field="provider",
            expected=provider,
            actual=budget_snapshot.provider,
        )
    if model_name and model_name != budget_snapshot.model_name:
        raise ContextBudgetCapacityMismatch(
            field="model_name",
            expected=model_name,
            actual=budget_snapshot.model_name,
        )
