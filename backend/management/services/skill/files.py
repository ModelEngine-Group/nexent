# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill archive entries, safe paths, text previews and local storage."""

import io
import json
import logging
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from consts.const import CONTAINER_SKILLS_PATH
from consts.exceptions import ForbiddenError, SkillException
from nexent.skills import SkillManager
from nexent.skills.paths import (
    InvalidSkillNameError,
    UnsafeSkillPathError,
    UnsafeSkillRootError,
    resolve_skill_path,
)

logger = logging.getLogger(__name__)
_UNSUPPORTED_PREVIEW_DIRECTORIES = frozenset(
    {
        "__macosx",
        "__pycache__",
        ".git",
        ".svn",
        ".hg",
    }
)
_UNSUPPORTED_PREVIEW_EXTENSIONS = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".pyo",
        ".so",
        ".tar",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
_TEXT_PREVIEW_EXTENSIONS = frozenset(
    {
        "",
        ".bash",
        ".c",
        ".cc",
        ".cfg",
        ".conf",
        ".cpp",
        ".css",
        ".csv",
        ".dockerfile",
        ".env",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".log",
        ".md",
        ".mdx",
        ".php",
        ".properties",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".svg",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)


class UnsupportedSkillFilePreview(SkillException):
    """Raised when a skill file is intentionally excluded from text preview."""


def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """Recover legacy ZIP member names written without the UTF-8 flag."""
    name = info.filename
    if info.flag_bits & 0x800 or name.isascii():
        return name
    try:
        raw_name = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "gb18030"):
        try:
            candidate = raw_name.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8" or any(
            "\u3400" <= char <= "\u9fff" for char in candidate
        ):
            return candidate
    return name


def _zip_members(zf: zipfile.ZipFile) -> List[Tuple[zipfile.ZipInfo, str]]:
    """Return ZIP entries paired with their normalized display paths."""
    members = [(info, _decode_zip_member_name(info)) for info in zf.infolist()]
    seen: Dict[str, str] = {}
    for info, decoded_name in members:
        normalized = _normalize_zip_entry_path(decoded_name)
        collision_key = normalized.casefold()
        previous = seen.get(collision_key)
        if previous is not None and previous != info.filename:
            raise SkillException(
                f"ZIP entries resolve to the same path: {decoded_name}"
            )
        seen[collision_key] = info.filename
    return members


def _zip_file_list(zf: zipfile.ZipFile) -> List[str]:
    return [decoded_name for _, decoded_name in _zip_members(zf)]


def _read_zip_member(zf: zipfile.ZipFile, decoded_name: str) -> bytes:
    for info, candidate in _zip_members(zf):
        if candidate == decoded_name:
            return zf.read(info)
    raise KeyError(decoded_name)


def _is_obviously_binary(raw: bytes) -> bool:
    if not raw:
        return False
    if b"\x00" in raw:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        if max(even_nuls, odd_nuls) > len(raw) / 4:
            return False
        return True
    control_count = sum(byte < 9 or 13 < byte < 32 for byte in raw)
    return control_count / len(raw) > 0.1


def _skill_file_preview_status(
    local_skills_dir: str,
    skill_name: str,
    relative_path: str,
) -> str:
    """Classify whether a local skill file may be exposed as editable text."""
    parts = [part.casefold() for part in relative_path.replace("\\", "/").split("/")]
    if any(part in _UNSUPPORTED_PREVIEW_DIRECTORIES for part in parts[:-1]):
        return "unsupported"
    extension = os.path.splitext(relative_path)[1].casefold()
    if extension in _UNSUPPORTED_PREVIEW_EXTENSIONS:
        return "unsupported"
    if extension in _TEXT_PREVIEW_EXTENSIONS:
        return "readable"

    local_root = os.path.realpath(local_skills_dir)
    skill_root = os.path.realpath(
        _resolve_local_skill_path(local_skills_dir, skill_name)
    )
    file_path = os.path.realpath(
        _resolve_local_skill_path(local_skills_dir, skill_name, relative_path)
    )
    if not file_path.startswith(local_root + os.sep) or not file_path.startswith(
        skill_root + os.sep
    ):
        raise ForbiddenError("Unsafe local skill path")
    try:
        with open(file_path, "rb") as file_obj:
            return (
                "unsupported"
                if _is_obviously_binary(file_obj.read(4096))
                else "readable"
            )
    except OSError:
        return "readable"


def _replace_skill_frontmatter_name(content: str, new_name: str) -> str:
    """Replace only the name value in SKILL.md frontmatter and preserve the body."""
    match = re.match(
        r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?P<closing>\r?\n---[ \t]*\r?\n)(?P<body>[\s\S]*)\Z",
        content,
        re.DOTALL,
    )
    if not match:
        raise SkillException("SKILL.md must have YAML frontmatter")

    frontmatter = match.group("frontmatter")
    name_match = re.search(
        r"(?m)^name[ \t]*:[^\r\n]*(?P<line_end>\r?\n|$)", frontmatter
    )
    if not name_match:
        raise SkillException("SKILL.md frontmatter must contain a name field")

    replacement = f"name: {json.dumps(new_name, ensure_ascii=False)}{name_match.group('line_end')}"
    updated_frontmatter = (
        frontmatter[: name_match.start()]
        + replacement
        + frontmatter[name_match.end() :]
    )
    return (
        content[: match.start("frontmatter")]
        + updated_frontmatter
        + content[match.end("frontmatter") :]
    )


def _normalize_zip_entry_path(name: str) -> str:
    """Normalize a ZIP member path for comparison (slashes, strip ./)."""
    norm = name.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _local_skill_config_yaml_path(skill_name: str, local_skills_dir: str) -> str:
    """Absolute path to <local_skills_dir>/<skill_name>/config/config.yaml."""
    return _resolve_local_skill_path(
        local_skills_dir,
        skill_name,
        "config",
        "config.yaml",
    )


def _local_skill_schema_yaml_path(skill_name: str, local_skills_dir: str) -> str:
    """Absolute path to <local_skills_dir>/<skill_name>/config/schema.yaml."""
    return _resolve_local_skill_path(
        local_skills_dir,
        skill_name,
        "config",
        "schema.yaml",
    )


def _resolve_local_skill_path(
    local_skills_dir: str, skill_name: str, *parts: str
) -> str:
    """Apply backend storage configuration and translate SDK path errors."""
    try:
        return resolve_skill_path(
            local_skills_dir,
            str(skill_name or "").strip(),
            *(str(part or "") for part in parts),
            allowed_root=CONTAINER_SKILLS_PATH,
        )
    except (InvalidSkillNameError, UnsafeSkillRootError) as exc:
        raise SkillException(str(exc)) from exc
    except UnsafeSkillPathError as exc:
        raise ForbiddenError(str(exc)) from exc


def _write_skill_params_to_local_config_yaml(
    skill_name: str,
    params: Dict[str, Any],
    local_skills_dir: str,
) -> None:
    """Write params to config/config.yaml; scalar ``value # tip`` strings round-trip as YAML comments above keys."""
    from management.services.skill.params import params_dict_to_roundtrip_yaml_text

    if not local_skills_dir:
        return
    path = _local_skill_config_yaml_path(skill_name, local_skills_dir)
    config_dir = os.path.dirname(path)
    os.makedirs(config_dir, exist_ok=True)
    text = params_dict_to_roundtrip_yaml_text(params)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("Wrote skill params to %s", path)


def _remove_local_skill_config_yaml(skill_name: str, local_skills_dir: str) -> None:
    """Remove config/config.yaml when params are cleared in the database."""
    if not local_skills_dir:
        return
    path = _local_skill_config_yaml_path(skill_name, local_skills_dir)
    if os.path.isfile(path):
        os.remove(path)
        logger.info("Removed %s (params cleared in DB)", path)


def get_skill_manager() -> SkillManager:
    """Return the process-wide SkillManager."""
    return SkillManager(base_skills_dir=CONTAINER_SKILLS_PATH)


class SkillArchiveOperations:
    """Archive upload and cleanup shared by the Skill service."""

    def _delete_local_skill_files(
        self, skill_name: str, *, tenant_id: Optional[str]
    ) -> None:
        """Delete all files within a skill's local directory, preserving the directory itself.

        Args:
            skill_name: Name of the skill whose local files should be deleted.
        """
        import shutil

        local_skills_dir = self._local_skills_dir(tenant_id)
        local_dir = _resolve_local_skill_path(local_skills_dir, skill_name)
        logger.info(
            "Starting deletion of local files for skill '%s' from '%s'",
            skill_name,
            local_dir,
        )

        if not os.path.isdir(local_dir):
            logger.info(
                "Local skill directory does not exist, nothing to delete: %s", local_dir
            )
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
            logger.info(
                "Successfully deleted all local files for skill '%s'", skill_name
            )
        except Exception as e:
            logger.error(
                "Failed to delete local files for skill '%s': %s", skill_name, e
            )

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
            original_folder_name is not None and original_folder_name != skill_name
        )

        has_root_skill_md = any(
            not fp.endswith("/")
            and fp.replace("\\", "/").split("/")[0].lower() == "skill.md"
            for fp in file_list
        )

        logger.info(
            "Starting ZIP extraction for skill '%s': needs_rename=%s, original_folder='%s', has_root_skill_md=%s",
            skill_name,
            needs_rename,
            original_folder_name,
            has_root_skill_md,
        )

        zip_stream.seek(0)
        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                logger.info(
                    "ZIP contains %d entries for skill '%s'", len(file_list), skill_name
                )

                validated_files: List[Tuple[str, str]] = []
                for file_path in file_list:
                    if file_path.endswith("/"):
                        continue

                    normalized_path = file_path.replace("\\", "/")
                    parts = normalized_path.split("/")

                    # Calculate target relative path
                    # Only strip the first component when the ZIP has a subdirectory structure
                    # (SKILL.md is inside a folder, not at root level)
                    if (
                        needs_rename
                        and len(parts) >= 2
                        and parts[0] == original_folder_name
                    ):
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
                skill_name,
                extracted_count,
                self._local_skills_dir(tenant_id),
            )
        except ForbiddenError:
            logger.warning("Rejected unsafe ZIP path for skill '%s'", skill_name)
            raise
        except Exception as e:
            logger.error(
                "Failed to extract ZIP files for skill '%s': %s", skill_name, e
            )
            raise
