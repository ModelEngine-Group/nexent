"""Official market template seeder.

Idempotently loads official solution templates from
``backend/resources/agent_templates/*.json`` into ``ag_agent_repository_t``
marked ``is_official_template=True`` / ``source='official'`` so they appear in
the unified market page and can be instantiated via the Recipe flow.

Run once at app startup (see ``config_app`` startup hook). Safe to re-run:
templates already seeded (matched by ``name`` + ``is_official_template``) are
skipped, so editing a template JSON requires deleting the row or bumping the
name to re-seed.

Skill ZIP payloads are built at seed time from the on-disk skill packages under
``resources/skill_packages/`` (see ``skill_package_builder``) so base64 blobs
never enter version control.
"""

import json
import logging
import os
from typing import Any, Dict, List

from database.client import get_db_session
from database.agent_repository_db import insert_agent_repository_record
from database.db_models import AgentRepository

logger = logging.getLogger(__name__)

_RESOURCES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "resources")
)
_SOLUTIONS_DIR = os.path.join(_RESOURCES_DIR, "solutions")

# Sentinel identities for platform-seeded official templates. These rows are
# global (not tenant-scoped) so any tenant can discover/instantiate them.
_SYSTEM_PUBLISHER_TENANT_ID = "nexent-official"
_SYSTEM_PUBLISHER_USER_ID = "nexent-official"


def _list_solution_dirs() -> List[str]:
    """List solution directories (each containing a solution.json or plugin.json)."""
    if not os.path.isdir(_SOLUTIONS_DIR):
        return []
    result = []
    for name in sorted(os.listdir(_SOLUTIONS_DIR)):
        sol_dir = os.path.join(_SOLUTIONS_DIR, name)
        if not os.path.isdir(sol_dir):
            continue
        has_manifest = os.path.isfile(
            os.path.join(sol_dir, "solution.json")
        ) or os.path.isfile(os.path.join(sol_dir, "plugin.json"))
        if has_manifest:
            result.append(sol_dir)
    return result


def _official_template_exists(session, name: str) -> bool:
    row = (
        session.query(AgentRepository)
        .filter(
            AgentRepository.name == name,
            AgentRepository.is_official_template.is_(True),
            AgentRepository.delete_flag != "Y",
        )
        .first()
    )
    return row is not None


def _build_repository_data(manifest: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a parsed solution (manifest + snapshot) into an ag_agent_repository_t payload."""
    tool_count = 0
    agent_info = snapshot.get("agent_info") or {}
    if isinstance(agent_info, dict):
        for entry in agent_info.values():
            if isinstance(entry, dict) and isinstance(entry.get("tools"), list):
                tool_count += len(entry["tools"])

    return {
        "agent_id": snapshot.get("agent_id") or 0,
        "version_no": 1,
        "name": manifest.get("name") or "unnamed-solution",
        "display_name": manifest.get("display_name"),
        "description": manifest.get("description") or "",
        "author": "nexent-official",
        "submitted_by": _SYSTEM_PUBLISHER_USER_ID,
        "version_name": "V1",
        "agent_info_json": snapshot,
        "status": "shared",
        "source": "official",
        "is_official_template": True,
        "expert_type": "agent",
        "tool_count": tool_count,
        "icon": manifest.get("icon"),
        "is_featured": False,
        "content": manifest.get("description") or "",
    }


def seed_official_templates() -> Dict[str, Any]:
    """Idempotently seed all official solution templates. Returns a summary dict."""
    # Lazy import to avoid pulling SDK tool registry at module import time.
    from services.solution_package_parser import parse_solution_package

    solution_dirs = _list_solution_dirs()
    if not solution_dirs:
        logger.info("No solution directories found under %s", _SOLUTIONS_DIR)
        return {"status": "noop", "seeded": 0, "skipped": 0}

    seeded = 0
    skipped = 0
    for sol_dir in solution_dirs:
        # Load the manifest first for the name / idempotency check.
        # Prefer solution.json; fall back to legacy plugin.json.
        manifest_path = os.path.join(sol_dir, "solution.json")
        if not os.path.isfile(manifest_path):
            manifest_path = os.path.join(sol_dir, "plugin.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load %s: %s", manifest_path, exc)
            continue

        name = manifest.get("name")
        if not name:
            logger.warning("Solution %s has no name, skipping", sol_dir)
            continue

        try:
            with get_db_session() as session:
                if _official_template_exists(session, name):
                    logger.info("Official template '%s' already seeded, skipping", name)
                    skipped += 1
                    continue

            snapshot = parse_solution_package(sol_dir)
            repository_data = _build_repository_data(manifest, snapshot)
            insert_agent_repository_record(
                repository_data=repository_data,
                publisher_tenant_id=_SYSTEM_PUBLISHER_TENANT_ID,
                publisher_user_id=_SYSTEM_PUBLISHER_USER_ID,
            )
            seeded += 1
            logger.info("Seeded official solution '%s' from %s", name, os.path.basename(sol_dir))
        except Exception as exc:
            logger.exception("Failed to seed official solution '%s': %s", name, exc)

    logger.info(
        "Official solution seed complete: %d seeded, %d skipped", seeded, skipped
    )
    return {"status": "success", "seeded": seeded, "skipped": skipped}
