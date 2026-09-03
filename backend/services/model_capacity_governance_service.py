"""Field-level capacity provenance, catalog adoption, and legacy normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from consts.exceptions import ModelCapacityConfigError
from services.model_capacity_validation_service import CAPACITY_FIELDS, CAPACITY_MODEL_TYPES


GOVERNANCE_SCHEMA_VERSION = 1
GOVERNED_FIELDS = (*CAPACITY_FIELDS, "tokenizer_family")
FIELD_SOURCES = frozenset({"catalog", "provider", "operator", "legacy", "unknown"})
_LEGACY_SOURCE_MAP = {
    "profile": "catalog",
    "provider_candidate": "provider",
    "operator": "operator",
    "legacy": "legacy",
    "default": "unknown",
    "unknown": "unknown",
}
_ROW_SOURCE_MAP = {
    "catalog": "profile",
    "provider": "provider_candidate",
    "operator": "operator",
    "legacy": "legacy",
    "unknown": "unknown",
}


@dataclass(frozen=True)
class GovernanceMergeResult:
    values: dict[str, Any]
    metadata: dict[str, Any]
    audit_delta: tuple[dict[str, Any], ...]
    row_capacity_source: Optional[str]
    capability_profile_version: Optional[str]


def _fail(reason: str, message: str, *, field: Optional[str] = None) -> None:
    raise ModelCapacityConfigError(reason, message, field=field)


def normalize_legacy_capacity_ingress(
    payload: Mapping[str, Any],
    *,
    explicit_fields: Iterable[str],
) -> tuple[dict[str, Any], set[str], bool]:
    """Normalize legacy max_tokens once and remove it as a capacity write authority."""
    normalized = dict(payload)
    explicit = set(explicit_fields)
    model_type = normalized.get("model_type")
    if model_type not in CAPACITY_MODEL_TYPES:
        return normalized, explicit, False

    legacy_explicit = "max_tokens" in explicit
    output_explicit = "max_output_tokens" in explicit
    legacy_value = normalized.get("max_tokens")
    output_value = normalized.get("max_output_tokens")
    used_legacy = False

    provider_capacity = normalized.get("capacity_source") == "provider_candidate"
    if (
        legacy_explicit
        and output_explicit
        and legacy_value is not None
        and output_value is not None
        and provider_capacity
    ):
        # Provider adapters retain `max_tokens` as a generation default for
        # compatibility while exposing authoritative capacity in
        # `max_output_tokens`. It is not a second capacity declaration.
        pass
    elif legacy_explicit and output_explicit and legacy_value is not None and output_value is not None:
        if legacy_value != output_value:
            _fail(
                "capacity_legacy_conflict",
                "max_tokens conflicts with max_output_tokens",
                field="max_output_tokens",
            )
    elif legacy_explicit and not output_explicit and legacy_value not in (None, 0):
        normalized["max_output_tokens"] = legacy_value
        explicit.add("max_output_tokens")
        used_legacy = True

    normalized.pop("max_tokens", None)
    explicit.discard("max_tokens")
    return normalized, explicit, used_legacy


def _valid_metadata(metadata: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not metadata or metadata.get("schema_version") != GOVERNANCE_SCHEMA_VERSION:
        return {"schema_version": GOVERNANCE_SCHEMA_VERSION, "fields": {}}
    fields = {}
    for field, item in (metadata.get("fields") or {}).items():
        if field not in GOVERNED_FIELDS or not isinstance(item, Mapping):
            continue
        source = item.get("source")
        if source not in FIELD_SOURCES:
            continue
        fields[field] = dict(item)
    return {"schema_version": GOVERNANCE_SCHEMA_VERSION, "fields": fields}


def derive_legacy_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return response-only metadata for an old row without mutating it."""
    metadata = _valid_metadata(record.get("capacity_field_metadata"))
    if metadata["fields"]:
        return metadata
    source = _LEGACY_SOURCE_MAP.get(record.get("capacity_source"), "legacy")
    profile_version = record.get("capability_profile_version")
    for field in GOVERNED_FIELDS:
        if record.get(field) is None:
            continue
        metadata["fields"][field] = {
            "source": source,
            "confidence": "unknown" if source in {"legacy", "operator", "unknown"} else "medium",
            **({"profile_version": profile_version} if profile_version else {}),
        }
    return metadata


def _field_metadata(
    source: str,
    *,
    profile_version: Optional[str] = None,
    evidence_id: Optional[str] = None,
    verified_at: Optional[str] = None,
) -> dict[str, Any]:
    item = {
        "source": source,
        "confidence": "high" if source == "catalog" else "medium" if source == "provider" else "unknown",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if profile_version:
        item["profile_version"] = profile_version
    if evidence_id:
        item["evidence_id"] = evidence_id
    if verified_at:
        item["verified_at"] = verified_at
    return item


def _project_row_source(fields: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    sources = {item.get("source") for item in fields.values()}
    for source in ("operator", "provider", "catalog", "legacy", "unknown"):
        if source in sources:
            return _ROW_SOURCE_MAP[source]
    return None


def merge_capacity_governance(
    payload: Mapping[str, Any],
    *,
    explicit_fields: Iterable[str],
    existing: Optional[Mapping[str, Any]] = None,
    accepted_profile_version: Optional[str] = None,
    accepted_profile_fields: Iterable[str] = (),
    provider_fields: Iterable[str] = (),
    profile_evidence_id: Optional[str] = None,
    profile_verified_at: Optional[str] = None,
    legacy_ingress_used: bool = False,
) -> GovernanceMergeResult:
    """Merge explicitly changed fields and preserve provenance for all others."""
    previous = dict(existing or {})
    values = dict(previous)
    values.update(payload)
    explicit = set(explicit_fields)
    metadata = derive_legacy_metadata(previous) if existing else _valid_metadata(None)
    fields = dict(metadata["fields"])
    accepted = set(accepted_profile_fields)
    provider = set(provider_fields)
    audit: list[dict[str, Any]] = []

    for field in GOVERNED_FIELDS:
        if field not in explicit:
            continue
        old_value = previous.get(field)
        new_value = payload.get(field)
        previous_source = (fields.get(field) or {}).get("source")
        provenance_changes = new_value is not None and (
            (
                field in accepted
                and accepted_profile_version is not None
                and previous_source != "catalog"
            )
            or (field in provider and previous_source != "provider")
        )
        if existing and new_value == old_value and not provenance_changes:
            continue
        if field in provider and previous_source == "operator":
            values[field] = old_value
            continue
        if new_value is None:
            fields.pop(field, None)
            new_source = "unknown"
        elif field in provider:
            new_source = "provider"
            fields[field] = _field_metadata(new_source)
        elif field in accepted and accepted_profile_version:
            new_source = "catalog"
            fields[field] = _field_metadata(
                new_source,
                profile_version=accepted_profile_version,
                evidence_id=profile_evidence_id,
                verified_at=profile_verified_at,
            )
        elif legacy_ingress_used and field == "max_output_tokens":
            new_source = "legacy"
            fields[field] = _field_metadata(new_source)
        else:
            new_source = "operator"
            fields[field] = _field_metadata(new_source)
        audit.append(
            {
                "field": field,
                "previous_source": previous_source,
                "new_source": new_source,
                "value_changed": old_value != new_value,
            }
        )

    metadata = {"schema_version": GOVERNANCE_SCHEMA_VERSION, "fields": fields}
    row_source = _project_row_source(fields)
    profile_versions = {
        item.get("profile_version")
        for item in fields.values()
        if item.get("source") == "catalog" and item.get("profile_version")
    }
    profile_version = next(iter(profile_versions)) if len(profile_versions) == 1 else None
    return GovernanceMergeResult(
        values=values,
        metadata=metadata,
        audit_delta=tuple(audit),
        row_capacity_source=row_source,
        capability_profile_version=profile_version,
    )


def catalog_adoption_preview(
    record: Mapping[str, Any],
    proposed_values: Mapping[str, Any],
    *,
    proposed_profile_version: str,
) -> dict[str, Any]:
    metadata = derive_legacy_metadata(record)
    fields = metadata["fields"]
    diff = {}
    for field in GOVERNED_FIELDS:
        if field not in proposed_values:
            continue
        source = (fields.get(field) or {}).get("source", "unknown")
        current = record.get(field)
        proposed = proposed_values.get(field)
        diff[field] = {
            "current_value": current,
            "current_source": source,
            "proposed_value": proposed,
            "proposed_source": "catalog",
            "changed": current != proposed,
            "blocked_by_manual": source == "operator",
            "applicable": source in {"catalog", "unknown", "legacy"}
            and (current != proposed or source != "catalog"),
        }
    return {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "current_profile_version": record.get("capability_profile_version"),
        "proposed_profile_version": proposed_profile_version,
        "fields": diff,
    }


def apply_catalog_adoption(
    record: Mapping[str, Any],
    proposed_values: Mapping[str, Any],
    *,
    proposed_profile_version: str,
    expected_profile_version: str,
    current_matcher_version: str,
    expected_matcher_version: Optional[str] = None,
    fields: Optional[Iterable[str]] = None,
    reset_manual_fields: Iterable[str] = (),
    profile_evidence_id: Optional[str] = None,
    profile_verified_at: Optional[str] = None,
) -> GovernanceMergeResult:
    """Version-checked adoption that preserves manual fields by default."""
    if expected_profile_version != proposed_profile_version:
        _fail("capacity_profile_stale", "catalog profile changed since preview")
    if expected_matcher_version and expected_matcher_version != current_matcher_version:
        _fail("capacity_matcher_stale", "model matcher changed since preview")

    requested = set(fields) if fields is not None else set(GOVERNED_FIELDS)
    reset_manual = set(reset_manual_fields)
    invalid = (requested | reset_manual).difference(GOVERNED_FIELDS)
    if invalid:
        invalid_field = sorted(invalid)[0]
        _fail(
            "capacity_adoption_field_invalid",
            f"unsupported adoption field: {invalid_field}",
            field=invalid_field,
        )
    if not reset_manual.issubset(requested):
        _fail(
            "capacity_manual_reset_not_selected",
            "reset_manual_fields must also be selected for adoption",
        )

    metadata = derive_legacy_metadata(record)
    payload: dict[str, Any] = {}
    accepted: set[str] = set()
    for field in requested:
        if field not in proposed_values:
            continue
        source = (metadata["fields"].get(field) or {}).get("source", "unknown")
        if source == "operator" and field not in reset_manual:
            continue
        if source not in {"catalog", "unknown", "legacy", "operator"}:
            continue
        proposed = proposed_values[field]
        if proposed == record.get(field) and source == "catalog":
            continue
        payload[field] = proposed
        accepted.add(field)

    return merge_capacity_governance(
        payload,
        explicit_fields=accepted,
        existing=record,
        accepted_profile_version=proposed_profile_version,
        accepted_profile_fields=accepted,
        profile_evidence_id=profile_evidence_id,
        profile_verified_at=profile_verified_at,
    )
