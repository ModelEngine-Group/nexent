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
SafeInputBudgetCalculator = _capacity_budget.SafeInputBudgetCalculator
W2_RESOLVER_VERSION = _capacity_budget.W2_RESOLVER_VERSION
compute_w2_fingerprint = _capacity_budget.compute_w2_fingerprint


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


def test_calculator_body_is_gated_until_w2_adr_acceptance():
    calculator = SafeInputBudgetCalculator()

    with pytest.raises(NotImplementedError):
        calculator.calculate_safe_input_budget(
            capacity_snapshot=None,
            reserve_policy=CapacityReservePolicy(),
        )
