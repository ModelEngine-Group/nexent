"""Skill management service."""

import aiofiles
import io
import logging
import ntpath
import os
import zipfile
from typing import Any, Dict, List, Optional, Tuple, Union


from nexent.skills import SkillManager
from nexent.skills.skill_loader import SkillLoader
from nexent.skills.upload import normalize_skill_upload
from nexent.skills.text_codec import DecodedSkillFile, decode_skill_text
from consts.const import (
    OFFICIAL_SKILLS_ZIP_PATH,
    ROOT_DIR,
)
from consts.exceptions import ForbiddenError, SkillException
from database import skill_db
from database.group_db import query_group_ids_by_user

logger = logging.getLogger(__name__)
_SKILL_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update this skill"
_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update skill access"


_UNSUPPORTED_PREVIEW_DIRECTORIES = frozenset({
    "__macosx",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
})
_UNSUPPORTED_PREVIEW_EXTENSIONS = frozenset({
    ".7z", ".a", ".avi", ".bin", ".bmp", ".class", ".dll", ".dylib",
    ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg",
    ".mov", ".mp3", ".mp4", ".o", ".obj", ".otf", ".pdf", ".png",
    ".pyc", ".pyo", ".so", ".tar", ".ttf", ".wav", ".webm", ".webp",
    ".woff", ".woff2", ".xls", ".xlsx", ".zip",
})
_TEXT_PREVIEW_EXTENSIONS = frozenset({
    "", ".bash", ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".csv",
    ".dockerfile", ".env", ".go", ".h", ".hpp", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".log", ".md", ".mdx", ".php", ".properties",
    ".py", ".rb", ".rs", ".rst", ".sh", ".sql", ".svg", ".toml", ".ts",
    ".tsx", ".txt", ".xml", ".yaml", ".yml", ".zsh",
})



from management.services.skill.support import (
    UnsupportedSkillFilePreview,
    _decode_zip_member_name,
    _zip_members,
    _zip_file_list,
    _read_zip_member,
    _is_obviously_binary,
    _skill_file_preview_status,
    _replace_skill_frontmatter_name,
    _to_group_id_set,
    can_view_skill,
    resolve_skill_permission,
    _apply_default_skill_permission_fields,
    _get_user_role,
    _can_edit_skill,
    _can_manage_skill_access,
    _has_skill_access_changes,
    _validate_skill_access_update,
    _normalize_zip_entry_path,
    _find_zip_member_config_yaml,
    _params_dict_to_storable,
    _comment_text_from_token,
    _tuple_slot2,
    _is_before_next_sibling_comment_token,
    _flatten_ca_comment_to_text,
    _comment_from_map_block_header,
    _tooltip_for_commented_map_key,
    _tooltip_for_commented_seq_index,
    _apply_inline_comment_to_scalar,
    _commented_tree_to_plain,
    _ruamel_tree_to_plain,
    _parse_yaml_ruamel_plain,
    _parse_yaml_with_ruamel_merge_eol_comments,
    _get_skill_inputs_from_code,
    _is_add_argument_call,
    _extract_arg_from_add_argument,
    _get_type_name,
    _ast_literal_eval,
    _parse_yaml_fallback_pyyaml,
    _parse_skill_params_from_config_bytes,
    _parse_skill_schema_from_yaml_bytes,
    _read_params_from_zip_config_yaml,
    _find_zip_member_schema_yaml,
    _read_schema_yaml_from_zip,
    _get_skill_inputs_from_zip,
    _local_skill_config_yaml_path,
    _local_skill_schema_yaml_path,
    _resolve_local_skill_path,
    _write_skill_params_to_local_config_yaml,
    _remove_local_skill_config_yaml,
    get_skill_manager,
)

__all__ = ('UnsupportedSkillFilePreview', '_decode_zip_member_name', '_zip_members', '_zip_file_list', '_read_zip_member', '_is_obviously_binary', '_skill_file_preview_status', '_replace_skill_frontmatter_name', '_to_group_id_set', 'can_view_skill', 'resolve_skill_permission', '_apply_default_skill_permission_fields', '_get_user_role', '_can_edit_skill', '_can_manage_skill_access', '_has_skill_access_changes', '_validate_skill_access_update', '_normalize_zip_entry_path', '_find_zip_member_config_yaml', '_params_dict_to_storable', '_comment_text_from_token', '_tuple_slot2', '_is_before_next_sibling_comment_token', '_flatten_ca_comment_to_text', '_comment_from_map_block_header', '_tooltip_for_commented_map_key', '_tooltip_for_commented_seq_index', '_apply_inline_comment_to_scalar', '_commented_tree_to_plain', '_ruamel_tree_to_plain', '_parse_yaml_ruamel_plain', '_parse_yaml_with_ruamel_merge_eol_comments', '_get_skill_inputs_from_code', '_is_add_argument_call', '_extract_arg_from_add_argument', '_get_type_name', '_ast_literal_eval', '_parse_yaml_fallback_pyyaml', '_parse_skill_params_from_config_bytes', '_parse_skill_schema_from_yaml_bytes', '_read_params_from_zip_config_yaml', '_find_zip_member_schema_yaml', '_read_schema_yaml_from_zip', '_get_skill_inputs_from_zip', '_local_skill_config_yaml_path', '_local_skill_schema_yaml_path', '_resolve_local_skill_path', '_write_skill_params_to_local_config_yaml', '_remove_local_skill_config_yaml', 'get_skill_manager')

class SkillService:
    """Skill management service for backend operations."""

    def __init__(self, skill_manager: Optional[SkillManager] = None, tenant_id: Optional[str] = None):
        """Initialize SkillService.

        Args:
            skill_manager: Optional SkillManager instance, uses tenant-aware global if not provided
            tenant_id: Tenant ID for skill isolation. Required when no skill_manager is provided.
        """
        self.tenant_id = tenant_id
        self.skill_manager = skill_manager or get_skill_manager()

    def _local_skills_dir(self, tenant_id: Optional[str] = None) -> str:
        """Resolve the local directory for an explicit or service-bound tenant."""
        effective_tenant_id = tenant_id if tenant_id is not None else self.tenant_id
        return self.skill_manager.resolve_tenant_dir(tenant_id=effective_tenant_id)

    def _resolve_local_skills_dir_for_overlay(self) -> Optional[str]:
        """Directory where skill folders live: ``SKILLS_PATH``, else ``ROOT_DIR/skills`` if present."""
        d = self._local_skills_dir()
        if d:
            return str(d).rstrip(os.sep) or None
        if ROOT_DIR:
            candidate = os.path.join(ROOT_DIR, "skills")
            if os.path.isdir(candidate):
                return candidate
        return None

    def _enrich_configs_from_yaml(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        """Read local config files and overlay onto skill.

        config/config.yaml → config_values (runtime defaults dict)
        config/schema.yaml → config_schemas (parameter metadata list)

        If a file does not exist, the corresponding DB key is removed so the
        response never contains stale data (e.g. {"configs": null} instead of
        the old DB value).
        """
        out = dict(skill)
        local_dir = self._resolve_local_skills_dir_for_overlay()
        if not local_dir:
            return out
        name = out.get("name")
        if not name:
            return out
        config_path = _local_skill_config_yaml_path(name, local_dir)
        if os.path.isfile(config_path):
            try:
                with open(config_path, "rb") as f:
                    raw = f.read()
                out["config_values"] = _parse_skill_params_from_config_bytes(raw)
            except Exception as exc:
                logger.warning("Could not parse local config.yaml for skill %s: %s", name, exc)
        else:
            out.pop("config_values", None)
        # schema.yaml takes precedence over DB config_schemas
        schema_path = _local_skill_schema_yaml_path(name, local_dir)
        if os.path.isfile(schema_path):
            try:
                with open(schema_path, "rb") as f:
                    raw = f.read()
                parsed = _parse_skill_schema_from_yaml_bytes(raw)
                out["config_schemas"] = parsed
            except Exception as exc:
                logger.warning("Could not parse local schema.yaml for skill %s: %s", name, exc)
        else:
            out.pop("config_schemas", None)
        return out

    def list_skills(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all skills for a tenant.

        Args:
            tenant_id: Tenant ID for filtering skills. Uses instance tenant_id if not provided.

        Returns:
            List of skill info dicts
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            skills = skill_db.list_skills(effective_tenant_id)
            enriched = [self._enrich_configs_from_yaml(s) for s in skills]
            return enriched
        except Exception as e:
            logger.error(f"Error listing skills: {e}")
            raise SkillException(f"Failed to list skills: {str(e)}") from e

    def list_visible_skills(
        self,
        *,
        tenant_id: Optional[str] = None,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """List skills visible to a user and attach the resolved permission."""
        user_role = _get_user_role(user_id)
        user_group_ids = set(query_group_ids_by_user(user_id) or [])
        visible_skills = [
            skill
            for skill in self.list_skills(tenant_id=tenant_id)
            if can_view_skill(
                skill=skill,
                user_id=user_id,
                user_role=user_role,
                user_group_ids=user_group_ids,
            )
        ]
        for skill in visible_skills:
            skill["permission"] = resolve_skill_permission(
                skill=skill,
                user_id=user_id,
                user_role=user_role,
                user_group_ids=user_group_ids,
            )
        return visible_skills

    def list_visible_skill_permission_summaries(
        self,
        *,
        tenant_id: Optional[str] = None,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """List lightweight visible-skill fields used by repository counts."""
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")

        user_role = _get_user_role(user_id)
        user_group_ids = set(query_group_ids_by_user(user_id) or [])
        return [
            skill
            for skill in skill_db.list_skill_permission_summaries(
                effective_tenant_id
            )
            if can_view_skill(
                skill=skill,
                user_id=user_id,
                user_role=user_role,
                user_group_ids=user_group_ids,
            )
        ]

    def _require_tenant_id(self, tenant_id: Optional[str]) -> str:
        effective = tenant_id or self.tenant_id
        if not effective:
            raise SkillException("tenant_id is required")
        return effective

    def get_skill(self, skill_name: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a named skill with the shared configuration overlay."""
        return self._get_skill(skill_name, tenant_id=tenant_id)

    def get_skill_by_id(self, skill_id: int, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a skill ID with the shared configuration overlay."""
        return self._get_skill(skill_id, tenant_id=tenant_id, by_id=True)

    def _get_skill(self, identifier, *, tenant_id: Optional[str], by_id: bool = False):
        tenant_id = self._require_tenant_id(tenant_id)
        try:
            lookup = skill_db.get_skill_by_id if by_id else skill_db.get_skill_by_name
            skill = lookup(identifier, tenant_id)
            return self._enrich_configs_from_yaml(skill) if skill else None
        except Exception as exc:
            logger.error("Error getting skill %s: %s", identifier, exc)
            raise SkillException(f"Failed to get skill: {exc}") from exc

    def create_skill(
        self,
        skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new skill for a tenant.

        Args:
            skill_data: Skill data including name, description, content, etc.
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: User ID of the creator

        Returns:
            Created skill dict

        Raises:
            SkillException: If skill already exists locally or in database (409)
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")

        skill_name = skill_data.get("name")
        if not skill_name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
        if existing:
            raise SkillException(f"Skill '{skill_name}' already exists")

        # Check if skill directory already exists locally
        resolved = self._resolve_local_skills_dir_for_overlay()
        if resolved:
            local_skill_dir = _resolve_local_skill_path(resolved, skill_name)
            if os.path.exists(local_skill_dir):
                raise SkillException(f"Skill '{skill_name}' already exists locally")

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_data["created_by"] = user_id
            skill_data["updated_by"] = user_id
        _apply_default_skill_permission_fields(skill_data, user_id)

        try:
            # Create database record first
            result = skill_db.create_skill(skill_data, effective_tenant_id)

            # Create local skill file (SKILL.md)
            self.skill_manager.save_skill(skill_data, tenant_id=effective_tenant_id)

            # Mirror DB config_schemas to config/config.yaml when present (same layout as ZIP uploads).
            if self.skill_manager.base_skills_dir and skill_data.get("config_schemas") is not None:
                try:
                    _write_skill_params_to_local_config_yaml(
                        skill_name,
                        _params_dict_to_storable(skill_data["config_schemas"]),
                        self._local_skills_dir(effective_tenant_id),
                    )
                except Exception as exc:
                    logger.warning(
                        "Local config/config.yaml write failed after create for %s: %s",
                        skill_name,
                        exc,
                    )

            logger.info(f"Created skill '{skill_name}' with local files")
            return self._enrich_configs_from_yaml(result)
        except SkillException:
            raise
        except Exception as e:
            logger.error(f"Error creating skill: {e}")
            raise SkillException(f"Failed to create skill: {str(e)}") from e

    def create_skill_from_file(
        self, file_content: Union[bytes, str, io.BytesIO], skill_name: Optional[str] = None,
        file_type: str = "auto", source: str = "custom", tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create from MD or ZIP using the shared upload pipeline."""
        content, kind = normalize_skill_upload(file_content, file_type)
        return self._save_skill_upload(
            content, skill_name, kind, tenant_id=tenant_id or self.tenant_id,
            user_id=user_id, source=source,
        )

    def _save_skill_upload(
        self, content: bytes, skill_name: Optional[str], kind: str, *,
        tenant_id: Optional[str], user_id: Optional[str], source: str = "custom",
        update: bool = False, skip_duplicate_check: bool = False,
        ingroup_permission: Optional[str] = None, rewrite_name: bool = False,
    ) -> Dict[str, Any]:
        """Share parsing and persistence while keeping operation-specific policies."""
        is_zip = kind == "zip"
        manifest_path = original_root = None
        text = None
        name = skill_name
        if is_zip:
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    files = _zip_file_list(archive)
                    manifests = [
                        path for path in files if not path.endswith("/")
                        and (path.replace("\\", "/").lower().endswith("skill.md") if update
                             else path.replace("\\", "/").split("/")[-1].lower() == "skill.md")
                    ]
                    if update:
                        manifests = [path for path in manifests if "/" in path.replace("\\", "/")]
                    else:
                        manifests.sort(key=lambda path: "/" in path.replace("\\", "/"))
                    if manifests:
                        manifest_path = manifests[0]
                        parts = manifest_path.replace("\\", "/").split("/")
                        original_root = parts[0] if len(parts) >= 2 else None
                        raw = _read_zip_member(archive, manifest_path)
                        text = raw.decode("utf-8") if rewrite_name else str(decode_skill_text(raw))
            except zipfile.BadZipFile:
                if update:
                    raise
                raise SkillException("Invalid ZIP archive")
            if not update and manifest_path is None:
                raise SkillException("SKILL.md not found in ZIP archive")
            name = skill_name or original_root
            if not name:
                raise SkillException("Skill name is required")
            if not update and not skip_duplicate_check and skill_db.get_skill_by_name(name, tenant_id):
                raise SkillException(f"Skill '{name}' already exists")
        else:
            text = content.decode("utf-8") if update else str(decode_skill_text(content))

        parsed = None
        if text or (text is not None and not update):
            try:
                parsed = SkillLoader.parse(text)
            except ValueError as exc:
                if update and is_zip:
                    logger.warning("Could not parse SKILL.md from ZIP: %s", exc)
                else:
                    label = "Invalid SKILL.md in ZIP" if is_zip else "Invalid SKILL.md format"
                    raise SkillException(f"{label}: {exc}") from exc
        elif not is_zip:
            try:
                parsed = SkillLoader.parse(text or "")
            except ValueError as exc:
                raise SkillException(f"Invalid SKILL.md format: {exc}") from exc

        name = name or (parsed or {}).get("name")
        if not name:
            raise SkillException("Skill name is required")
        if not update:
            local_dir = self._resolve_local_skills_dir_for_overlay()
            if local_dir:
                _resolve_local_skill_path(local_dir, name)
            if not is_zip and not skip_duplicate_check and skill_db.get_skill_by_name(name, tenant_id):
                raise SkillException(f"Skill '{name}' already exists")

        allowed_tools = (parsed or {}).get("allowed_tools", [])
        data = {}
        if parsed is not None:
            data = {
                "description": parsed.get("description", ""),
                "content": parsed.get("content", ""),
                "tags": parsed.get("tags", []),
                "tool_ids": skill_db.get_tool_ids_by_names(allowed_tools, tenant_id) if allowed_tools else [],
            }
        if is_zip:
            root = original_root or name
            if not update:
                schema = _read_schema_yaml_from_zip(content, root)
                inputs = _get_skill_inputs_from_zip(content, preferred_skill_root=root)
                if schema or inputs:
                    data["config_schemas"] = schema or inputs
            params = _read_params_from_zip_config_yaml(content, preferred_skill_root=root)
            if params is not None:
                data["config_values"] = params

        if update:
            result = skill_db.update_skill(name, data, tenant_id, updated_by=user_id or None)
            self._delete_local_skill_files(name, tenant_id=tenant_id)
            data.update({"name": name, "allowed-tools": allowed_tools})
        else:
            data.update({"name": name, "source": source, "allowed-tools": allowed_tools})
            if user_id:
                data.update({"created_by": user_id, "updated_by": user_id})
            if ingroup_permission is not None:
                data["ingroup_permission"] = ingroup_permission
            _apply_default_skill_permission_fields(data, user_id)
            result = skill_db.create_skill(data, tenant_id)

        self.skill_manager.save_skill(data, tenant_id=tenant_id)
        if is_zip:
            overrides = None
            if rewrite_name and str(parsed.get("name") or "") != name:
                overrides = {manifest_path: _replace_skill_frontmatter_name(text, name).encode("utf-8")}
            if rewrite_name:
                self._upload_zip_files(content, name, original_root, tenant_id=tenant_id, file_overrides=overrides)
            else:
                self._upload_zip_files(content, name, original_root, tenant_id=tenant_id)
        return self._enrich_configs_from_yaml(result)

    def _delete_local_skill_files(self, skill_name: str, *, tenant_id: Optional[str]) -> None:
        """Delete all files within a skill's local directory, preserving the directory itself.

        Args:
            skill_name: Name of the skill whose local files should be deleted.
        """
        import shutil

        local_skills_dir = self._local_skills_dir(tenant_id)
        local_dir = _resolve_local_skill_path(local_skills_dir, skill_name)
        logger.info("Starting deletion of local files for skill '%s' from '%s'", skill_name, local_dir)

        if not os.path.isdir(local_dir):
            logger.info("Local skill directory does not exist, nothing to delete: %s", local_dir)
            return
        try:
            items = os.listdir(local_dir)
            logger.info("Found %d items to delete in '%s'", len(items), local_dir)

            for item in items:
                item_path = os.path.realpath(os.path.join(local_dir, item))
                if not item_path.startswith(os.path.realpath(local_dir) + os.sep):
                    logger.warning("Skipped unsafe local skill entry: %s", item)
                    continue
                if item_path.endswith("/"):
                    continue
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    logger.debug("Deleted directory: %s", item_path)
                else:
                    os.remove(item_path)
                    logger.debug("Deleted file: %s", item_path)
            logger.info("Successfully deleted all local files for skill '%s'", skill_name)
        except Exception as e:
            logger.error("Failed to delete local files for skill '%s': %s", skill_name, e)

    def _upload_zip_files(
        self,
        zip_bytes: bytes,
        skill_name: str,
        original_folder_name: Optional[str] = None,
        *,
        tenant_id: Optional[str],
        file_overrides: Optional[Dict[str, bytes]] = None,
    ) -> None:
        """Extract ZIP files to local storage only.

        Args:
            zip_bytes: ZIP archive content
            skill_name: Target skill name (for local directory)
            original_folder_name: Original folder name in ZIP (if different from skill_name)
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = _zip_file_list(zf)
        except zipfile.BadZipFile:
            raise SkillException("Invalid ZIP archive")

        # Determine if this ZIP has a subdirectory structure or root-level structure.
        # Root-level: SKILL.md is at root (e.g., "SKILL.md", "script/analyze.py") -> no stripping
        # Subdirectory: SKILL.md is inside a folder (e.g., "my-skill/SKILL.md") -> strip folder prefix
        needs_rename = (
            original_folder_name is not None
            and original_folder_name != skill_name
        )

        has_root_skill_md = any(
            not fp.endswith("/")
            and fp.replace("\\", "/").split("/")[0].lower() == "skill.md"
            for fp in file_list
        )

        logger.info(
            "Starting ZIP extraction for skill '%s': needs_rename=%s, original_folder='%s', has_root_skill_md=%s",
            skill_name, needs_rename, original_folder_name, has_root_skill_md
        )

        zip_stream.seek(0)
        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                logger.info("ZIP contains %d entries for skill '%s'", len(file_list), skill_name)

                validated_files: List[Tuple[str, str]] = []
                for file_path in file_list:
                    if file_path.endswith("/"):
                        continue

                    normalized_path = file_path.replace("\\", "/")
                    parts = normalized_path.split("/")

                    # Calculate target relative path
                    # Only strip the first component when the ZIP has a subdirectory structure
                    # (SKILL.md is inside a folder, not at root level)
                    if needs_rename and len(parts) >= 2 and parts[0] == original_folder_name:
                        relative_path = "/".join(parts[1:])
                    elif (
                        len(parts) >= 2
                        and not has_root_skill_md
                        and original_folder_name is not None
                        and parts[0] == original_folder_name
                    ):
                        # Strip first component (ZIP has subdirectory structure without root SKILL.md)
                        relative_path = "/".join(parts[1:])
                    else:
                        relative_path = normalized_path

                    if not relative_path:
                        continue

                    _resolve_local_skill_path(
                        self._local_skills_dir(tenant_id),
                        skill_name,
                        relative_path,
                    )
                    validated_files.append((file_path, relative_path))

                extracted_count = 0
                for file_path, relative_path in validated_files:
                    file_data = (
                        file_overrides[file_path]
                        if file_overrides and file_path in file_overrides
                        else _read_zip_member(zf, file_path)
                    )
                    local_skills_dir = self._local_skills_dir(tenant_id)
                    local_path = _resolve_local_skill_path(
                        local_skills_dir,
                        skill_name,
                        relative_path,
                    )
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(file_data)
                    extracted_count += 1
                    logger.debug("Extracted file '%s' -> '%s'", file_path, local_path)

            logger.info(
                "Completed ZIP extraction for skill '%s': %d files extracted to '%s'",
                skill_name, extracted_count, self._local_skills_dir(tenant_id)
            )
        except ForbiddenError:
            logger.warning("Rejected unsafe ZIP path for skill '%s'", skill_name)
            raise
        except Exception as e:
            logger.error("Failed to extract ZIP files for skill '%s': %s", skill_name, e)
            raise

    def update_skill_from_file(
        self, skill_name: str, file_content: Union[bytes, str, io.BytesIO],
        file_type: str = "auto", tenant_id: Optional[str] = None, user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate access before sharing the MD/ZIP replacement pipeline."""
        tenant_id = self._require_tenant_id(tenant_id)
        existing = skill_db.get_skill_by_name(skill_name, tenant_id)
        if not existing:
            raise SkillException(f"Skill not found: {skill_name}")
        if user_id is not None and not _can_edit_skill(existing, user_id):
            raise ForbiddenError(_SKILL_UPDATE_FORBIDDEN_MESSAGE)
        content, kind = normalize_skill_upload(file_content, file_type)
        return self._save_skill_upload(
            content, skill_name, kind, tenant_id=tenant_id, user_id=user_id, update=True
        )

    def update_skill(
        self, skill_name: str, skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None, user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update by name, preserving the trusted internal-call permission rule."""
        return self._update_skill_record(skill_name, skill_data, tenant_id, user_id)

    def update_skill_by_id(
        self, skill_id: int, skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None, user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update by ID with mandatory edit permission and rename handling."""
        return self._update_skill_record(skill_id, skill_data, tenant_id, user_id, by_id=True)

    def _update_skill_record(self, identifier, skill_data, tenant_id, user_id, *, by_id=False):
        tenant_id = self._require_tenant_id(tenant_id)
        try:
            lookup = skill_db.get_skill_by_id if by_id else skill_db.get_skill_by_name
            existing = lookup(identifier, tenant_id)
            if not existing:
                raise SkillException(f"Skill not found: {identifier}")
            if (by_id or user_id is not None) and not _can_edit_skill(existing, user_id):
                raise ForbiddenError(_SKILL_UPDATE_FORBIDDEN_MESSAGE)
            _validate_skill_access_update(existing, skill_data, user_id)

            local_dir = self._resolve_local_skills_dir_for_overlay() if by_id else None
            if by_id and local_dir and "name" in skill_data:
                _resolve_local_skill_path(local_dir, str(skill_data["name"] or ""))
            persist = skill_db.update_skill_by_id if by_id else skill_db.update_skill
            result = persist(identifier, skill_data, tenant_id, updated_by=user_id or None)
            if not by_id:
                local_dir = self._local_skills_dir(tenant_id)
            if not local_dir:
                return self._enrich_configs_from_yaml(result)

            local_name = identifier
            if by_id:
                id_name = f"skill_{int(existing['skill_id'])}"
                id_path = _resolve_local_skill_path(local_dir, id_name)
                local_name = id_name if os.path.isdir(id_path) else str(result.get("name") or existing.get("name") or "")
                if not local_name:
                    return self._enrich_configs_from_yaml(result)

            self._sync_updated_skill_files(
                local_name, local_dir, skill_data, existing, tenant_id,
                previous_name=str(existing.get("name") or "") if by_id else identifier,
                rename=by_id and local_name != f"skill_{identifier}",
            )
            return self._enrich_configs_from_yaml(result)
        except (ForbiddenError, SkillException):
            raise
        except Exception as exc:
            logger.exception("Error updating skill %s", identifier)
            raise SkillException(f"Failed to update skill: {exc}") from exc

    def _sync_updated_skill_files(
        self, local_name, local_dir, data, existing, tenant_id, *, previous_name, rename,
    ):
        """Keep the existing best-effort local mirror after a database update."""
        if "config_values" in data:
            try:
                if data["config_values"] is None:
                    _remove_local_skill_config_yaml(local_name, local_dir)
                else:
                    _write_skill_params_to_local_config_yaml(
                        local_name, _params_dict_to_storable(data["config_values"]), local_dir
                    )
            except Exception as exc:
                logger.warning("Local config/config.yaml sync failed for %s: %s", local_name, exc)
        try:
            local_skill = {
                "name": local_name,
                "description": data.get("description", existing.get("description", "")),
                "content": data.get("content", existing.get("content", "")),
                "tags": data.get("tags", existing.get("tags", [])),
                "allowed-tools": skill_db.get_tool_names_by_skill_name(previous_name, tenant_id),
                "files": data.get("files", []),
            }
            self.skill_manager.save_skill(local_skill, tenant_id=tenant_id)
            old_name = previous_name.strip()
            if rename and old_name and old_name != local_name:
                self.skill_manager.delete_skill(old_name, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Local SKILL.md sync failed after DB update for %s: %s", local_name, exc)

    def delete_skill(
        self,
        skill_name: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """Delete a skill for a tenant.

        Args:
            skill_name: Name of the skill to delete
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: User ID of the user performing the delete

        Returns:
            True if deleted successfully
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            # Delete local skill files from filesystem
            skill_dir = _resolve_local_skill_path(
                self._local_skills_dir(effective_tenant_id),
                skill_name,
            )
            if os.path.exists(skill_dir):
                import shutil
                shutil.rmtree(skill_dir)
                logger.info(f"Deleted skill directory: {skill_dir}")

            # Delete from database (soft delete with updated_by)
            return skill_db.delete_skill(skill_name, effective_tenant_id, updated_by=user_id)
        except Exception as e:
            logger.error(f"Error deleting skill {skill_name}: {e}")
            raise SkillException(f"Failed to delete skill: {str(e)}") from e


    def get_enabled_skills_for_agent(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """Get enabled skills for a specific agent from SkillInstance table.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number for fetching skill instances

        Returns:
            List of enabled skill dicts
        """
        try:
            enabled_skills = skill_db.search_skills_for_agent(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no
            )

            result = []
            for skill_instance in enabled_skills:
                skill_id = skill_instance.get("skill_id")
                skill = skill_db.get_skill_by_id(skill_id, tenant_id)
                if skill:
                    effective_config_values = dict(skill.get("config_values") or {})
                    effective_config_values.update(skill_instance.get("config_values") or {})
                    # Get skill info from ag_skill_info_t (repository returns keys: name, description, content)
                    merged = {
                        "skill_id": skill_id,
                        "name": skill.get("name"),
                        "description": skill.get("description", ""),
                        "content": skill.get("content", ""),
                        "enabled": skill_instance.get("enabled", True),
                        "tool_ids": skill.get("tool_ids", []),
                        "config_schemas": skill.get("config_schemas") or [],
                        "config_values": effective_config_values,
                    }
                    result.append(merged)

            return result
        except Exception as e:
            logger.error(f"Error getting enabled skills for agent: {e}")
            raise SkillException(f"Failed to get enabled skills: {str(e)}") from e

    def load_skill_directory(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Load entire skill directory including scripts.

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with skill metadata and local directory path, or None if not found
        """
        try:
            return self.skill_manager.load_skill_directory(skill_name, tenant_id=self.tenant_id)
        except Exception as e:
            logger.error(f"Error loading skill directory {skill_name}: {e}")
            raise SkillException(f"Failed to load skill directory: {str(e)}") from e

    def get_skill_scripts(self, skill_name: str) -> List[str]:
        """Get list of executable scripts in skill.

        Args:
            skill_name: Name of the skill

        Returns:
            List of script file paths
        """
        try:
            return self.skill_manager.get_skill_scripts(skill_name, tenant_id=self.tenant_id)
        except Exception as e:
            logger.error(f"Error getting skill scripts {skill_name}: {e}")
            raise SkillException(f"Failed to get skill scripts: {str(e)}") from e

    def build_skills_summary(
        self,
        available_skills: Optional[List[str]] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0
    ) -> str:
        """Build skills summary with whitelist filter for prompt injection.

        Args:
            available_skills: Optional whitelist of skill names to include.
                             If provided, only skills in this list will be included.
            agent_id: Agent ID for fetching skill instances
            tenant_id: Tenant ID for fetching skill instances
            version_no: Version number for fetching skill instances

        Returns:
            XML-formatted skills summary
        """
        try:
            skills_to_include = []

            if agent_id and tenant_id:
                # Get skills from SkillInstance table
                agent_skills = skill_db.search_skills_for_agent(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    version_no=version_no
                )

                for skill_instance in agent_skills:
                    skill_id = skill_instance.get("skill_id")
                    skill = skill_db.get_skill_by_id(skill_id, tenant_id)
                    if skill:
                        if available_skills is not None and skill.get("name") not in available_skills:
                            continue
                        # Get skill info from ag_skill_info_t (repository returns keys: name, description)
                        skills_to_include.append({
                            "name": skill.get("name"),
                            "description": skill.get("description", ""),
                        })
            else:
                # Fallback: use all skills from the current tenant
                effective_tenant_id = tenant_id or self.tenant_id
                if effective_tenant_id:
                    all_skills = skill_db.list_skills(effective_tenant_id)
                else:
                    all_skills = []
                skills_to_include = all_skills
                if available_skills is not None:
                    available_set = set(available_skills)
                    skills_to_include = [s for s in all_skills if s.get("name") in available_set]

            if not skills_to_include:
                return ""

            def escape_xml(s: str) -> str:
                if s is None:
                    return ""
                return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            lines = ["<skills>"]
            for skill in skills_to_include:
                name = escape_xml(skill.get("name", ""))
                description = escape_xml(skill.get("description", ""))

                lines.append(f'  <skill>')
                lines.append(f'    <name>{name}</name>')
                lines.append(f'    <description>{description}</description>')
                lines.append(f'  </skill>')

            lines.append("</skills>")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Error building skills summary: {e}")
            raise SkillException(f"Failed to build skills summary: {str(e)}") from e

    def get_skill_content(self, skill_name: str, tenant_id: Optional[str] = None) -> str:
        """Get skill content for runtime loading.

        Args:
            skill_name: Name of the skill to load
            tenant_id: Tenant ID for filtering. Uses instance tenant_id if not provided.

        Returns:
            Skill content in markdown format
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            return ""
        try:
            skill = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
            return skill.get("content", "") if skill else ""
        except Exception as e:
            logger.error(f"Error getting skill content {skill_name}: {e}")
            raise SkillException(f"Failed to get skill content: {str(e)}") from e

    def get_skill_file_tree(
        self,
        skill_name: str,
        tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get file tree structure of a skill.

        Args:
            skill_name: Name of the skill
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            Dict with file tree structure, or None if not found
        """
        try:
            effective_tenant_id = tenant_id or self.tenant_id
            tree = self.skill_manager.get_skill_file_tree(
                skill_name, tenant_id=effective_tenant_id
            )
            if not tree:
                return tree

            local_skills_dir = self._local_skills_dir(effective_tenant_id)

            def annotate(node: Dict[str, Any], parent_path: str = "") -> None:
                is_root = not parent_path and node.get("type") == "directory" and node.get("name") == skill_name
                relative_path = parent_path if is_root else (
                    f"{parent_path}/{node.get('name')}" if parent_path else str(node.get("name") or "")
                )
                if node.get("type") == "file":
                    node["preview_status"] = _skill_file_preview_status(
                        local_skills_dir,
                        skill_name,
                        relative_path,
                    )
                for child in node.get("children") or []:
                    annotate(child, relative_path)

            annotate(tree)
            return tree
        except Exception as e:
            logger.error(f"Error getting skill file tree: {e}")
            raise SkillException(f"Failed to get skill file tree: {str(e)}") from e

    def get_skill_file_content(
        self,
        skill_name: str,
        file_path: str,
        tenant_id: Optional[str] = None
    ) -> Optional[DecodedSkillFile]:
        """Get content of a specific file within a skill.

        Args:
            skill_name: Name of the skill
            file_path: Relative path to the file within the skill directory
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            File content as string, or None if file not found
        """
        try:
            effective_tenant_id = tenant_id or self.tenant_id
            local_skills_dir = self._local_skills_dir(effective_tenant_id)
            full_path = _resolve_local_skill_path(
                local_skills_dir,
                skill_name,
                file_path,
            )
            local_root = os.path.realpath(local_skills_dir)
            skill_root = os.path.realpath(
                _resolve_local_skill_path(local_skills_dir, skill_name)
            )
            full_path = os.path.realpath(full_path)
            if (
                not full_path.startswith(local_root + os.sep)
                or not full_path.startswith(skill_root + os.sep)
            ):
                raise ForbiddenError("Unsafe local skill path")

            try:
                if _skill_file_preview_status(local_skills_dir, skill_name, file_path) == "unsupported":
                    raise UnsupportedSkillFilePreview(f"Unsupported skill file preview: {file_path}")
                with open(full_path, "rb") as f:
                    raw = f.read()
                if isinstance(raw, str):
                    return DecodedSkillFile(raw, "utf-8")
                if _is_obviously_binary(raw):
                    raise UnsupportedSkillFilePreview(f"Unsupported skill file preview: {file_path}")
                return decode_skill_text(raw)
            except FileNotFoundError:
                logger.warning("Skill file not found: %s/%s", skill_name, file_path)
                return None
            except UnsupportedSkillFilePreview:
                raise
        except ForbiddenError:
            logger.warning("Rejected unsafe file read for skill '%s'", skill_name)
            raise
        except UnsupportedSkillFilePreview:
            raise
        except Exception as e:
            logger.error(f"Error reading skill file {skill_name}/{file_path}: {e}")
            raise SkillException(f"Failed to read skill file: {str(e)}") from e

    # ============== Skill Instance Methods ==============

    def create_or_update_skill_instance(
        self,
        skill_info,
        tenant_id: str,
        user_id: str,
        version_no: int = 0
    ):
        """Create or update a skill instance for an agent.

        Args:
            skill_info: Skill instance information (SkillInstanceInfoRequest or dict)
            tenant_id: Tenant ID
            user_id: User ID (will be set as created_by/updated_by)
            version_no: Version number (default 0 for draft)

        Returns:
            Created or updated skill instance dict
        """
        from database import skill_db as skill_db_module
        return skill_db_module.create_or_update_skill_by_skill_info(
            skill_info=skill_info,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no
        )

    def list_skill_instances(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """List all skill instances for an agent.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            List of skill instance dicts
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instances_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

    def get_skill_instance(
        self,
        agent_id: int,
        skill_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> Optional[Dict[str, Any]]:
        """Get a specific skill instance for an agent.

        Args:
            agent_id: Agent ID
            skill_id: Skill ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            Skill instance dict or None if not found
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instance_by_id(
            agent_id=agent_id,
            skill_id=skill_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

    def create_skill_from_zip_bytes(
        self, zip_bytes: bytes, skill_name: Optional[str] = None, source: str = "导入",
        user_id: Optional[str] = None, tenant_id: Optional[str] = None,
        skip_duplicate_check: bool = False, ingroup_permission: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import through the shared pipeline with optional frontmatter rename."""
        return self._save_skill_upload(
            zip_bytes, skill_name, "zip", tenant_id=tenant_id, user_id=user_id,
            source=source, skip_duplicate_check=skip_duplicate_check,
            ingroup_permission=ingroup_permission, rewrite_name=True,
        )

    def export_skills_by_names(
        self,
        skill_names: List[str],
        tenant_id: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Export skills as ZIP files by name.

        Packages the entire skill directory (SKILL.md, scripts/, assets/, config/)
        into a ZIP for each skill name.

        Args:
            skill_names: List of skill names to export
            tenant_id: Tenant ID for skill lookup

        Returns:
            List of dicts with skill_name and skill_zip_base64
        """
        import base64

        effective_tenant_id = tenant_id or self.tenant_id
        results: List[Dict[str, str]] = []

        for skill_name in skill_names:
            local_skills_dir = self._local_skills_dir(effective_tenant_id)
            skill_dir = _resolve_local_skill_path(
                local_skills_dir,
                skill_name,
            )
            if not os.path.isdir(skill_dir):
                skill_info = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
                if not skill_info:
                    logger.warning(f"Skill directory and DB record not found for export: {skill_name}")
                    continue
                logger.warning(
                    "Skill directory not found for export, rebuilding SKILL.md from DB snapshot: %s",
                    skill_name,
                )
                self.skill_manager.save_skill({
                    "name": skill_info.get("name") or skill_name,
                    "description": skill_info.get("description", ""),
                    "content": skill_info.get("content", ""),
                    "tags": skill_info.get("tags", []),
                }, tenant_id=effective_tenant_id)
                if not os.path.isdir(skill_dir):
                    logger.warning(f"Failed to rebuild skill directory for export: {skill_name}")
                    continue

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(skill_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, skill_dir)
                        arcname = os.path.join(skill_name, rel_path)
                        zf.write(file_path, arcname)

            zip_buffer.seek(0)
            zip_base64 = base64.b64encode(zip_buffer.read()).decode("utf-8")
            results.append({
                "skill_name": skill_name,
                "skill_zip_base64": zip_base64
            })

        return results


# ============== Skill List Initialization ==============


async def init_skill_list_for_tenant(tenant_id: str, user_id: str):
    """Initialize skill list for a new tenant by scanning local skill directories.

    Mirrors init_tool_list_for_tenant() in tool_configuration_service.py.

    Args:
        tenant_id: Tenant ID for the new tenant
        user_id: User ID for tracking who initiated the scan

    Returns:
        Dictionary containing initialization result
    """
    from database import skill_db as skill_db_module

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
    from database import skill_db as skill_db_module

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
                logger.debug("Loaded config_schemas from schema.yaml for skill %s", skill_name)
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
    skill_ids: List[int],
    tenant_id: str,
    user_id: Optional[str] = None
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
    from database import skill_db as skill_db_module

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
        except Exception as e:
            logger.error(
                f"Failed to install skill ID {skill_id} into tenant {tenant_id}: {e}"
            )

    return installed_ids


def install_skills_from_zip_for_tenant(
    skill_names: List[str],
    tenant_id: str,
    user_id: Optional[str] = None,
    locale: Optional[str] = None
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
            if not entry.name.casefold().endswith(".zip") or not entry.is_file(follow_symlinks=False):
                continue
            candidate = os.path.realpath(entry.path)
            if os.path.normcase(os.path.dirname(candidate)) != os.path.normcase(zip_root):
                logger.warning("Skipped unsafe official skill ZIP entry: %s", entry.name)
                continue
            official_name = entry.name[:-4]
            available_zip_resources[official_name] = (official_name, candidate)
    except OSError as exc:
        logger.warning("Failed to scan official skills zip directory %s: %s", zip_root, exc)
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
                    "with a non-official source, skipping"
                )
                installed.append(official_name)
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
        except Exception as e:
            logger.error(
                f"Failed to install skill '{skill_name}' from ZIP for tenant {tenant_id}: {e}"
            )

    return installed


def get_official_skills_with_status(
    tenant_id: Optional[str] = None
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
    from database import skill_db as skill_db_module

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
                    skill_manager.resolve_tenant_dir(tenant_id=tenant_id),
                    skill_name
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
            db_skill = skill_db_module.get_skill_by_id(skill_id, tenant_id) if tenant_id else None
            if db_skill:
                description = db_skill.get("description", "")
        if not description:
            db_global = skill_db_module.get_skill_by_name(skill_name, None)
            if db_global:
                description = db_global.get("description", "")

        result.append({
            "skill_id": skill_id if skill_id is not None else 0,
            "name": skill_name,
            "description": description,
            "source": "official",
            "status": status,
        })

    return result
