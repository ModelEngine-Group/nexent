# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Filesystem path validation shared by SkillManager and backend services."""

import ntpath
import os


class InvalidSkillNameError(ValueError):
    """A skill name is not a single safe directory component."""


class UnsafeSkillPathError(ValueError):
    """A requested path escapes its configured skill directory."""


class UnsafeSkillRootError(ValueError):
    """The supplied skills root escapes the configured storage root."""


def _is_same_or_descendant(path: str, root: str) -> bool:
    """Return whether path is root itself or a descendant on the same drive."""
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def validate_path_component(value: str) -> str:
    """Validate a single directory component without changing its spelling."""
    if (
        not isinstance(value, str) or not value.strip() or value in {".", ".."}
        or "/" in value or "\\" in value or "\x00" in value
        or os.path.isabs(value) or ntpath.isabs(value) or ntpath.splitdrive(value)[0]
        or os.path.basename(value) != value
    ):
        raise InvalidSkillNameError("Invalid skill name for local file access")
    return value


def _relative_segments(parts: tuple[str, ...]) -> list[str]:
    """Validate relative components without accessing the filesystem."""
    segments = []
    for part in parts:
        if (
            "\x00" in part or os.path.isabs(part) or ntpath.isabs(part)
            or ntpath.splitdrive(part)[0]
        ):
            raise UnsafeSkillPathError("Unsafe local skill path")
        components = part.replace("\\", "/").split("/")
        if ".." in components:
            raise UnsafeSkillPathError("Unsafe local skill path")
        segments.extend(component for component in components if component not in {"", "."})
    return segments


def resolve_contained_path(root: str, *parts: str) -> str:
    """Resolve relative components and reject traversal and escaping symlinks."""
    segments = _relative_segments(parts)
    root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root, *segments))
    if not _is_same_or_descendant(candidate, root):
        raise UnsafeSkillPathError("Unsafe local skill path")
    return candidate


def resolve_skill_path(root: str, name: str, *parts: str, allowed_root: str | None = None) -> str:
    """Resolve a skill or file below both its local and configured roots."""
    validate_path_component(name)
    root = os.path.realpath(root)
    if allowed_root:
        allowed_root = os.path.realpath(allowed_root)
        if not _is_same_or_descendant(root, allowed_root):
            raise UnsafeSkillRootError("Unsafe local skills directory")
    skill_root = resolve_contained_path(root, name)
    if skill_root == root or not _is_same_or_descendant(skill_root, root):
        raise UnsafeSkillPathError("Unsafe local skill path")
    return resolve_contained_path(skill_root, *parts)


class SkillPathResolver:
    """Reuse canonical roots within one operation, never across requests.

    Every skill and final target is still resolved through realpath so changed
    ancestor or file symlinks cannot escape the captured root.
    """

    def __init__(self, root: str, *, allowed_root: str | None = None):
        self.root = os.path.realpath(root)
        if allowed_root:
            allowed = os.path.realpath(allowed_root)
            if not _is_same_or_descendant(self.root, allowed):
                raise UnsafeSkillRootError("Unsafe local skills directory")

    def resolve_many(self, name: str, relative_paths: list[tuple[str, ...]]) -> list[str]:
        """Validate one skill and independently resolve each requested target."""
        validate_path_component(name)
        skill_root = os.path.realpath(os.path.join(self.root, name))
        if skill_root == self.root or not _is_same_or_descendant(skill_root, self.root):
            raise UnsafeSkillPathError("Unsafe local skill path")
        targets = []
        for parts in relative_paths:
            candidate = os.path.realpath(os.path.join(skill_root, *_relative_segments(parts)))
            if not _is_same_or_descendant(candidate, skill_root):
                raise UnsafeSkillPathError("Unsafe local skill path")
            targets.append(candidate)
        return targets
