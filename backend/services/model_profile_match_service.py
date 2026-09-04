"""Independent, versioned capacity and tokenizer resolution for model setup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Mapping, Optional

from consts.capability_profiles import CATALOG
from nexent.core.models.model_identity import MATCHER_VERSION, parse_model_identity
from nexent.core.models.tokenizer_registry import resolve_for_model
from services.model_capacity_suggestion_service import CapacitySuggestionResult, suggest_capacity


MATCH_SCHEMA_VERSION = 1
logger = logging.getLogger("model_profile_match_service")


@dataclass(frozen=True)
class ProfileMatch:
    selected_profile: Optional[str]
    confidence: Optional[str]
    source: str
    reason: str
    matcher_version: str
    candidates: tuple[str, ...] = ()
    auto_applicable: bool = False


@dataclass(frozen=True)
class ModelProfileResolution:
    canonical_model_id: str
    identity_metadata: Mapping[str, Any]
    capacity_match: ProfileMatch
    tokenizer_match: ProfileMatch
    tokenizer_family: Optional[str]
    tokenizer_counting_mode: str
    capacity_suggestions: Mapping[str, Any]


def _evaluated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capacity_profile(version: Optional[str]):
    if not version:
        return None
    return next(
        (profile for profile in CATALOG.values() if profile.capability_profile_version == version),
        None,
    )


def resolve_model_profiles(
    *,
    model_name: str,
    provider: Optional[str],
    base_url: Optional[str],
    model_type: Optional[str],
    capacity_result: Optional[CapacitySuggestionResult] = None,
) -> ModelProfileResolution:
    capacity = capacity_result or suggest_capacity(
        model_name=model_name,
        base_url=base_url,
        provider_hint=provider,
        model_type=model_type,
        catalog=CATALOG,
    )
    identity_provider = capacity.suggested_provider or provider
    identity = parse_model_identity(model_name, identity_provider)
    matched_profile = _capacity_profile(capacity.capability_profile_version)
    identity_candidates = tuple(
        sorted(
            profile.capability_profile_version
            for (catalog_provider, _), profile in CATALOG.items()
            if (not identity_provider or catalog_provider == identity_provider)
            and parse_model_identity(profile.model_name, catalog_provider).family
            == identity.family
        )
    ) if identity.family else ()
    unresolved_candidates = () if matched_profile else identity_candidates
    capacity_match = ProfileMatch(
        selected_profile=capacity.capability_profile_version,
        confidence=capacity.match_confidence.value if capacity.match_confidence else None,
        source="catalog" if capacity.capability_profile_version else "unknown",
        reason=(
            "capacity_profile_ambiguous"
            if len(unresolved_candidates) > 1
            else capacity.match_kind.value
        ),
        matcher_version=MATCHER_VERSION,
        candidates=unresolved_candidates,
        auto_applicable=bool(
            matched_profile
            and matched_profile.auto_applicable
            and capacity.match_confidence
            and capacity.match_confidence.value == "high"
        ),
    )
    tokenizer = resolve_for_model(identity_provider, model_name)
    tokenizer_match = ProfileMatch(
        selected_profile=tokenizer.profile_id,
        confidence=tokenizer.confidence,
        source="catalog" if tokenizer.source == "profile" else "unknown",
        reason=tokenizer.reason,
        matcher_version=tokenizer.matcher_version,
        candidates=tokenizer.candidates,
        auto_applicable=tokenizer.counting_mode == "exact",
    )
    capacity_suggestions = (
        asdict(capacity.suggestions) if capacity.suggestions is not None else {}
    )
    # P1 deliberately separates the two matchers. A capacity catalog row may
    # retain a legacy tokenizer hint for compatibility, but it is not an
    # automatic tokenizer fact without an independently verified match.
    capacity_suggestions["tokenizer_family"] = (
        tokenizer.family if tokenizer.counting_mode == "exact" else None
    )
    identity_metadata = {
        "schema_version": MATCH_SCHEMA_VERSION,
        "canonical_id": identity.canonical_id,
        "resolved": identity.resolved,
        "ambiguity": identity.ambiguous or len(unresolved_candidates) > 1,
        "confidence": identity.confidence,
        "attributes": {
            key: value
            for key, value in identity.model_dump().items()
            if key
            not in {
                "raw_model_id",
                "canonical_id",
                "resolved",
                "ambiguous",
                "confidence",
                "matcher_version",
                "evidence",
                "candidates",
            }
        },
        "evidence": list(identity.evidence),
        "candidates": list(unresolved_candidates or identity.candidates),
        "matcher_version": identity.matcher_version,
        "evaluated_at": _evaluated_at(),
    }
    result = ModelProfileResolution(
        canonical_model_id=identity.canonical_id,
        identity_metadata=identity_metadata,
        capacity_match=capacity_match,
        tokenizer_match=tokenizer_match,
        tokenizer_family=tokenizer.family,
        tokenizer_counting_mode=tokenizer.counting_mode,
        capacity_suggestions=capacity_suggestions,
    )
    logger.info(
        "model_profile_resolution canonical_id=%s matcher_version=%s capacity_profile=%s capacity_confidence=%s capacity_reason=%s tokenizer_profile=%s tokenizer_confidence=%s tokenizer_reason=%s",
        result.canonical_model_id,
        MATCHER_VERSION,
        result.capacity_match.selected_profile or "none",
        result.capacity_match.confidence or "unknown",
        result.capacity_match.reason,
        result.tokenizer_match.selected_profile or "none",
        result.tokenizer_match.confidence or "unknown",
        result.tokenizer_match.reason,
    )
    return result


def serialize_profile_match(match: ProfileMatch) -> dict[str, Any]:
    return {
        "schema_version": MATCH_SCHEMA_VERSION,
        **asdict(match),
        "candidates": list(match.candidates),
        "evaluated_at": _evaluated_at(),
    }
