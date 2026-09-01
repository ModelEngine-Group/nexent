"""Filesystem path validation shared by SkillManager and backend services."""

import ntpath
import os


class InvalidSkillNameError(ValueError):
    """A skill name is not a single safe directory component."""


class UnsafeSkillPathError(ValueError):
    """A requested path escapes its configured skill directory."""


class UnsafeSkillRootError(ValueError):
    """The supplied skills root escapes the configured storage root."""


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


def resolve_contained_path(root: str, *parts: str) -> str:
    """Resolve relative components and reject traversal and escaping symlinks."""
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
    root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root, *segments))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise UnsafeSkillPathError("Unsafe local skill path")
    return candidate


def resolve_skill_path(root: str, name: str, *parts: str, allowed_root: str | None = None) -> str:
    """Resolve a skill or file below both its local and configured roots."""
    validate_path_component(name)
    root = os.path.realpath(root)
    if allowed_root:
        allowed_root = os.path.realpath(allowed_root)
        if root != allowed_root and not root.startswith(allowed_root + os.sep):
            raise UnsafeSkillRootError("Unsafe local skills directory")
    skill_root = resolve_contained_path(root, name)
    if not skill_root.startswith(root + os.sep):
        raise UnsafeSkillPathError("Unsafe local skill path")
    return resolve_contained_path(skill_root, *parts)
