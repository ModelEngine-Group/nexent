"""Trusted catalog lifecycle and stage-only refresh boundary for P3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Mapping, Optional

from consts.capability_profiles import CATALOG, CATALOG_REVISION
from services.model_capacity_health_service import catalog_freshness


@dataclass(frozen=True)
class StagedCatalogCandidate:
    revision: str
    source_identity: str
    staged_at: str
    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]


_lock = Lock()
_candidate: Optional[StagedCatalogCandidate] = None


def _active_profiles() -> dict[str, Any]:
    return {profile.capability_profile_version: profile for profile in CATALOG.values()}


def catalog_status() -> dict[str, Any]:
    profiles = _active_profiles()
    lifecycle: dict[str, int] = {}
    for profile in profiles.values():
        state = catalog_freshness(profile.verified_at)[0]
        lifecycle[state] = lifecycle.get(state, 0) + 1
    with _lock:
        candidate = _candidate
    return {
        "active_revision": CATALOG_REVISION,
        "profile_count": len(profiles),
        "lifecycle_counts": lifecycle,
        "candidate": candidate.__dict__ if candidate else None,
    }


def stage_trusted_candidate(
    document: Mapping[str, Any], *, source_identity: str, signature_verified: bool,
) -> StagedCatalogCandidate:
    """Validate and stage facts only; never changes CATALOG or tenant records."""
    if not signature_verified or not source_identity.strip():
        raise ValueError("catalog_source_untrusted")
    revision = document.get("revision")
    profiles = document.get("profiles")
    if not isinstance(revision, str) or not revision.strip() or revision == CATALOG_REVISION:
        raise ValueError("catalog_revision_invalid")
    if not isinstance(profiles, Mapping):
        raise ValueError("catalog_profiles_invalid")
    normalized: dict[str, Mapping[str, Any]] = {}
    for version, profile in profiles.items():
        if not isinstance(version, str) or not isinstance(profile, Mapping):
            raise ValueError("catalog_profile_invalid")
        required = {"provider", "model_name", "context_window_tokens", "max_output_tokens", "verified_at", "evidence"}
        if not required.issubset(profile) or not profile.get("evidence") or catalog_freshness(profile.get("verified_at"))[0] == "expired":
            raise ValueError("catalog_profile_incomplete")
        if int(profile["context_window_tokens"]) <= int(profile["max_output_tokens"]):
            raise ValueError("catalog_capacity_invalid")
        normalized[version] = profile
    active = _active_profiles()
    active_versions, proposed_versions = set(active), set(normalized)
    candidate = StagedCatalogCandidate(
        revision=revision, source_identity=source_identity,
        staged_at=datetime.now(timezone.utc).isoformat(),
        added=tuple(sorted(proposed_versions - active_versions)),
        changed=tuple(sorted(version for version in proposed_versions & active_versions if normalized[version] != active[version].model_dump())),
        removed=tuple(sorted(active_versions - proposed_versions)),
    )
    global _candidate
    with _lock:
        _candidate = candidate
    return candidate


def refresh_catalog_candidate(
    loader: Callable[[], Mapping[str, Any]], *, source_identity: str,
    verifier: Callable[[Mapping[str, Any]], bool],
) -> StagedCatalogCandidate:
    """Scheduler-safe adapter entrypoint: load, verify, then stage only."""
    document = loader()
    return stage_trusted_candidate(
        document, source_identity=source_identity,
        signature_verified=bool(verifier(document)),
    )
