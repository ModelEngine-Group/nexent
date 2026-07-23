"""Canonicalization and content addressing for NL2AGENT catalog snapshots."""

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from typing import Any, Dict


CATALOG_KEYS = (
    "tool_catalog",
    "skill_catalog",
    "registry_results",
    "community_results",
    "official_skills",
)
CATALOG_VERSION_PATTERN = re.compile(r"^catalog_[0-9a-f]{32}$")
CATALOG_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_value(value: Any) -> Any:
    """Normalize JSON values while preserving semantically ordered nested arrays."""
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value).strip()
    return deepcopy(value)


def canonicalize_catalogs(
    catalogs: Dict[str, Any],
) -> Dict[str, list[Dict[str, Any]]]:
    """Return normalized catalogs with deterministic top-level item ordering."""
    if not isinstance(catalogs, dict):
        raise ValueError("catalogs must be an object")
    canonical: Dict[str, list[Dict[str, Any]]] = {}
    for key in CATALOG_KEYS:
        items = catalogs.get(key)
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise ValueError(f"catalog field {key!r} must be a list of objects")
        normalized_items = [_normalize_value(item) for item in items]
        canonical[key] = sorted(normalized_items, key=_canonical_json)
    return canonical


def catalog_hash(catalogs: Dict[str, Any]) -> str:
    """Return the SHA-256 digest of one normalized, metadata-free catalog."""
    canonical = canonicalize_catalogs(catalogs)
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def create_catalog_snapshot(
    catalogs: Dict[str, Any], *, catalog_version: str
) -> Dict[str, Any]:
    """Create the immutable JSONB payload persisted with a new Session."""
    if not CATALOG_VERSION_PATTERN.fullmatch(str(catalog_version or "")):
        raise ValueError("catalog_version must be a generated catalog identifier")
    canonical = canonicalize_catalogs(catalogs)
    return {
        "catalog_version": catalog_version,
        "catalog_hash": catalog_hash(canonical),
        **canonical,
    }


def catalog_identity(snapshot: Dict[str, Any]) -> tuple[str, str]:
    """Validate snapshot metadata and return its immutable identity."""
    if not isinstance(snapshot, dict):
        raise ValueError("catalog snapshot must be an object")
    version = str(snapshot.get("catalog_version") or "")
    digest = str(snapshot.get("catalog_hash") or "").lower()
    if not CATALOG_VERSION_PATTERN.fullmatch(version):
        raise ValueError("catalog snapshot version is missing or malformed")
    if not CATALOG_HASH_PATTERN.fullmatch(digest):
        raise ValueError("catalog snapshot hash is missing or malformed")
    expected = catalog_hash(snapshot)
    if digest != expected:
        raise ValueError("catalog snapshot hash does not match its contents")
    return version, digest


def recommendation_matches_snapshot(
    recommendation: Dict[str, Any], snapshot: Dict[str, Any]
) -> bool:
    """Return whether a persisted recommendation belongs to this exact snapshot."""
    version, digest = catalog_identity(snapshot)
    return (
        recommendation.get("catalog_version") == version
        and recommendation.get("catalog_hash") == digest
    )


def snapshot_catalogs(snapshot: Dict[str, Any]) -> Dict[str, list[Dict[str, Any]]]:
    """Validate a snapshot and project only the provider catalog lists."""
    catalog_identity(snapshot)
    return {key: deepcopy(snapshot[key]) for key in CATALOG_KEYS}


def mcp_recommendation_id(source: str, item: Dict[str, Any]) -> str:
    """Build the stable recommendation identifier used by search and install."""
    if source == "registry":
        server = item.get("server") if isinstance(item.get("server"), dict) else item
        identity = server.get("name") or server.get("id")
    else:
        identity = (
            item.get("communityId")
            or item.get("community_id")
            or item.get("name")
        )
    return f"{source}:{identity}"
