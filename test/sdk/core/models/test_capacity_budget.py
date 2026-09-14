"""Contract tests for the canonical Context Budget V2 snapshot."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

_SDK_ROOT = Path(__file__).resolve().parents[4] / "sdk" / "nexent"
for pkg_name, pkg_path in (("nexent", _SDK_ROOT), ("nexent.core", _SDK_ROOT / "core"), ("nexent.core.models", _SDK_ROOT / "core" / "models")):
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

capacity_resolver = _load("nexent.core.models.capacity_resolver", _SDK_ROOT / "core" / "models" / "capacity_resolver.py")
budget = _load("nexent.core.models.capacity_budget", _SDK_ROOT / "core" / "models" / "capacity_budget.py")

def _capacity(**overrides):
    payload = {
        "provider": "openai", "model_name": "gpt-4o",
        "context_window_tokens": 128_000, "max_input_tokens": None,
        "max_output_tokens": 16_384, "default_output_reserve_tokens": 4_096,
        "requested_output_tokens": 4_096, "provider_input_limit_tokens": 123_904,
        "tokenizer_family": "o200k_base", "counting_mode": "estimated",
        "unknown_capabilities": ["tokenizer"],
        "field_sources": {"context_window_tokens": "profile"},
        "capability_profile_version": "openai/gpt-4o@1", "fingerprint": "w1fingerprint",
    }
    payload.update(overrides)
    return capacity_resolver.ModelCapacitySnapshot(**payload)

def _calculate(**policy_overrides):
    return budget.ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=_capacity(),
        reserve_policy=budget.CapacityReservePolicy(**policy_overrides),
    )

def test_v2_defaults_use_effective_limit_for_trigger_and_target():
    snapshot = _calculate()
    assert snapshot.schema_version == 2
    assert snapshot.effective_input_limit_tokens == 123_904
    assert snapshot.compaction_trigger_threshold_tokens == 99_123
    assert snapshot.compaction_target_tokens == 74_342
    assert not hasattr(snapshot, "hard_input_budget_tokens")
    assert budget.validate_context_budget_snapshot(snapshot) is snapshot

def test_custom_trigger_does_not_change_default_target():
    snapshot = _calculate(compaction_trigger_ratio=0.75, compaction_trigger_ratio_source="tenant_config")
    assert snapshot.compaction_trigger_threshold_tokens == 92_928
    assert snapshot.compaction_target_tokens == 74_342

@pytest.mark.parametrize("value", [0, 1.01])
def test_invalid_trigger_ratio_is_rejected(value):
    with pytest.raises(ValidationError):
        budget.CapacityReservePolicy(compaction_trigger_ratio=value)

def _legacy_payload():
    payload = {
        "resolver_version": "1.0.0", "w1_fingerprint": "w1fingerprint",
        "provider": "openai", "model_name": "gpt-4o",
        "requested_output_tokens": 4_096, "output_reserve_source": "model_default",
        "provider_input_limit_tokens": 123_904,
        "uncertainty_reserve_tokens": 12_800,
        "uncertainty_reserve_basis": "context_window_10pct",
        "approved_profile_reserve_tokens": None,
        "soft_limit_ratio": 0.75, "soft_limit_ratio_source": "tenant_config",
        "soft_input_budget_tokens": 92_928, "hard_input_budget_tokens": 1,
        "field_sources": {"soft_limit_ratio": "tenant_config"}, "warnings": [],
    }
    payload["fingerprint"] = budget._compute_legacy_w2_fingerprint(payload)
    return payload

def test_verified_v1_converts_to_v2_and_ignores_hard_budget():
    snapshot = budget.parse_context_budget_snapshot(_legacy_payload())
    assert snapshot.schema_version == 2
    assert snapshot.compaction_trigger_threshold_tokens == 92_928
    assert snapshot.compaction_target_tokens == 74_342
    assert snapshot.compaction_target_tokens != 1
    assert "legacy_w2_v1_payload_migrated" in snapshot.warnings

def test_invalid_v1_fingerprint_is_rejected():
    payload = _legacy_payload()
    payload["hard_input_budget_tokens"] = 2
    with pytest.raises(budget.ContextBudgetFingerprintMismatch):
        budget.parse_context_budget_snapshot(payload)

def test_request_override_recomputes_effective_limit():
    snapshot = budget.ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=_capacity(), reserve_policy=budget.CapacityReservePolicy(),
        request_overrides=budget.RequestBudgetOverrides(requested_output_tokens=8_192),
    )
    assert snapshot.effective_input_limit_tokens == 119_808
    assert snapshot.output_reserve_source == "request"

def test_no_effective_capacity_is_rejected():
    calculator = budget.ContextBudgetCalculator()
    capacity_snapshot = _capacity(
        context_window_tokens=4_096,
        max_input_tokens=None,
        requested_output_tokens=4_096,
        unknown_capabilities=[],
    )
    reserve_policy = budget.CapacityReservePolicy()
    with pytest.raises(budget.NoSafeInputCapacity):
        calculator.calculate_context_budget(
            capacity_snapshot=capacity_snapshot,
            reserve_policy=reserve_policy,
        )
