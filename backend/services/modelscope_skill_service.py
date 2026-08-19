"""Business service for the ModelScope external Skill market."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.modelscope_skill_adapter import (
    MODELSCOPE_SKILL_SOURCE,
    ModelScopeSkillAdapter,
)
from consts.exceptions import ModelScopeSkillNotFoundError, SkillException
from database import skill_db
from database.group_db import query_groups_by_tenant
from nexent.skills.skill_loader import SkillLoader
from services.skill_service import (
    _apply_default_skill_permission_fields,
    _get_skill_inputs_from_code,
    _parse_skill_params_from_config_bytes,
    _parse_skill_schema_from_yaml_bytes,
    _resolve_local_skill_path,
    get_skill_manager,
)

logger = logging.getLogger(__name__)

MAX_SKILL_FILE_COUNT = 1_000
MAX_SKILL_TOTAL_BYTES = 100 * 1024 * 1024


def _validate_downloaded_directory(skill_dir: Path) -> None:
    """Validate a downloaded snapshot without executing any of its contents."""
    root = skill_dir.resolve()
    if not root.is_dir():
        raise SkillException("Downloaded Skill directory does not exist")

    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        raise SkillException("Downloaded Skill must contain a root SKILL.md")

    file_count = 0
    total_bytes = 0
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise SkillException("Downloaded Skill contains symbolic links")
        try:
            entry.resolve().relative_to(root)
        except ValueError as exc:
            raise SkillException("Downloaded Skill contains an unsafe path") from exc
        if not entry.is_file():
            continue
        file_count += 1
        total_bytes += entry.stat().st_size
        if file_count > MAX_SKILL_FILE_COUNT:
            raise SkillException("Downloaded Skill contains too many files")
        if total_bytes > MAX_SKILL_TOTAL_BYTES:
            raise SkillException("Downloaded Skill is too large")


def _read_directory_skill_data(
    skill_dir: Path,
    *,
    local_name: str,
    description: str,
    tags: list[str],
    tenant_id: str,
) -> dict[str, Any]:
    try:
        parsed = SkillLoader.load(str(skill_dir / "SKILL.md"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SkillException(f"Invalid downloaded SKILL.md: {exc}") from exc

    raw_allowed_tools = parsed.get("allowed_tools", [])
    if isinstance(raw_allowed_tools, str):
        allowed_tools = [
            tool.strip() for tool in raw_allowed_tools.split(",") if tool.strip()
        ]
    elif isinstance(raw_allowed_tools, list):
        allowed_tools = [
            tool.strip()
            for tool in raw_allowed_tools
            if isinstance(tool, str) and tool.strip()
        ]
    else:
        allowed_tools = []
    tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)
    skill_data: dict[str, Any] = {
        "name": local_name,
        "description": description,
        "content": parsed.get("content", ""),
        "tags": tags,
        "tool_ids": tool_ids,
        "allowed-tools": allowed_tools,
    }
    script_outputs = parsed.get("script_outputs")
    if isinstance(script_outputs, dict) and script_outputs:
        skill_data["script_outputs"] = script_outputs

    schema_path = skill_dir / "config" / "schema.yaml"
    if schema_path.is_file():
        schemas = _parse_skill_schema_from_yaml_bytes(schema_path.read_bytes())
        if schemas:
            skill_data["config_schemas"] = schemas
    else:
        script_schemas = _get_skill_inputs_from_code(str(skill_dir / "scripts"))
        if script_schemas:
            skill_data["config_schemas"] = script_schemas

    config_path = skill_dir / "config" / "config.yaml"
    if config_path.is_file():
        skill_data["config_values"] = _parse_skill_params_from_config_bytes(
            config_path.read_bytes()
        )

    # Keep the editable local snapshot and the database metadata aligned.
    (skill_dir / "SKILL.md").write_text(
        SkillLoader.to_skill_md(skill_data), encoding="utf-8"
    )
    return skill_data


def _rollback_created_skill(local_name: str, tenant_id: str, user_id: str) -> None:
    try:
        skill_db.delete_skill(local_name, tenant_id, updated_by=user_id)
    except Exception:
        logger.exception(
            "Failed to roll back database record for ModelScope Skill %s",
            local_name,
        )


class ModelScopeSkillService:
    """Query and install anonymous public Skills from ModelScope."""

    def __init__(
        self,
        adapter: ModelScopeSkillAdapter | None = None,
        skill_manager: Any | None = None,
    ) -> None:
        self.adapter = adapter or ModelScopeSkillAdapter()
        self.skill_manager = skill_manager or get_skill_manager()

    def list_skills(
        self, *, search: str | None, page_number: int, page_size: int
    ) -> dict[str, Any]:
        return self.adapter.list_skills(
            search=search, page_number=page_number, page_size=page_size
        )

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        return self.adapter.get_skill(skill_id)

    def get_market_skill_detail(
        self,
        *,
        skill_id: str,
        source: str,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Return a locally installed market skill record, or {} if absent."""
        record = skill_db.get_skill_by_unique_id_and_owner(
            unique_id=skill_id,
            source=source,
            created_by=user_id,
            tenant_id=tenant_id,
        )
        if not record:
            return {}
        return dict(record)

    def get_upstream_last_modified(self, unique_id: str) -> str | None:
        """Fetch upstream last_modified for a ModelScope skill, or None if unavailable."""
        normalized_id = unique_id.strip()
        if not normalized_id:
            return None
        try:
            upstream = self.adapter.get_skill(normalized_id)
            return upstream.get("last_modified")
        except ModelScopeSkillNotFoundError:
            return None
        except Exception:
            logger.warning(
                "Failed to fetch upstream ModelScope Skill metadata for %s",
                normalized_id,
                exc_info=True,
            )
            return None

    def _download_skill_snapshot(
        self,
        *,
        canonical_id: str,
        tenant_root: Path,
        local_name: str,
        description: str,
        tags: list[str],
        tenant_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        """Download a skill into staging and parse the resulting snapshot."""
        with tempfile.TemporaryDirectory(
            prefix=".modelscope-skill-", dir=tenant_root
        ) as staging_dir:
            downloaded = self.adapter.download_skill(
                canonical_id, Path(staging_dir)
            )
            _validate_downloaded_directory(downloaded)
            downloaded_data = _read_directory_skill_data(
                downloaded,
                local_name=local_name,
                description=description,
                tags=tags,
                tenant_id=tenant_id,
            )
            persistent_staging = tenant_root / f".modelscope-skill-staged-{next(tempfile._get_candidate_names())}"
            shutil.copytree(downloaded, persistent_staging)
            return persistent_staging, downloaded_data

    def _replace_local_skill_directory(
        self, *, destination: Path, downloaded: Path
    ) -> None:
        """Replace the local skill directory with a downloaded snapshot."""
        backup_path = destination.parent / f".modelscope-skill-backup-{next(tempfile._get_candidate_names())}"
        try:
            if destination.exists():
                os.replace(destination, backup_path)
            shutil.move(str(downloaded), str(destination))
        except Exception:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if backup_path.exists() and not destination.exists():
                os.replace(backup_path, destination)
            raise
        else:
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)

    def install_skill(
        self,
        *,
        skill_id: str,
        name: str,
        description: str,
        tags: list[str],
        group_ids: list[int] | None,
        ingroup_permission: str | None,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Install one public ModelScope snapshot as an independent local Skill."""
        local_name = name.strip()
        tenant_root = Path(
            self.skill_manager.resolve_tenant_dir(tenant_id=tenant_id)
        ).resolve()
        tenant_root.mkdir(parents=True, exist_ok=True)
        destination = Path(_resolve_local_skill_path(str(tenant_root), local_name))

        if skill_db.get_skill_by_name(local_name, tenant_id):
            raise SkillException(f"Skill '{local_name}' already exists")
        if destination.exists():
            raise SkillException(f"Skill '{local_name}' already exists locally")

        if group_ids:
            tenant_groups = query_groups_by_tenant(
                tenant_id, page=None, page_size=None
            ).get("groups", [])
            tenant_group_ids = {
                int(group["group_id"])
                for group in tenant_groups
                if group.get("group_id") is not None
            }
            if not set(group_ids).issubset(tenant_group_ids):
                raise SkillException("One or more groups do not belong to the tenant")

        source_skill = self.adapter.get_skill(skill_id)
        canonical_id = source_skill["skill_id"]

        skill_data: dict[str, Any] = {
            "name": local_name,
            "description": description.strip(),
            "tags": tags,
            "source": MODELSCOPE_SKILL_SOURCE,
            "unique_id": canonical_id,
            "version_update_time": datetime.now(),
            "group_ids": group_ids,
            "ingroup_permission": ingroup_permission,
            "created_by": user_id,
            "updated_by": user_id,
        }
        _apply_default_skill_permission_fields(skill_data, user_id)

        # Insert first so the tenant-unique name is claimed before the download.
        result = skill_db.create_skill(skill_data, tenant_id)
        try:
            downloaded, downloaded_data = self._download_skill_snapshot(
                canonical_id=canonical_id,
                tenant_root=tenant_root,
                local_name=local_name,
                description=description.strip(),
                tags=tags,
                tenant_id=tenant_id,
            )
            update_data: dict[str, Any] = {
                "content": downloaded_data.get("content", ""),
                "tool_ids": downloaded_data.get("tool_ids", []),
            }
            if "config_schemas" in downloaded_data:
                update_data["config_schemas"] = downloaded_data["config_schemas"]
            if "config_values" in downloaded_data:
                update_data["config_values"] = downloaded_data["config_values"]
            result = skill_db.update_skill(
                local_name,
                update_data,
                tenant_id,
                updated_by=user_id,
            )
            try:
                self._replace_local_skill_directory(
                    destination=destination, downloaded=downloaded
                )
            except Exception as exc:
                raise SkillException(
                    "Failed to move the downloaded Skill into local storage"
                ) from exc
        except Exception:
            _rollback_created_skill(local_name, tenant_id, user_id)
            raise

        return result

    def update_skill(
        self,
        *,
        skill_id: int,
        unique_id: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Refresh an installed ModelScope skill while preserving local metadata."""
        existing_skill = skill_db.get_skill_by_id(skill_id, tenant_id)
        if not existing_skill:
            raise SkillException(f"Skill not found: {skill_id}")
        if existing_skill.get("source") != MODELSCOPE_SKILL_SOURCE:
            raise SkillException("Only ModelScope skills can be updated")
        if str(existing_skill.get("unique_id") or "").strip() != unique_id:
            raise SkillException("Skill unique_id does not match installed record")

        local_name = str(existing_skill.get("name") or "").strip()
        if not local_name:
            raise SkillException(f"Skill name is missing: {skill_id}")

        tenant_root = Path(
            self.skill_manager.resolve_tenant_dir(tenant_id=tenant_id)
        ).resolve()
        tenant_root.mkdir(parents=True, exist_ok=True)
        destination = Path(_resolve_local_skill_path(str(tenant_root), local_name))
        if not destination.exists():
            raise SkillException(f"Skill directory not found: {local_name}")

        source_skill = self.adapter.get_skill(unique_id)
        canonical_id = source_skill["skill_id"]

        downloaded, downloaded_data = self._download_skill_snapshot(
            canonical_id=canonical_id,
            tenant_root=tenant_root,
            local_name=local_name,
            description=str(source_skill.get("description") or ""),
            tags=list(existing_skill.get("tags") or []),
            tenant_id=tenant_id,
        )
        update_data: dict[str, Any] = {
            "content": downloaded_data.get("content", ""),
            "description": downloaded_data.get("description", ""),
            "tool_ids": downloaded_data.get("tool_ids", []),
            "version_update_time": datetime.now(),
        }
        if "config_schemas" in downloaded_data:
            update_data["config_schemas"] = downloaded_data["config_schemas"]
        if "config_values" in downloaded_data:
            update_data["config_values"] = downloaded_data["config_values"]

        result = skill_db.update_skill_by_id(
            skill_id,
            update_data,
            tenant_id,
            updated_by=user_id,
        )
        try:
            self._replace_local_skill_directory(
                destination=destination, downloaded=downloaded
            )
        except Exception as exc:
            raise SkillException(
                "Failed to move the downloaded Skill into local storage"
            ) from exc
        return result
