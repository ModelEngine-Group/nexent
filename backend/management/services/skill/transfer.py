# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill catalog initialization and official installation."""

import logging
import ntpath
import os
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
from consts.const import OFFICIAL_SKILLS_ZIP_PATH
from contracts.errors.exceptions import AppException
from management.db.skill import repository as skill_db
from management.services.skill.files import (
    _local_skill_schema_yaml_path,
    _resolve_local_skill_path,
    get_skill_manager,
)
from management.services.skill.params import (
    _get_skill_inputs_from_code,
    _parse_skill_schema_from_yaml_bytes,
)

logger = logging.getLogger(__name__)


async def init_skill_list_for_tenant(tenant_id: str, user_id: str):
    """Initialize skill list for a new tenant by scanning local skill directories.

    Mirrors init_tool_list_for_tenant() in tool_configuration_service.py.

    Args:
        tenant_id: Tenant ID for the new tenant
        user_id: User ID for tracking who initiated the scan

    Returns:
        Dictionary containing initialization result
    """
    from management.db.skill import repository as skill_db_module

    if skill_db_module.check_skill_list_initialized(tenant_id):
        logger.info(f"Skill list already initialized for tenant {tenant_id}, skipping")
        return {"status": "already_initialized", "message": "Skill list already exists"}

    logger.info(f"Initializing skill list for new tenant: {tenant_id}")
    await update_skill_list(tenant_id=tenant_id, user_id=user_id)
    return {"status": "success", "message": "Skill list initialized successfully"}


async def update_skill_list(tenant_id: str, user_id: str):
    """Scan local skill directories and update ag_skill_info_t.

    Mirrors update_tool_list() in tool_configuration_service.py.

    Args:
        tenant_id: Tenant ID for the tenant
        user_id: User ID for tracking who initiated the scan
    """
    from management.db.skill import repository as skill_db_module

    skill_manager = get_skill_manager()
    # Use the resolved tenant-scoped local path for schema/config file reading
    local_base = skill_manager.resolve_tenant_dir(tenant_id=tenant_id)
    scanned_skills = skill_manager.list_skills(tenant_id=tenant_id)

    skills_to_upsert = []
    for skill_info in scanned_skills:
        skill_name = skill_info.get("name")
        if not skill_name:
            continue

        skill_data = {
            "name": skill_name,
            "description": skill_info.get("description", ""),
            "tags": skill_info.get("tags", []),
            "source": "official",
        }

        try:
            full_skill = skill_manager.load_skill(skill_name, tenant_id=tenant_id)
            if full_skill:
                skill_data["content"] = full_skill.get("content", "")

            # Try schema.yaml first; fall back to AST-parsed scripts
            schema_path = _local_skill_schema_yaml_path(skill_name, local_base)
            if os.path.isfile(schema_path):
                async with aiofiles.open(schema_path, "rb") as f:
                    raw = await f.read()
                parsed = _parse_skill_schema_from_yaml_bytes(raw)
                skill_data["config_schemas"] = parsed
                logger.debug(
                    "Loaded config_schemas from schema.yaml for skill %s", skill_name
                )
            else:
                scripts_dir = _resolve_local_skill_path(
                    local_base,
                    skill_name,
                    "scripts",
                )
                inputs = _get_skill_inputs_from_code(scripts_dir)
                if inputs:
                    skill_data["config_schemas"] = inputs
        except Exception as e:
            logger.warning(f"Could not load full skill content for {skill_name}: {e}")
            skill_data["content"] = ""

        skills_to_upsert.append(skill_data)

    if skills_to_upsert:
        skill_db_module.upsert_scanned_skills(skills_to_upsert, user_id, tenant_id)
        logger.info(f"Upserted {len(skills_to_upsert)} skills for tenant {tenant_id}")
    else:
        logger.info(f"No skills found to upsert for tenant {tenant_id}")


def install_skills_for_tenant(
    skill_ids: List[int], tenant_id: str, user_id: Optional[str] = None
) -> List[int]:
    """Install specified official skills into a new tenant by copying their records.

    For each skill_id provided, finds the global template skill (official skill with
    NULL tenant_id) and creates a copy in ag_skill_info_t for the target tenant.
    Skills that cannot be found as global templates are skipped with a warning.

    Args:
        skill_ids: List of skill IDs to install for the tenant.
        tenant_id: Target tenant ID to install skills into.
        user_id: User ID for created_by/updated_by audit fields.

    Returns:
        List of skill IDs that were successfully installed.
    """
    from management.db.skill import repository as skill_db_module

    if not skill_ids:
        return []

    installed_ids: List[int] = []
    for skill_id in skill_ids:
        try:
            template = skill_db_module.get_skill_by_id_global(skill_id)
            if not template:
                logger.warning(
                    f"Skill template with ID {skill_id} not found for installation "
                    f"into tenant {tenant_id}"
                )
                continue

            skill_name = template.get("name", "")
            if not skill_name:
                logger.warning(
                    f"Skill template {skill_id} has no name, skipping installation "
                    f"for tenant {tenant_id}"
                )
                continue

            existing = skill_db_module.get_skill_by_name(skill_name, tenant_id)
            if existing:
                logger.info(
                    f"Skill '{skill_name}' already exists for tenant {tenant_id}, skipping"
                )
                installed_ids.append(existing.get("skill_id"))
                continue

            skill_data = {
                "name": skill_name,
                "description": template.get("description", ""),
                "tags": template.get("tags", []),
                "content": template.get("content", ""),
                "config_schemas": template.get("config_schemas"),
                "config_values": template.get("config_values"),
                "source": template.get("source", "official"),
                "created_by": user_id,
                "updated_by": user_id,
            }
            result = skill_db_module.create_skill(skill_data, tenant_id)
            new_skill_id = result.get("skill_id")
            if new_skill_id:
                installed_ids.append(new_skill_id)
                logger.info(
                    f"Installed skill '{skill_name}' (ID {new_skill_id}) for tenant {tenant_id}"
                )
            else:
                logger.warning(
                    f"create_skill returned no skill_id for '{skill_name}', "
                    f"tenant {tenant_id}"
                )
        except AppException:
            raise
        except Exception as e:
            logger.error(
                f"Failed to install skill ID {skill_id} into tenant {tenant_id}: {e}"
            )

    return installed_ids


def install_skills_from_zip_for_tenant(
    skill_names: List[str],
    tenant_id: str,
    user_id: Optional[str] = None,
    locale: Optional[str] = None,
) -> List[str]:
    """Install official skills into a new tenant by reading ZIP files from OFFICIAL_SKILLS_ZIP_PATH.

    For each skill_name provided, derives the ZIP filename as <skill_name>.zip,
    reads the file from OFFICIAL_SKILLS_ZIP_PATH, and creates the skill via
    create_skill_from_file (which handles ZIP extraction, SKILL.md parsing,
    and database record creation).

    Skills that cannot be found as ZIP files are skipped with a warning.
    Existing official skills are refreshed from the trusted bundled ZIP;
    same-name custom skills are preserved.

    Args:
        skill_names: List of skill names to install (e.g. ["search-knowledge-base"]).
        tenant_id: Target tenant ID to install skills into.
        user_id: User ID for created_by/updated_by audit fields.
        locale: Frontend locale (e.g. "zh" or "en").

    Returns:
        List of skill names that were successfully installed.
    """
    from management.services.skill.service import SkillService

    if not skill_names:
        return []

    zip_dir = OFFICIAL_SKILLS_ZIP_PATH
    if not os.path.isdir(zip_dir):
        logger.warning(f"Official skills zip directory not found: {zip_dir}")
        return []

    installed: List[str] = []
    service = SkillService(tenant_id=tenant_id)
    zip_root = os.path.realpath(zip_dir)
    available_zip_resources: Dict[str, Tuple[str, str]] = {}
    try:
        for entry in os.scandir(zip_root):
            if not entry.name.casefold().endswith(".zip") or not entry.is_file(
                follow_symlinks=False
            ):
                continue
            candidate = os.path.realpath(entry.path)
            if os.path.normcase(os.path.dirname(candidate)) != os.path.normcase(
                zip_root
            ):
                logger.warning(
                    "Skipped unsafe official skill ZIP entry: %s", entry.name
                )
                continue
            official_name = entry.name[:-4]
            available_zip_resources[official_name] = (official_name, candidate)
    except OSError as exc:
        logger.warning(
            "Failed to scan official skills zip directory %s: %s", zip_root, exc
        )
        return []

    for skill_name in skill_names:
        name = str(skill_name or "").strip()
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or os.path.basename(name) != name
            or os.path.isabs(name)
            or ntpath.isabs(name)
            or bool(ntpath.splitdrive(name)[0])
        ):
            logger.warning("Rejected unsafe official skill name: %r", skill_name)
            continue

        zip_filename = f"{name}.zip"
        zip_resource = available_zip_resources.get(name)
        if zip_resource is None:
            logger.warning(
                f"ZIP file not found for skill '{name}': expected '{zip_filename}' in '{zip_root}'"
            )
            continue
        official_name, zip_path = zip_resource

        try:
            existing = skill_db.get_skill_by_name(official_name, tenant_id)
            with open(zip_path, "rb") as f:
                zip_content = f.read()

            if existing and existing.get("source") == "official":
                service.update_skill_from_file(
                    skill_name=official_name,
                    file_content=zip_content,
                    file_type="zip",
                    tenant_id=tenant_id,
                    user_id=None,
                )
                logger.info(
                    f"Refreshed official skill '{official_name}' for tenant {tenant_id}"
                )
                installed.append(official_name)
                continue
            if existing:
                logger.info(
                    f"Skill '{official_name}' already exists for tenant {tenant_id} "
                    "with a non-official source; installing the official package "
                    "under a numbered alias"
                )
                alias_name = None
                alias_existing = None
                for suffix in range(1, 1001):
                    candidate = f"{official_name}_{suffix}"
                    candidate_existing = skill_db.get_skill_by_name(
                        candidate,
                        tenant_id,
                    )
                    if (
                        not candidate_existing
                        or candidate_existing.get("source") == "official"
                    ):
                        alias_name = candidate
                        alias_existing = candidate_existing
                        break
                if alias_name is None:
                    logger.warning(
                        "No free official alias found for skill '%s' in tenant %s",
                        official_name,
                        tenant_id,
                    )
                    continue
                if alias_existing:
                    service.update_skill_from_file(
                        skill_name=alias_name,
                        file_content=zip_content,
                        file_type="zip",
                        tenant_id=tenant_id,
                        user_id=None,
                        rewrite_name=True,
                    )
                else:
                    service.create_skill_from_zip_bytes(
                        zip_bytes=zip_content,
                        skill_name=alias_name,
                        source="official",
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                installed.append(alias_name)
                continue

            # The request name only selects a pre-existing official resource.
            # Persist the canonical name obtained while scanning the trusted directory.
            result = service.create_skill_from_file(
                file_content=zip_content,
                skill_name=official_name,
                file_type="zip",
                source="official",
                tenant_id=tenant_id,
                user_id=user_id,
            )
            installed_name = result.get("name", official_name)
            installed.append(installed_name)
            logger.info(
                f"Installed skill '{installed_name}' for tenant {tenant_id} "
                f"from ZIP {zip_filename}"
            )
        except AppException:
            raise
        except Exception as e:
            logger.error(
                f"Failed to install skill '{skill_name}' from ZIP for tenant {tenant_id}: {e}"
            )

    return installed


def get_official_skills_with_status(
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return all official skills with their installation status for a tenant.

    Scans the official-skills-zip directory for available official skills
    (filename without .zip = skill name). For each skill, checks whether
    it is already installed for the target tenant and whether local resource
    files exist.

    Args:
        tenant_id: Tenant ID to check installation status for.

    Returns:
        List of dicts with skill_id, name, description, source, and status
        ("installable" | "installed" | "resource_missing").
    """
    from management.db.skill import repository as skill_db_module

    result: List[Dict[str, Any]] = []

    zip_dir = OFFICIAL_SKILLS_ZIP_PATH
    if not os.path.isdir(zip_dir):
        logger.warning(f"Official skills zip directory not found: {zip_dir}")
        return result

    try:
        zip_files = [f for f in os.listdir(zip_dir) if f.lower().endswith(".zip")]
    except OSError as e:
        logger.warning(f"Failed to list official skills zip directory: {e}")
        return result

    for zip_file in sorted(zip_files):
        skill_name = zip_file[:-4]
        if not skill_name:
            continue

        skill_id: Optional[int] = None
        is_installed = False
        has_resources = True

        if tenant_id:
            existing = skill_db_module.get_skill_by_name(skill_name, tenant_id)
            if existing:
                skill_id = existing.get("skill_id")
                is_installed = True
                skill_manager = get_skill_manager()
                skill_dir = os.path.join(
                    skill_manager.resolve_tenant_dir(tenant_id=tenant_id), skill_name
                )
                has_resources = os.path.isdir(skill_dir)

        if skill_id is None:
            global_skill = skill_db_module.get_skill_by_name(skill_name, None)
            if global_skill:
                skill_id = global_skill.get("skill_id")

        if is_installed and not has_resources:
            status = "resource_missing"
        elif is_installed:
            status = "installed"
        else:
            status = "installable"

        description = ""
        if skill_id:
            db_skill = (
                skill_db_module.get_skill_by_id(skill_id, tenant_id)
                if tenant_id
                else None
            )
            if db_skill:
                description = db_skill.get("description", "")
        if not description:
            db_global = skill_db_module.get_skill_by_name(skill_name, None)
            if db_global:
                description = db_global.get("description", "")

        result.append(
            {
                "skill_id": skill_id if skill_id is not None else 0,
                "name": skill_name,
                "description": description,
                "source": "official",
                "status": status,
            }
        )

    return result
