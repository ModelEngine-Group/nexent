#!/usr/bin/env python3
"""
V4 Tool Params Rollback Script

Reverses the V4 migration, converting ag_tool_info_t.params back to legacy structure:

  1. kb_refs[].knowledge_base_id -> kb_refs[].kb_id
  2. Nested retrieval_model -> flat search_mode/top_k/score_threshold/reranking_enable

Usage:
    python scripts/rollback_v4_tool_params.py --dry-run
    python scripts/rollback_v4_tool_params.py --execute --batch-size 100
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

logger = logging.getLogger("rollback_v4_tool_params")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

TABLE = "nexent.ag_tool_info_t"

# Reverse mapping: nested retrieval_model key -> legacy flat key
_RETRIEVAL_KEY_REVERSE_MAP = {
    "search_method": "search_mode",
    "search_method_enabled": "search_mode_enabled",
    "top_k": "top_k",
    "score_threshold": "score_threshold",
    "reranking_enable": "reranking_enable",
}


def _build_database_url() -> str:
    """Construct PostgreSQL connection URL from individual consts."""
    return (
        f"postgresql://{POSTGRES_USER}:{NEXENT_POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


def rollback_params(params_str: str) -> tuple[str, bool]:
    """
    Rollback a single params JSON string from V4 to legacy structure.

    Returns:
        (rolled_back_json_str, was_modified)

    Idempotent: running on already-rolled-back input returns the same output
    with was_modified=False.
    """
    try:
        params = json.loads(params_str)
    except (json.JSONDecodeError, TypeError):
        return params_str, False

    if not isinstance(params, dict):
        return params_str, False

    modified = False

    # Step 1: kb_refs[].knowledge_base_id -> kb_refs[].kb_id
    kb_refs = params.get("kb_refs")
    if isinstance(kb_refs, list):
        for ref in kb_refs:
            if isinstance(ref, dict) and "knowledge_base_id" in ref:
                ref["kb_id"] = ref.pop("knowledge_base_id")
                modified = True

    # Step 2: nested retrieval_model -> flat keys
    retrieval_model = params.get("retrieval_model")
    if isinstance(retrieval_model, dict) and retrieval_model:
        for nested_key, flat_key in _RETRIEVAL_KEY_REVERSE_MAP.items():
            if nested_key in retrieval_model:
                params[flat_key] = retrieval_model.pop(nested_key)
        # Remove retrieval_model if now empty
        if not retrieval_model:
            del params["retrieval_model"]
        modified = True

    return json.dumps(params, ensure_ascii=False), modified


def run_rollback(dry_run: bool, batch_size: int) -> dict[str, int]:
    """
    Execute the rollback against the database.

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

    # Count matching rows
    with engine.connect() as conn:
        count_sql = text(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE params LIKE '%\"knowledge_base_id\":%' "
            f"OR params LIKE '%\"retrieval_model\":%'"
        )
        total = conn.execute(count_sql).scalar() or 0

    logger.info("Will modify up to %d records", total)

    if total == 0:
        logger.info("No records to rollback.")
        return stats

    offset = 0
    while True:
        with engine.connect() as conn:
            batch_sql = text(
                f"SELECT tool_id, params FROM {TABLE} "
                f"WHERE params LIKE '%\"knowledge_base_id\":%' "
                f"OR params LIKE '%\"retrieval_model\":%' "
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

            if isinstance(raw_params, dict):
                params_str = json.dumps(raw_params, ensure_ascii=False)
            elif isinstance(raw_params, str):
                params_str = raw_params
            else:
                stats["skipped"] += 1
                continue

            try:
                new_params_str, was_modified = rollback_params(params_str)
            except Exception as exc:
                logger.error("Failed to rollback tool_id=%s: %s", tool_id, exc)
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
        description="Rollback ag_tool_info_t.params from V4 to legacy structure",
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
        "Starting V4 tool params rollback: dry_run=%s batch_size=%d",
        dry_run, args.batch_size,
    )
    if dry_run:
        logger.info("--dry-run is enabled by default; pass --execute to apply changes")

    stats = run_rollback(dry_run=dry_run, batch_size=args.batch_size)

    logger.info("Rollback summary: %s", json.dumps(stats, indent=2))
    return 1 if stats["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
