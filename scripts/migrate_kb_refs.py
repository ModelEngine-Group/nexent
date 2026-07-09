"""
migrate_kb_refs.py — one-shot migration for ExternalKnowledgeSearchTool params.

Converts legacy parameter shapes stored in ``ag_tool_instance_t.params`` to the
unified ``kb_refs`` schema:

    LEGACY #1 (oldest):
        {
            "index_names": ["n1", "n2"],
            ...
        }

    LEGACY #2 (intermediate):
        {
            "adapter_id": 1,
            "kb_ids": ["kb-1", "kb-2"],
            "kb_display_names": ["KB One", "KB Two"],
            ...
        }

    TARGET:
        {
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-1", "display_name": "KB One"},
                {"adapter_id": 1, "kb_id": "kb-2", "display_name": "KB Two"},
            ],
            ...
        }

Safety guarantees:
    - Default run is ``--dry-run``: produces a preview, ZERO database writes
    - ``--tenant T`` scopes the operation to a single tenant
    - ``--backup`` copies the original ``params`` into ``params._migrate_backup``
      before overwriting (per-row audit trail)
    - Skips any row that already has ``kb_refs`` (idempotent)
    - For legacy-shape #1, resolves the local adapter id per tenant via
      ``ExternalKnowledgeBaseService.ensure_local_adapter`` (so no manual
      adapter lookup is needed)
    - Rolls back on any unexpected error to avoid partial corruption

Run from project root:

    # Preview only (safe default)
    python scripts/migrate_kb_refs.py

    # Preview for one tenant
    python scripts/migrate_kb_refs.py --tenant tenant-abc --dry-run

    # Execute for one tenant, backup original params
    python scripts/migrate_kb_refs.py --tenant tenant-abc --execute --backup

    # Execute for ALL tenants (use with care)
    python scripts/migrate_kb_refs.py --execute --backup
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make backend importable when run as standalone script
_project_root = Path(__file__).resolve().parent.parent
_backend = _project_root / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from database.client import get_db_session
from database.db_models import ToolInfo, ToolInstance

logger = logging.getLogger("migrate_kb_refs")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Class name to filter on (the tool identifier stored in ag_tool_info_t.class_name)
_TOOL_CLASS_NAME = "ExternalKnowledgeSearchTool"


# ---------------------------------------------------------------------------
# Conversion logic
# ---------------------------------------------------------------------------

def _try_json_parse(value: Any) -> Any:
    """Parse JSON-encoded strings to python objects; pass-through otherwise."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return []
    return value


def convert_params_to_kb_refs(
    params: Dict[str, Any],
    local_adapter_id: Optional[int],
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    Convert legacy params to canonical kb_refs list.

    Returns ``(kb_refs, reason)`` where:
        - ``kb_refs`` is ``None`` when row is already migrated OR no conversion is possible.
        - ``reason`` is one of:
            * ``"already_migrated"`` — ``kb_refs`` already present, skip
            * ``"skipped_empty"`` — neither legacy shape #1 nor #2 is usable
            * ``"local_no_adapter"`` — legacy #1 but no local adapter id resolved
            * ``"converted_legacy_1"`` — converted from ``index_names``
            * ``"converted_legacy_2"`` — converted from ``adapter_id+kb_ids``
    """
    if not isinstance(params, dict):
        return None, "skipped_empty"

    if params.get("kb_refs"):
        return None, "already_migrated"

    # Legacy shape #2: adapter_id + kb_ids
    adapter_id = params.get("adapter_id")
    kb_ids_raw = params.get("kb_ids")
    display_names_raw = params.get("kb_display_names")

    if adapter_id is not None and kb_ids_raw:
        kb_ids = _try_json_parse(kb_ids_raw)
        if not isinstance(kb_ids, list):
            kb_ids = []
        display_names = _try_json_parse(display_names_raw)
        if not isinstance(display_names, list):
            display_names = []
        kb_refs = [
            {
                "adapter_id": int(adapter_id),
                "kb_id": str(kb_id),
                "display_name": (
                    display_names[i] if i < len(display_names) else str(kb_id)
                ),
            }
            for i, kb_id in enumerate(kb_ids)
            if kb_id
        ]
        if kb_refs:
            return kb_refs, "converted_legacy_2"
        return None, "skipped_empty"

    # Legacy shape #1: index_names (requires local adapter)
    index_names_raw = params.get("index_names")
    if index_names_raw and local_adapter_id is not None:
        index_names = _try_json_parse(index_names_raw)
        if not isinstance(index_names, list) or not index_names:
            index_names = []
        kb_refs = [
            {
                "adapter_id": int(local_adapter_id),
                "kb_id": str(name),
                "display_name": str(name),
            }
            for name in index_names
            if name
        ]
        if kb_refs:
            return kb_refs, "converted_legacy_1"

    if index_names_raw and local_adapter_id is None:
        return None, "local_no_adapter"

    return None, "skipped_empty"


# ---------------------------------------------------------------------------
# Local-adapter resolver (one per tenant, cached within a run)
# ---------------------------------------------------------------------------

def _resolve_local_adapter_id(tenant_id: str, cache: Dict[str, Optional[int]]) -> Optional[int]:
    """Idempotent resolution of the tenant's local adapter id."""
    if tenant_id in cache:
        return cache[tenant_id]
    try:
        from services.external_kb_service import ExternalKnowledgeBaseService
        record = ExternalKnowledgeBaseService.ensure_local_adapter(tenant_id)
        cache[tenant_id] = record.get("adapter_id")
    except Exception as exc:
        logger.warning("ensure_local_adapter failed for tenant %s: %s", tenant_id, exc)
        cache[tenant_id] = None
    return cache[tenant_id]


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def run_migration(
    tenant_filter: Optional[str],
    dry_run: bool,
    backup: bool,
) -> Dict[str, int]:
    """Run the migration. Returns a dict of counters."""
    from sqlalchemy import and_

    stats = {
        "scanned": 0,
        "already_migrated": 0,
        "converted": 0,
        "skipped_empty": 0,
        "local_no_adapter": 0,
        "errors": 0,
    }
    local_adapter_cache: Dict[str, Optional[int]] = {}

    with get_db_session() as session:
        query = (
            session.query(ToolInstance, ToolInfo.class_name)
            .join(ToolInfo, ToolInstance.tool_id == ToolInfo.tool_id)
            .filter(ToolInfo.class_name == _TOOL_CLASS_NAME)
        )
        if tenant_filter:
            query = query.filter(ToolInstance.tenant_id == tenant_filter)

        rows: List[Tuple[ToolInstance, str]] = query.all()
        stats["scanned"] = len(rows)
        logger.info("Scanned %d ExternalKnowledgeSearchTool rows", len(rows))

        for instance, _class_name in rows:
            tenant_id = instance.tenant_id or ""
            params = instance.params if isinstance(instance.params, dict) else {}

            local_adapter_id = (
                _resolve_local_adapter_id(tenant_id, local_adapter_cache)
                if "index_names" in params else None
            )

            kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id)
            stats[reason] = stats.get(reason, 0) + 1

            preview = {
                "tool_instance_id": instance.tool_instance_id,
                "tenant_id": tenant_id,
                "agent_id": instance.agent_id,
                "version_no": instance.version_no,
                "reason": reason,
                "kb_refs_count": len(kb_refs) if kb_refs else 0,
            }

            if reason in ("already_migrated", "skipped_empty", "local_no_adapter"):
                logger.info("[DRY] %s", preview)
                if reason == "local_no_adapter":
                    logger.warning(
                        "Row %d has index_names but local adapter not auto-provisioned "
                        "for tenant %s; skipped.",
                        instance.tool_instance_id, tenant_id,
                    )
                continue

            logger.info("[%s] %s", "DRY" if dry_run else "LIVE", preview)

            if dry_run:
                continue

            # Live path: backup + overwrite params.kb_refs
            try:
                new_params = dict(params)
                if backup:
                    new_params["_migrate_backup"] = {
                        "kb_ids": new_params.pop("kb_ids", None),
                        "kb_display_names": new_params.pop("kb_display_names", None),
                        "adapter_id": new_params.pop("adapter_id", None),
                        "index_names": new_params.pop("index_names", None),
                    }
                else:
                    for k in ("kb_ids", "kb_display_names", "adapter_id", "index_names"):
                        new_params.pop(k, None)

                new_params["kb_refs"] = json.loads(json.dumps(kb_refs))
                instance.params = new_params
                session.flush()
            except Exception as exc:
                logger.error(
                    "Failed to update row %d: %s — rolling back",
                    instance.tool_instance_id, exc,
                    exc_info=True,
                )
                session.rollback()
                stats["errors"] += 1
                break

        if not dry_run:
            session.commit()
            logger.info("Committed %d conversions", stats["converted"])

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate ExternalKnowledgeSearchTool params to kb_refs schema",
    )
    parser.add_argument(
        "--tenant",
        help="Scope to a single tenant_id (default: all tenants)",
        default=None,
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview only; no DB writes (DEFAULT)",
    )
    mode.add_argument(
        "--execute",
        dest="execute",
        action="store_true",
        default=False,
        help="Actually write updates (USE WITH CARE)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=False,
        help="Before overwriting, copy original fields to params._migrate_backup",
    )

    args = parser.parse_args()
    dry_run = not args.execute

    logger.info(
        "Starting migrate_kb_refs: tenant=%r dry_run=%s backup=%s",
        args.tenant, dry_run, args.backup,
    )
    if dry_run:
        logger.info("--dry-run is enabled; pass --execute to apply changes")

    stats = run_migration(
        tenant_filter=args.tenant,
        dry_run=dry_run,
        backup=args.backup,
    )

    logger.info("Migration summary: %s", json.dumps(stats, indent=2))
    return 1 if stats["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
