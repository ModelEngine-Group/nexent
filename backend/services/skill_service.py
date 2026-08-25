"""Skill management service."""

import aiofiles
import argparse
import ast
import inspect
import io
import json
import logging
import ntpath
import os
import zipfile
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from charset_normalizer import from_bytes

from nexent.skills import SkillManager
from nexent.skills.skill_loader import SkillLoader
from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    CONTAINER_SKILLS_PATH,
    OFFICIAL_SKILLS_ZIP_PATH,
    PERMISSION_EDIT,
    PERMISSION_PRIVATE,
    PERMISSION_READ,
    ROOT_DIR,
)
from consts.exceptions import ForbiddenError, SkillException
from database import skill_db
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.str_utils import convert_list_to_string
from utils.skill_import_utils import generate_available_copy_skill_name

logger = logging.getLogger(__name__)
_SKILL_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update this skill"
_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update skill access"


_skill_manager: Optional[SkillManager] = None

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


class UnsupportedSkillFilePreview(SkillException):
    """Raised when a skill file is intentionally excluded from text preview."""


class DecodedSkillFile(str):
    """String content carrying the source character encoding."""

    encoding: str

    def __new__(cls, content: str, encoding: str):
        value = super().__new__(cls, content)
        value.encoding = encoding
        return value


def _decode_text_bytes(raw: bytes) -> DecodedSkillFile:
    """Decode text bytes without silently replacing undecodable characters."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return DecodedSkillFile(raw.decode("utf-8-sig"), "utf-8-sig")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return DecodedSkillFile(raw.decode("utf-32"), "utf-32")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return DecodedSkillFile(raw.decode("utf-16"), "utf-16")
    if raw and raw.count(b"\x00") / len(raw) > 0.2:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        if odd_nuls > len(raw) / 4:
            return DecodedSkillFile(raw.decode("utf-16-le"), "utf-16-le")
        if even_nuls > len(raw) / 4:
            return DecodedSkillFile(raw.decode("utf-16-be"), "utf-16-be")

    try:
        return DecodedSkillFile(raw.decode("utf-8"), "utf-8")
    except UnicodeDecodeError:
        pass

    for encoding in ("gb18030", "big5"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if any("\u3400" <= char <= "\u9fff" for char in decoded):
            return DecodedSkillFile(decoded, encoding)

    match = from_bytes(raw).best()
    if match is None or match.encoding is None or match.chaos > 0.3:
        raise UnicodeDecodeError("unknown", raw, 0, len(raw), "Unable to detect a reliable text encoding")
    return DecodedSkillFile(str(match), match.encoding.lower())


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
        if encoding == "utf-8" or any("\u3400" <= char <= "\u9fff" for char in candidate):
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
            raise SkillException(f"ZIP entries resolve to the same path: {decoded_name}")
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
    if (
        not file_path.startswith(local_root + os.sep)
        or not file_path.startswith(skill_root + os.sep)
    ):
        raise ForbiddenError("Unsafe local skill path")
    try:
        with open(file_path, "rb") as file_obj:
            return "unsupported" if _is_obviously_binary(file_obj.read(4096)) else "readable"
    except OSError:
        return "readable"


    return result
