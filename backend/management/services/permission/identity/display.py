# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional response enrichment; never change stored or operational identities."""

import logging
from typing import Any, Dict, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)


def get_cas_identities(user_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Load optional storage dependencies only when enrichment is requested."""
    from database.user_identity_db import get_cas_identities as load

    return load(user_ids)


def get_repository_agent_identity_ids(repository_ids: Iterable[int]) -> Dict[int, Dict[str, Optional[str]]]:
    """Resolve explicit versioned source records without guessing from emails."""
    from database.user_identity_db import get_repository_agent_identity_ids as load

    return load(repository_ids)


def load_cas_identities(user_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Keep unavailable optional display metadata from breaking existing APIs."""
    ids = {value for value in user_ids if isinstance(value, str) and value}
    if not ids:
        return {}
    try:
        result = get_cas_identities(ids)
        return result if isinstance(result, dict) else {}
    except Exception:
        logger.warning("CAS display identity lookup failed", exc_info=True)
        return {}


def enrich_cas_usernames(
    records: list[Dict[str, Any]],
    fields: Mapping[str, str],
    *,
    email_fields: Optional[Mapping[str, str]] = None,
    identities: Optional[Dict[str, Dict[str, str]]] = None,
) -> list[Dict[str, Any]]:
    """Add username fields using explicit IDs; optionally verify free-text provenance."""
    if identities is None:
        identities = load_cas_identities(row.get(source) for row in records for source in fields.values())
    for row in records:
        for output, source in fields.items():
            row.pop(output, None)
            identity = identities.get(row.get(source), {})
            name = identity.get("cas_username")
            if not isinstance(name, str) or not name.strip():
                continue
            email_field = (email_fields or {}).get(output)
            if email_field:
                original = str(row.get(email_field) or "").strip().casefold()
                canonical = str(identity.get("email") or "").strip().casefold()
                if not original or not canonical or original != canonical:
                    continue
            row[output] = name.strip()
    return records


def enrich_repository_identities(records: list[Dict[str, Any]], kind: str) -> None:
    """Attach names only to verified authors and explicitly linked submitters."""
    author_ids = {}
    repository_ids = {
        row["agent_repository_id"] for row in records
        if kind == "agent" and isinstance(row.get("agent_repository_id"), int)
    }
    if repository_ids:
        try:
            author_ids = get_repository_agent_identity_ids(repository_ids)
            if not isinstance(author_ids, dict):
                author_ids = {}
        except Exception:
            logger.warning("Repository author identity lookup failed", exc_info=True)
    sources = []
    for record in records:
        snapshot = record.get(f"{kind}_info_json") or {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        association = author_ids.get(record.get("agent_repository_id"), {})
        author_id = association.get("author_id") if kind == "agent" else snapshot.get("created_by")
        sources.append({
            "author_id": author_id,
            "submitter_id": record.get("publisher_user_id") or association.get("submitter_id"),
            "author": record.get("author"),
            "submitted_by": record.get("submitted_by"),
        })
    enrich_cas_usernames(sources, {
        "author_cas_username": "author_id", "submitted_by_cas_username": "submitter_id",
    }, email_fields={
        "author_cas_username": "author",
    })
    for record, source in zip(records, sources):
        for field in ("author_cas_username", "submitted_by_cas_username"):
            if field in source:
                record[field] = source[field]


def repository_identity_fields(record: Dict[str, Any]) -> Dict[str, str]:
    """Copy optional presentation metadata without exposing internal identity IDs."""
    return {
        key: record[key] for key in ("author_cas_username", "submitted_by_cas_username")
        if key in record
    }
