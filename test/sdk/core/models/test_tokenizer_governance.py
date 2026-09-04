from dataclasses import dataclass

import pytest

from nexent.core.models import tokenizer_registry as registry
from nexent.core.models.tokenizer_registry import (
    TokenizerConformanceFixture,
    TokenizerProfile,
    register,
    register_profile,
    resolve_for_model,
    run_conformance,
)


@dataclass
class ExactFixtureAdapter:
    family: str = "fixture_exact"

    def count_tokens(self, messages):
        return int(messages[0]["expected"])


@pytest.fixture(autouse=True)
def isolated_registry():
    old_registry = dict(registry.REGISTRY)
    old_profiles = dict(registry.PROFILES)
    old_conformance = dict(registry.CONFORMANCE)
    registry.REGISTRY.clear()
    registry.PROFILES.clear()
    registry.CONFORMANCE.clear()
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(old_registry)
    registry.PROFILES.clear()
    registry.PROFILES.update(old_profiles)
    registry.CONFORMANCE.clear()
    registry.CONFORMANCE.update(old_conformance)


def profile(**overrides):
    values = {
        "profile_id": "qwen2.5-text@1",
        "family": "fixture_exact",
        "aliases": ("Qwen2.5-7B-Instruct",),
        "exclusions": ("Qwen2.5-VL-7B-Instruct",),
        "adapter_version": "1.0",
        "package_version": "test-1",
        "fixture_version": "fixtures-1",
        "verification_status": "verified",
        "priority": 10,
    }
    values.update(overrides)
    return TokenizerProfile(**values)


def passing_fixtures(count=100):
    return tuple(
        TokenizerConformanceFixture(
            fixture_id=f"fixture-{index}",
            messages=({"expected": 10 + index},),
            expected_tokens=10 + index,
        )
        for index in range(count)
    )


def test_ac_p1_004_unique_verified_conforming_adapter_is_exact():
    adapter = ExactFixtureAdapter()
    register(adapter)
    register_profile(profile())
    report = run_conformance(
        adapter,
        passing_fixtures(),
        adapter_version="1.0",
        fixture_version="fixtures-1",
    )

    result = resolve_for_model("silicon", "Qwen2.5-7B-Instruct")

    assert report.passed
    assert result.counting_mode == "exact"
    assert result.profile_id == "qwen2.5-text@1"
    assert result.reason == "verified_profile_and_conformance"


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("missing_adapter", "tokenizer_adapter_unavailable"),
        ("unverified", "tokenizer_profile_unverified"),
        ("missing_report", "tokenizer_conformance_missing"),
        ("failed_report", "tokenizer_conformance_failed"),
        ("stale_report", "tokenizer_conformance_stale"),
    ],
)
def test_ac_p1_004_non_verified_paths_fall_back(setup, reason):
    adapter = ExactFixtureAdapter()
    if setup != "missing_adapter":
        register(adapter)
    register_profile(profile(verification_status="unverified" if setup == "unverified" else "verified"))
    if setup in {"failed_report", "stale_report"}:
        run_conformance(
            adapter,
            passing_fixtures(1 if setup == "failed_report" else 100),
            adapter_version="old" if setup == "stale_report" else "1.0",
            fixture_version="fixtures-1",
        )

    result = resolve_for_model("silicon", "Qwen2.5-7B-Instruct")

    assert result.counting_mode == "estimated"
    assert result.reason == reason


def test_ac_p1_004_exclusion_wins_over_family_alias():
    register_profile(profile())

    result = resolve_for_model("silicon", "Qwen2.5-VL-7B-Instruct")

    assert result.counting_mode == "estimated"
    assert result.reason == "tokenizer_profile_not_found"


def test_ac_p1_004_equal_priority_matches_are_ambiguous():
    register_profile(profile())
    register_profile(profile(profile_id="qwen2.5-other@1"))

    result = resolve_for_model("silicon", "Qwen2.5-7B-Instruct")

    assert result.counting_mode == "estimated"
    assert result.reason == "tokenizer_profile_ambiguous"
    assert result.candidates == ("qwen2.5-other@1", "qwen2.5-text@1")


def test_ac_p1_004_conformance_requires_full_fixture_floor():
    report = run_conformance(
        ExactFixtureAdapter(),
        passing_fixtures(99),
        adapter_version="1.0",
        fixture_version="fixtures-1",
    )

    assert not report.passed
