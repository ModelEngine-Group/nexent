# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Capture and fingerprint the files in a tenant's configured skill storage."""

import hmac
import json
import os
from hashlib import sha256
from pathlib import Path, PureWindowsPath

from contracts.constants import environment
from contracts.errors.exceptions import ValidationError

MAX_SKILL_FILES = 256
MAX_SKILL_BYTES = 16 * 1024 * 1024


def skill_path_segment(value: str) -> str:
    if (not value or value in {".", ".."} or value[-1] in " ." or PureWindowsPath(value).is_reserved()
            or any(char in value for char in '/\\:\x00')):
        raise ValueError("Invalid skill path component")
    return value


def _raise_walk_error(error: OSError) -> None:
    raise error


def capture_skill_files(tenant_id: str, name: str) -> dict[str, bytes]:
    """Read bounded regular files from one skill without following directory links."""
    if not environment.CONTAINER_SKILLS_PATH:
        raise ValueError("Skill storage is not configured")
    root = Path(environment.CONTAINER_SKILLS_PATH).resolve()
    skill = root / skill_path_segment(tenant_id) / skill_path_segment(name)
    if skill.resolve() != skill or not skill.is_dir():
        raise ValueError("Skill directory is unavailable")
    files: dict[str, bytes] = {}
    remaining = MAX_SKILL_BYTES
    for directory, subdirs, filenames in os.walk(skill, onerror=_raise_walk_error):
        current = Path(directory)
        for component in [*subdirs, *filenames]:
            path = current / skill_path_segment(component)
            if path.is_symlink() or path.resolve() != path:
                raise ValueError("Skill bundle contains a link")
        for filename in filenames:
            path = current / filename
            if len(files) >= MAX_SKILL_FILES or not path.is_file():
                raise ValueError("Unsupported skill bundle")
            with path.open("rb") as stream:
                content = stream.read(remaining + 1)
            remaining -= len(content)
            if remaining < 0:
                raise ValueError("Skill bundle exceeds the file size limit")
            files[path.relative_to(skill).as_posix()] = content
    if "SKILL.md" not in files:
        raise ValueError("Skill guide is unavailable")
    return files


def validate_skill_context(context_items, rows) -> None:
    expected = {row["name"]: {"name": row["name"], "description": row["description"]} for row in rows}
    for item in context_items or ():
        if item.get("type") == "skill":
            content = item.get("content")
            if (not isinstance(content, dict) or not isinstance(content.get("name"), str)
                    or content != expected.get(content["name"])):
                raise ValueError("Skill context does not match the authorized binding")


def merge_skill_tool_parameters(tool_id: int, contributions) -> dict:
    """Apply compatible skill overrides and report conflicting values with their sources."""
    values = {}
    sources = {}
    for skill_name, config in contributions:
        for name, value in config.items():
            if name in values and values[name] != value:
                raise ValidationError(
                    f"Skills '{sources[name]}' and '{skill_name}' configure "
                    f"tool ID {tool_id} parameter '{name}' with different values."
                )
            values[name] = value
            sources[name] = skill_name
    return values


def skill_execution_revision(tenant_id: str, agent_id: int, version_no: int,
                             row: dict, files: dict[str, bytes]) -> str:
    """Pin the authorized binding, effective configuration and exact file contents."""
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/skill-execution/v1", "sha256")
    hashes = {name: sha256(content).hexdigest() for name, content in files.items()}
    payload = json.dumps([tenant_id, agent_id, version_no, row, hashes], sort_keys=True, separators=(",", ":"))
    return hmac.digest(key, payload.encode(), "sha256").hex()
