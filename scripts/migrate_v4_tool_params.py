#!/usr/bin/env python3
"""
V4 Tool Params Migration Script

Migrates ag_tool_info_t.params from legacy flat structure to V4 nested structure:

  1. kb_refs[].kb_id -> kb_refs[].knowledge_base_id
  2. Flat search_mode/top_k/score_threshold/reranking_enable/search_mode_enabled
     -> nested retrieval_model dict

Usage:
    python scripts/migrate_v4_tool_params.py --dry-run
    python scripts/migrate_v4_tool_params.py --execute --batch-size 100
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Make backend importable for consts
_project_root = Path(__file__).resolve().parent.parent
_backend = _project_root / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import create_engine, text

from consts.const import (
    NEXENT_POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
)

logger = logging.getLogger("migrate_v4_tool_params")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

TABLE = "nexent.ag_tool_info_t"

# Flat keys that move into retrieval_model
_RETRIEVAL_FLAT_KEYS = (
    "search_mode",
    "search_mode_enabled",
    "top_k",
    "score_threshold",
    "reranking_enable",
)

# Mapping from legacy flat key -> nested retrieval_model key
_RETRIEVAL_KEY_MAP = {
    "search_mode": "search_method",
    "search_mode_enabled": "search_method_enabled",
    "top_k": "top_k",
    "score_threshold": "score_threshold",
    "reranking_enable": "reranking_enable",
}


def _build_database_url() -> str:
    """Construct PostgreSQL connection URL from individual consts.

    Password and user are URL-encoded so that characters like ``@`` / ``#``
    inside the password do not break URL parsing.
    """
    from urllib.parse import quote_plus

    user = quote_plus(POSTGRES_USER or "")
    password = quote_plus(NEXENT_POSTGRES_PASSWORD or "")
    return (
        f"postgresql://{user}:{password}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


def migrate_params(params_str: str) -> tuple[str, bool]:
    """
    Migrate a single params JSON string from legacy to V4 structure.

    Returns:
        (migrated_json_str, was_modified)

    Idempotent: running on already-migrated input returns the same output
    with was_modified=False.
    """
    try:
        params = json.loads(params_str)
    except (json.JSONDecodeError, TypeError):
        return params_str, False

    if not isinstance(params, dict):
        return params_str, False

    modified = False

    # Step 1: kb_refs[].kb_id -> kb_refs[].knowledge_base_id
    kb_refs = params.get("kb_refs")
    if isinstance(kb_refs, list):
        for ref in kb_refs:
            if isinstance(ref, dict) and "kb_id" in ref:
                ref["knowledge_base_id"] = ref.pop("kb_id")
                modified = True

    # Step 2: flat search_mode keys -> nested retrieval_model
    if "search_mode" in params and "retrieval_model" not in params:
        retrieval_model: dict[str, Any] = {}
        for old_key, new_key in _RETRIEVAL_KEY_MAP.items():
            if old_key in params:
                retrieval_model[new_key] = params.pop(old_key)
        if retrieval_model:
            params["retrieval_model"] = retrieval_model
            modified = True

    return json.dumps(params, ensure_ascii=False), modified


def run_migration(dry_run: bool, batch_size: int) -> dict[str, int]:
    """
    Execute the migration against the database.

    Returns a stats dict with counters.
    """
    stats = {
        "scanned": 0,
        "modified": 0,
        "skipped": 0,
        "errors": 0,
    }

    url = _build_database_url()
    engine = create_engine(url, pool_pre_ping=True)

    # First, count matching rows for the summary
    with engine.connect() as conn:
        count_sql = text(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE params::text LIKE '%\"kb_id\":%' OR params::text LIKE '%\"search_mode\":%'"
        )
        total = conn.execute(count_sql).scalar() or 0

    logger.info("Will modify up to %d records", total)

    if total == 0:
        logger.info("No records to migrate.")
        return stats

    offset = 0
    while True:
        with engine.connect() as conn:
            batch_sql = text(
                f"SELECT tool_id, params FROM {TABLE} "
                f"WHERE params::text LIKE '%\"kb_id\":%' OR params::text LIKE '%\"search_mode\":%' "
                f"ORDER BY tool_id LIMIT :limit OFFSET :offset"
            )
            rows = conn.execute(batch_sql, {"limit": batch_size, "offset": offset}).fetchall()

        if not rows:
            break

        stats["scanned"] += len(rows)
        batch_modified = 0

        for row in rows:
            tool_id = row[0]
            raw_params = row[1]

            # params column may already be a dict (JSON column) or a string
            if isinstance(raw_params, dict):
                params_str = json.dumps(raw_params, ensure_ascii=False)
            elif isinstance(raw_params, str):
                params_str = raw_params
            else:
                stats["skipped"] += 1
                continue

            try:
                new_params_str, was_modified = migrate_params(params_str)
            except Exception as exc:
                logger.error("Failed to migrate tool_id=%s: %s", tool_id, exc)
                stats["errors"] += 1
                continue

            if not was_modified:
                stats["skipped"] += 1
                continue

            if dry_run:
                logger.info(
                    "[DRY-RUN] tool_id=%s\n  BEFORE: %s\n  AFTER:  %s",
                    tool_id, params_str, new_params_str,
                )
                batch_modified += 1
            else:
                try:
                    with engine.begin() as update_conn:
                        update_sql = text(
                            f"UPDATE {TABLE} SET params = :params WHERE tool_id = :tool_id"
                        )
                        update_conn.execute(
                            update_sql,
                            {"params": new_params_str, "tool_id": tool_id},
                        )
                    batch_modified += 1
                except Exception as exc:
                    logger.error("Failed to update tool_id=%s: %s", tool_id, exc)
                    stats["errors"] += 1

        stats["modified"] += batch_modified
        offset += batch_size

        logger.info(
            "Batch done: scanned=%d modified=%d offset=%d",
            stats["scanned"], stats["modified"], offset,
        )

    engine.dispose()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate ag_tool_info_t.params to V4 structure",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without writing to DB (DEFAULT)",
    )
    parser.add_argument(
        "--execute",
        dest="execute",
        action="store_true",
        default=False,
        help="Actually write updates (USE WITH CARE)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records per transaction batch (default: 100)",
    )

    args = parser.parse_args()
    dry_run = not args.execute

    logger.info(
        "Starting V4 tool params migration: dry_run=%s batch_size=%d",
        dry_run, args.batch_size,
    )
    if dry_run:
        logger.info("--dry-run is enabled by default; pass --execute to apply changes")

    stats = run_migration(dry_run=dry_run, batch_size=args.batch_size)

    logger.info("Migration summary: %s", json.dumps(stats, indent=2))
    return 1 if stats["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
