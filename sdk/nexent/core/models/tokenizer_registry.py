from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Literal, Optional, Protocol, Sequence, Tuple, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .capacity_resolver import CountingMode
from .model_identity import MATCHER_VERSION, identities_are_safe_aliases, parse_model_identity

logger = logging.getLogger("tokenizer_registry")


TOKENIZER_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,49}$")


def is_valid_family_identifier(family: str) -> bool:
    """Validate against the naming convention fixed by W1 ADR Decision 1."""
    return bool(TOKENIZER_FAMILY_PATTERN.match(family))


@runtime_checkable
class TokenizerAdapter(Protocol):
    """Contract for a tokenizer-family counting implementation.

    Implementations must be deterministic, side-effect free, and threadsafe.
    Promotion from `estimated` to `exact` requires meeting the accuracy gate
    defined in W1 ADR Decision 1 (>=100-message fixture, MAE <= 0.5%, max single
    error <= 2%).
    """

    family: str

    def count_tokens(self, messages: Sequence[dict]) -> int: ...


class FallbackEstimator:
    """Generic character-to-token estimator used when no family adapter matches.

    Never marked `exact`. Purpose: avoid hard failures when a catalog entry has
    an unknown tokenizer family — operators always see a budget number, just one
    that triggers W2's 10% uncertainty reserve.
    """

    family = "_fallback"

    def count_tokens(self, messages: Sequence[dict]) -> int:
        encoded = json.dumps(list(messages), ensure_ascii=False)
        return max(1, len(encoded) // 4)


FALLBACK: TokenizerAdapter = FallbackEstimator()


REGISTRY: Dict[str, TokenizerAdapter] = {}


class TokenizerConformanceFixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    messages: Tuple[dict, ...]
    expected_tokens: int = Field(gt=0)


class TokenizerConformanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: str
    adapter_version: str
    fixture_version: str
    sample_count: int
    mean_absolute_error_ratio: float
    max_error_ratio: float
    passed: bool


class TokenizerProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    family: str
    aliases: Tuple[str, ...]
    exclusions: Tuple[str, ...] = ()
    adapter_version: str
    package_version: str
    fixture_version: str
    priority: int = 0
    matcher_version: str = MATCHER_VERSION
    verification_status: Literal["verified", "unverified"] = "unverified"


class TokenizerMatchResult(BaseModel):
    adapter: TokenizerAdapter = Field(exclude=True)
    counting_mode: CountingMode
    profile_id: Optional[str] = None
    family: Optional[str] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    source: Literal["profile", "fallback"]
    matcher_version: str = MATCHER_VERSION
    reason: str
    candidates: Tuple[str, ...] = ()

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


PROFILES: Dict[str, TokenizerProfile] = {}
CONFORMANCE: Dict[str, TokenizerConformanceReport] = {}


def register(adapter: TokenizerAdapter) -> None:
    """Register a verified adapter. Called once at import time by adapter modules."""
    family = adapter.family
    if not is_valid_family_identifier(family):
        raise ValueError(
            f"Tokenizer family {family!r} does not match required pattern "
            f"{TOKENIZER_FAMILY_PATTERN.pattern}"
        )
    if family in REGISTRY:
        raise ValueError(f"Tokenizer family {family!r} is already registered")
    REGISTRY[family] = adapter


def register_profile(profile: TokenizerProfile) -> None:
    if not is_valid_family_identifier(profile.family):
        raise ValueError(f"Invalid tokenizer family {profile.family!r}")
    if profile.profile_id in PROFILES:
        raise ValueError(f"Tokenizer profile {profile.profile_id!r} is already registered")
    if not profile.aliases:
        raise ValueError("Tokenizer profile requires at least one alias")
    PROFILES[profile.profile_id] = profile


def run_conformance(
    adapter: TokenizerAdapter,
    fixtures: Sequence[TokenizerConformanceFixture],
    *,
    adapter_version: str,
    fixture_version: str,
    minimum_samples: int = 100,
    maximum_mean_error_ratio: float = 0.005,
    maximum_single_error_ratio: float = 0.02,
) -> TokenizerConformanceReport:
    errors: List[float] = []
    for fixture in fixtures:
        actual = adapter.count_tokens(fixture.messages)
        errors.append(abs(actual - fixture.expected_tokens) / fixture.expected_tokens)
    mean_error = sum(errors) / len(errors) if errors else 1.0
    max_error = max(errors, default=1.0)
    report = TokenizerConformanceReport(
        family=adapter.family,
        adapter_version=adapter_version,
        fixture_version=fixture_version,
        sample_count=len(fixtures),
        mean_absolute_error_ratio=mean_error,
        max_error_ratio=max_error,
        passed=(
            len(fixtures) >= minimum_samples
            and mean_error <= maximum_mean_error_ratio
            and max_error <= maximum_single_error_ratio
        ),
    )
    CONFORMANCE[adapter.family] = report
    return report


def _profile_matches(profile: TokenizerProfile, provider: Optional[str], model_name: str) -> bool:
    requested = parse_model_identity(model_name, provider)
    if any(
        identities_are_safe_aliases(requested, parse_model_identity(exclusion, provider))
        for exclusion in profile.exclusions
    ):
        return False
    return any(
        identities_are_safe_aliases(requested, parse_model_identity(alias, provider))
        for alias in profile.aliases
    )


def resolve_for_model(provider: Optional[str], model_name: str) -> TokenizerMatchResult:
    """Resolve a verified profile independently from capacity matching."""
    matches = [
        profile
        for profile in PROFILES.values()
        if profile.matcher_version == MATCHER_VERSION
        and _profile_matches(profile, provider, model_name)
    ]
    if not matches:
        return TokenizerMatchResult(
            adapter=FALLBACK,
            counting_mode="estimated",
            source="fallback",
            reason="tokenizer_profile_not_found",
        )

    highest_priority = max(profile.priority for profile in matches)
    winners = [profile for profile in matches if profile.priority == highest_priority]
    if len(winners) != 1:
        return TokenizerMatchResult(
            adapter=FALLBACK,
            counting_mode="estimated",
            source="fallback",
            reason="tokenizer_profile_ambiguous",
            candidates=tuple(sorted(profile.profile_id for profile in winners)),
        )

    profile = winners[0]
    adapter = REGISTRY.get(profile.family)
    if adapter is None:
        reason = "tokenizer_adapter_unavailable"
    elif profile.verification_status != "verified":
        reason = "tokenizer_profile_unverified"
    else:
        report = CONFORMANCE.get(profile.family)
        reason = (
            "tokenizer_conformance_missing"
            if report is None
            else "tokenizer_conformance_failed"
            if not report.passed
            else ""
        )
        if report and (
            report.adapter_version != profile.adapter_version
            or report.fixture_version != profile.fixture_version
        ):
            reason = "tokenizer_conformance_stale"

    if reason:
        return TokenizerMatchResult(
            adapter=FALLBACK,
            counting_mode="estimated",
            profile_id=profile.profile_id,
            family=profile.family,
            confidence="low",
            source="fallback",
            reason=reason,
        )
    return TokenizerMatchResult(
        adapter=adapter,
        counting_mode="exact",
        profile_id=profile.profile_id,
        family=profile.family,
        confidence="high",
        source="profile",
        reason="verified_profile_and_conformance",
    )


def resolve(family: Optional[str]) -> Tuple[TokenizerAdapter, CountingMode]:
    """Return (adapter, counting_mode) for the requested tokenizer family.

    Returns FALLBACK with `estimated` when family is None or unmapped. Returns
    the registered adapter with `exact` when a verified mapping exists.
    """
    if family is None or family not in REGISTRY:
        return FALLBACK, "estimated"
    return REGISTRY[family], "exact"
