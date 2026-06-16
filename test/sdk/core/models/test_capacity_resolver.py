"""Unit tests for ModelCapacityResolver (W1)."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# Build a minimal `nexent.core.models` package skeleton in sys.modules so we can
# import the capacity_resolver and tokenizer_registry modules without triggering
# the SDK's full __init__ chain (which pulls smolagents, mem0, etc.).
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
_load(
    "nexent.core.models.tokenizer_registry",
    _SDK_ROOT / "core" / "models" / "tokenizer_registry.py",
)

CapabilityProfile = _capacity_resolver.CapabilityProfile
InvalidCapacityConfiguration = _capacity_resolver.InvalidCapacityConfiguration
ModelCapacitySnapshot = _capacity_resolver.ModelCapacitySnapshot
ProviderCapabilityUnknown = _capacity_resolver.ProviderCapabilityUnknown
RESOLVER_VERSION = _capacity_resolver.RESOLVER_VERSION
RequestedOutputExceedsCap = _capacity_resolver.RequestedOutputExceedsCap
compute_fingerprint = _capacity_resolver.compute_fingerprint
resolve_capacity = _capacity_resolver.resolve_capacity

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def _gpt4o_profile() -> CapabilityProfile:
    return CapabilityProfile(
        provider="openai",
        model_name="gpt-4o",
        capability_profile_version="openai/gpt-4o@1",
        window_shape="combined",
        context_window_tokens=128_000,
        max_output_tokens=16_384,
        default_output_reserve_tokens=4_096,
        tokenizer_family="o200k_base",
    )


def _separate_limit_profile() -> CapabilityProfile:
    """A synthetic profile exercising the separate-input-limit path.

    No real day-one model uses this shape, but the budget code must support it.
    """
    return CapabilityProfile(
        provider="testprovider",
        model_name="separate-limit-model",
        capability_profile_version="testprovider/separate@1",
        window_shape="separate",
        context_window_tokens=None,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        default_output_reserve_tokens=1_024,
        tokenizer_family=None,
    )


def _catalog(*profiles: CapabilityProfile) -> dict:
    return {(p.provider, p.model_name): p for p in profiles}


def test_known_profile_no_overrides_builds_snapshot():
    catalog = _catalog(_gpt4o_profile())

    snap = resolve_capacity(
        model_id="gpt-4o",
        provider="openai",
        capability_profiles=catalog,
    )

    assert isinstance(snap, ModelCapacitySnapshot)
    assert snap.provider == "openai"
    assert snap.model_name == "gpt-4o"
    assert snap.context_window_tokens == 128_000
    assert snap.max_output_tokens == 16_384
    assert snap.default_output_reserve_tokens == 4_096
    assert snap.requested_output_tokens == 4_096  # defaulted from reserve
    assert snap.provider_input_limit_tokens == 128_000 - 4_096
    assert snap.tokenizer_family == "o200k_base"
    assert snap.counting_mode == "estimated"  # no adapter registered yet
    assert snap.capability_profile_version == "openai/gpt-4o@1"
    assert snap.resolver_version == RESOLVER_VERSION
    assert "capability_profile_missing" not in snap.unknown_capabilities
    # Fields the profile defined come from "profile"; fields the profile left
    # null are tagged "unknown". None should come from "operator" when no
    # overrides are supplied.
    assert snap.field_sources["context_window_tokens"] == "profile"
    assert snap.field_sources["max_output_tokens"] == "profile"
    assert snap.field_sources["max_input_tokens"] == "unknown"  # gpt-4o has no separate input limit
    assert "operator" not in snap.field_sources.values()
    assert len(snap.fingerprint) == 32


def test_operator_override_wins_over_profile():
    catalog = _catalog(_gpt4o_profile())

    snap = resolve_capacity(
        model_id="gpt-4o",
        provider="openai",
        operator_overrides={"max_output_tokens": 8_192},
        capability_profiles=catalog,
    )

    assert snap.max_output_tokens == 8_192
    assert snap.field_sources["max_output_tokens"] == "operator"
    assert snap.field_sources["context_window_tokens"] == "profile"


def test_uncataloged_model_with_operator_overrides_resolves():
    snap = resolve_capacity(
        model_id="custom-model",
        provider="self-hosted",
        operator_overrides={
            "context_window_tokens": 32_000,
            "max_output_tokens": 4_000,
            "default_output_reserve_tokens": 1_000,
        },
        capability_profiles={},
    )

    assert snap.context_window_tokens == 32_000
    assert snap.requested_output_tokens == 1_000
    assert snap.provider_input_limit_tokens == 32_000 - 1_000
    assert snap.field_sources["context_window_tokens"] == "operator"
    assert snap.capability_profile_version is None
    assert "capability_profile_missing" in snap.unknown_capabilities


def test_uncataloged_model_without_hard_capacity_is_rejected():
    with pytest.raises(ProviderCapabilityUnknown):
        resolve_capacity(
            model_id="ghost-model",
            provider="unknown-provider",
            capability_profiles={},
        )


def test_max_output_exceeding_context_window_is_rejected():
    bad_profile = CapabilityProfile(
        provider="x", model_name="y", capability_profile_version="x/y@1",
        window_shape="combined", context_window_tokens=4_096,
        max_output_tokens=8_192, default_output_reserve_tokens=1_024,
    )
    with pytest.raises(InvalidCapacityConfiguration):
        resolve_capacity(
            model_id="y",
            provider="x",
            capability_profiles=_catalog(bad_profile),
        )


def test_requested_output_exceeding_max_output_is_rejected():
    catalog = _catalog(_gpt4o_profile())
    with pytest.raises(RequestedOutputExceedsCap):
        resolve_capacity(
            model_id="gpt-4o",
            provider="openai",
            requested_output_tokens=32_000,
            capability_profiles=catalog,
        )


def test_requested_output_defaults_to_profile_reserve():
    catalog = _catalog(_gpt4o_profile())
    snap = resolve_capacity(
        model_id="gpt-4o",
        provider="openai",
        capability_profiles=catalog,
    )
    assert snap.requested_output_tokens == 4_096


def test_separate_input_limit_uses_max_input_tokens():
    catalog = _catalog(_separate_limit_profile())
    snap = resolve_capacity(
        model_id="separate-limit-model",
        provider="testprovider",
        capability_profiles=catalog,
    )
    assert snap.max_input_tokens == 32_768
    assert snap.provider_input_limit_tokens == 32_768


def test_separate_input_limit_with_combined_takes_minimum():
    profile = CapabilityProfile(
        provider="x", model_name="y", capability_profile_version="x/y@1",
        window_shape="combined", context_window_tokens=128_000,
        max_input_tokens=16_000, max_output_tokens=4_096,
        default_output_reserve_tokens=512,
    )
    snap = resolve_capacity(
        model_id="y", provider="x",
        capability_profiles=_catalog(profile),
    )
    assert snap.provider_input_limit_tokens == 16_000


def test_snapshot_is_immutable():
    catalog = _catalog(_gpt4o_profile())
    snap = resolve_capacity(
        model_id="gpt-4o", provider="openai",
        capability_profiles=catalog,
    )
    with pytest.raises(ValidationError):
        snap.provider = "mutated"


def test_fingerprint_recomputes_identically():
    catalog = _catalog(_gpt4o_profile())
    snap = resolve_capacity(
        model_id="gpt-4o", provider="openai",
        capability_profiles=catalog,
    )

    recomputed = compute_fingerprint(
        resolver_version=snap.resolver_version,
        provider=snap.provider,
        model_name=snap.model_name,
        context_window_tokens=snap.context_window_tokens,
        max_input_tokens=snap.max_input_tokens,
        max_output_tokens=snap.max_output_tokens,
        default_output_reserve_tokens=snap.default_output_reserve_tokens,
        requested_output_tokens=snap.requested_output_tokens,
        provider_input_limit_tokens=snap.provider_input_limit_tokens,
        tokenizer_family=snap.tokenizer_family,
        counting_mode=snap.counting_mode,
        capability_profile_version=snap.capability_profile_version,
        unknown_capabilities=snap.unknown_capabilities,
        field_sources=dict(snap.field_sources),
    )

    assert snap.fingerprint == recomputed


def test_fingerprint_changes_when_request_changes():
    catalog = _catalog(_gpt4o_profile())
    snap_a = resolve_capacity(
        model_id="gpt-4o", provider="openai",
        requested_output_tokens=2_000,
        capability_profiles=catalog,
    )
    snap_b = resolve_capacity(
        model_id="gpt-4o", provider="openai",
        requested_output_tokens=4_000,
        capability_profiles=catalog,
    )
    assert snap_a.fingerprint != snap_b.fingerprint


def test_negative_or_zero_capacity_is_rejected():
    with pytest.raises(InvalidCapacityConfiguration):
        resolve_capacity(
            model_id="bad", provider="x",
            operator_overrides={"context_window_tokens": 0},
            capability_profiles={},
        )
    with pytest.raises(InvalidCapacityConfiguration):
        resolve_capacity(
            model_id="bad", provider="x",
            operator_overrides={"context_window_tokens": -100},
            capability_profiles={},
        )


def test_requested_output_must_be_positive():
    catalog = _catalog(_gpt4o_profile())
    with pytest.raises(InvalidCapacityConfiguration):
        resolve_capacity(
            model_id="gpt-4o", provider="openai",
            requested_output_tokens=0,
            capability_profiles=catalog,
        )


def test_unknown_capabilities_includes_tokenizer_when_estimated():
    catalog = _catalog(_gpt4o_profile())
    snap = resolve_capacity(
        model_id="gpt-4o", provider="openai",
        capability_profiles=catalog,
    )
    assert "tokenizer" in snap.unknown_capabilities
