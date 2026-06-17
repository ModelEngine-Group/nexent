"""Unit tests for W2 safe-input-budget type skeleton."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError


_SDK_ROOT = Path(__file__).resolve().parents[4] / "sdk" / "nexent"

for pkg_name, pkg_path in (
    ("nexent", _SDK_ROOT),
    ("nexent.core", _SDK_ROOT / "core"),
    ("nexent.core.models", _SDK_ROOT / "core" / "models"),
):
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_path)]
        sys.modules[pkg_name] = pkg


def _load(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_capacity_resolver = _load(
    "nexent.core.models.capacity_resolver",
    _SDK_ROOT / "core" / "models" / "capacity_resolver.py",
)
_capacity_budget = _load(
    "nexent.core.models.capacity_budget",
    _SDK_ROOT / "core" / "models" / "capacity_budget.py",
)

CapacityReservePolicy = _capacity_budget.CapacityReservePolicy
InvalidReservePolicy = _capacity_budget.InvalidReservePolicy
NoSafeInputCapacity = _capacity_budget.NoSafeInputCapacity
RequestedOutputExceedsCapacity = _capacity_budget.RequestedOutputExceedsCapacity
RequestBudgetOverrides = _capacity_budget.RequestBudgetOverrides
ReserveExceedsCapacity = _capacity_budget.ReserveExceedsCapacity
SafeInputBudgetCalculator = _capacity_budget.SafeInputBudgetCalculator
UncertaintyReserveBasisUnknown = _capacity_budget.UncertaintyReserveBasisUnknown
W2_RESOLVER_VERSION = _capacity_budget.W2_RESOLVER_VERSION
compute_w2_fingerprint = _capacity_budget.compute_w2_fingerprint
ModelCapacitySnapshot = _capacity_resolver.ModelCapacitySnapshot


def _fingerprint(**overrides) -> str:
    payload = {
        "w2_resolver_version": W2_RESOLVER_VERSION,
        "w1_fingerprint": "w1abc",
        "provider": "openai",
        "model_name": "gpt-4o",
        "requested_output_tokens": 4096,
        "output_reserve_source": "model_default",
        "uncertainty_reserve_tokens": 12800,
        "uncertainty_reserve_basis": "context_window_10pct",
        "approved_profile_reserve_tokens": None,
        "soft_limit_ratio": 0.8,
        "soft_limit_ratio_source": "code_default",
        "soft_input_budget_tokens": 88883,
        "hard_input_budget_tokens": 111104,
        "field_sources": {"soft_limit_ratio": "code_default"},
        "warnings": [],
    }
    payload.update(overrides)
    return compute_w2_fingerprint(**payload)


def test_capacity_reserve_policy_defaults_to_w2_soft_limit():
    policy = CapacityReservePolicy()

    assert policy.soft_limit_ratio == 0.8
    assert policy.soft_limit_ratio_source == "code_default"
    assert policy.approved_profile_reserve_tokens is None


def test_capacity_reserve_policy_rejects_invalid_ratio():
    with pytest.raises(ValidationError):
        CapacityReservePolicy(soft_limit_ratio=0)

    with pytest.raises(ValidationError):
        CapacityReservePolicy(soft_limit_ratio=1.01)


def test_compute_w2_fingerprint_is_deterministic_and_ignores_warnings():
    first = _fingerprint(warnings=["observe-only"])
    second = _fingerprint(warnings=["different warning"])

    assert first == second
    assert len(first) == 32


def test_compute_w2_fingerprint_changes_when_contract_changes():
    first = _fingerprint()
    second = _fingerprint(requested_output_tokens=8192)

    assert first != second


def _capacity_snapshot(**overrides) -> ModelCapacitySnapshot:
    payload = {
        "provider": "openai",
        "model_name": "gpt-4o",
        "context_window_tokens": 128_000,
        "max_input_tokens": None,
        "max_output_tokens": 16_384,
        "default_output_reserve_tokens": 4_096,
        "requested_output_tokens": 4_096,
        "provider_input_limit_tokens": 123_904,
        "tokenizer_family": "o200k_base",
        "counting_mode": "estimated",
        "unknown_capabilities": ["tokenizer"],
        "field_sources": {
            "context_window_tokens": "profile",
            "max_output_tokens": "profile",
        },
        "capability_profile_version": "openai/gpt-4o@1",
        "fingerprint": "w1fingerprint",
    }
    payload.update(overrides)
    return ModelCapacitySnapshot(**payload)


def test_calculator_combined_window_uses_10_percent_uncertainty_reserve():
    calculator = SafeInputBudgetCalculator()

    snap = calculator.calculate_safe_input_budget(
        capacity_snapshot=_capacity_snapshot(),
        reserve_policy=CapacityReservePolicy(),
    )

    assert snap.provider_input_limit_tokens == 128_000 - 4_096
    assert snap.uncertainty_reserve_tokens == 12_800
    assert snap.uncertainty_reserve_basis == "context_window_10pct"
    assert snap.hard_input_budget_tokens == 111_104
    assert snap.soft_input_budget_tokens == 88_883
    assert snap.requested_output_tokens == 4_096
    assert snap.output_reserve_source == "model_default"
    assert snap.w1_fingerprint == "w1fingerprint"
    assert "uncertainty_reserve_active" in snap.warnings
    assert len(snap.fingerprint) == 32


def test_calculator_recomputes_provider_limit_for_request_override():
    calculator = SafeInputBudgetCalculator()

    snap = calculator.calculate_safe_input_budget(
        capacity_snapshot=_capacity_snapshot(),
        reserve_policy=CapacityReservePolicy(),
        request_overrides=RequestBudgetOverrides(requested_output_tokens=8_192),
    )

    assert snap.requested_output_tokens == 8_192
    assert snap.output_reserve_source == "request"
    assert snap.provider_input_limit_tokens == 128_000 - 8_192
    assert snap.hard_input_budget_tokens == (128_000 - 8_192) - 12_800


def test_calculator_rejects_request_override_that_lowers_reserve():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(InvalidReservePolicy):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=_capacity_snapshot(),
            reserve_policy=CapacityReservePolicy(),
            request_overrides=RequestBudgetOverrides(requested_output_tokens=2_048),
        )


def test_calculator_allows_agent_override_source():
    calculator = SafeInputBudgetCalculator()

    snap = calculator.calculate_safe_input_budget(
        capacity_snapshot=_capacity_snapshot(),
        reserve_policy=CapacityReservePolicy(),
        requested_output_tokens=2_048,
        output_reserve_source="agent",
    )

    assert snap.requested_output_tokens == 2_048
    assert snap.output_reserve_source == "agent"


def test_calculator_uses_approved_profile_reserve_for_separate_input_limit():
    calculator = SafeInputBudgetCalculator()

    snap = calculator.calculate_safe_input_budget(
        capacity_snapshot=_capacity_snapshot(
            context_window_tokens=None,
            max_input_tokens=32_768,
            provider_input_limit_tokens=32_768,
            unknown_capabilities=["tokenizer"],
        ),
        reserve_policy=CapacityReservePolicy(approved_profile_reserve_tokens=512),
    )

    assert snap.provider_input_limit_tokens == 32_768
    assert snap.uncertainty_reserve_tokens == 512
    assert snap.uncertainty_reserve_basis == "approved_profile"
    assert snap.hard_input_budget_tokens == 32_256


def test_calculator_requires_context_window_for_10_percent_reserve():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(UncertaintyReserveBasisUnknown):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=_capacity_snapshot(
                context_window_tokens=None,
                max_input_tokens=32_768,
                provider_input_limit_tokens=32_768,
                unknown_capabilities=["tokenizer"],
            ),
            reserve_policy=CapacityReservePolicy(),
        )


def test_calculator_rejects_requested_output_above_capacity():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(RequestedOutputExceedsCapacity):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=_capacity_snapshot(max_output_tokens=8_000),
            reserve_policy=CapacityReservePolicy(),
            request_overrides=RequestBudgetOverrides(requested_output_tokens=8_192),
        )


def test_calculator_rejects_reserve_larger_than_provider_limit():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(ReserveExceedsCapacity):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=_capacity_snapshot(
                context_window_tokens=10_000,
                max_input_tokens=100,
                provider_input_limit_tokens=100,
                unknown_capabilities=["tokenizer"],
            ),
            reserve_policy=CapacityReservePolicy(),
        )


def test_calculator_rejects_no_safe_input_capacity_after_output_reserve():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(NoSafeInputCapacity):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=_capacity_snapshot(
                context_window_tokens=4_096,
                max_input_tokens=None,
                max_output_tokens=8_192,
                requested_output_tokens=4_096,
                provider_input_limit_tokens=1,
                unknown_capabilities=[],
            ),
            reserve_policy=CapacityReservePolicy(),
        )
