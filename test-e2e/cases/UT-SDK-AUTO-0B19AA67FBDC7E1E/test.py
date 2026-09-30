"""Unit tests for skill path-validation security boundaries.

Case: UT-SDK-AUTO-0B19AA67FBDC7E1E
"""

from __future__ import annotations

import os
import subprocess

import pytest

from nexent.skills.paths import (
    InvalidSkillNameError,
    UnsafeSkillPathError,
    UnsafeSkillRootError,
    resolve_contained_path,
    resolve_skill_path,
    validate_path_component,
)
from nexent.skills.skill_manager import SkillManager


CASE_ID = "UT-SDK-AUTO-0B19AA67FBDC7E1E"
NUL = chr(0)
BS = chr(92)


def _directory_link(target, link):
    """Exercise a real resolving directory link without requiring elevation."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
            raise
        # NTFS directory junctions have the same realpath escape boundary and
        # do not require the developer-mode symbolic-link privilege.
        subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True, text=True)


@pytest.mark.stage("D1")
@pytest.mark.case_id(CASE_ID)
def test_skill_path_boundary(tmp_path):
    root = tmp_path / "skills_root"
    root.mkdir()
    root_s = str(root)

    # validate_path_component keeps a valid word and rejects every unsafe shape.
    assert validate_path_component("hello") == "hello"
    assert validate_path_component("my_skill") == "my_skill"

    invalid_names = (
        "",
        "   ",
        ".",
        "..",
        "a/b",
        "a" + BS + "b",
        "evil" + NUL + "name",
        "/etc/passwd",
        "C:evil",
        "C:" + BS + "evil",
        "evil/",
    )
    for value in invalid_names:
        with pytest.raises(InvalidSkillNameError):
            validate_path_component(value)

    with pytest.raises(InvalidSkillNameError):
        validate_path_component(123)

    # resolve_contained_path rejects traversal, absolute, drive and NUL segments.
    for part in ("..", "a/../../b", "/etc", "C:evil", "a" + NUL + "b"):
        with pytest.raises(UnsafeSkillPathError):
            resolve_contained_path(root_s, part)

    # A symlink segment escaping the root must be rejected after realpath.
    outside = tmp_path / "outside"
    outside.mkdir()
    _directory_link(outside, root / "link_escape")
    with pytest.raises(UnsafeSkillPathError):
        resolve_contained_path(root_s, "link_escape")

    (root / "sub").mkdir()
    assert resolve_contained_path(root_s, "sub") == str((root / "sub").resolve())

    # resolve_skill_path rejects invalid names and escaping names.
    with pytest.raises(InvalidSkillNameError):
        resolve_skill_path(root_s, "../evil")

    other_root = tmp_path / "other_root"
    other_root.mkdir()
    with pytest.raises(UnsafeSkillRootError):
        resolve_skill_path(str(other_root), "skill", allowed_root=root_s)

    # Name resolving back to the root itself (symlink) -> UnsafeSkillPathError.
    _directory_link(root, root / "self_link")
    with pytest.raises(UnsafeSkillPathError):
        resolve_skill_path(root_s, "self_link")

    # Name escaping the root via symlink -> UnsafeSkillPathError.
    with pytest.raises(UnsafeSkillPathError):
        resolve_skill_path(root_s, "link_escape")

    # A valid skill name resolves to a real path below the root.
    skill_dir = root / "good_skill"
    skill_dir.mkdir()
    resolved = resolve_skill_path(root_s, "good_skill", allowed_root=root_s)
    assert resolved == str(skill_dir.resolve())
    assert resolved.startswith(os.path.realpath(root_s) + os.sep)

    # SkillManager.resolve_skill_dir reuses the same boundary for tenant names.
    SkillManager._instance = None
    manager = SkillManager(base_skills_dir=root_s)
    for bad_name in ("../evil", "C:evil", "abs/evil"):
        with pytest.raises(InvalidSkillNameError):
            manager.resolve_skill_dir(bad_name, tenant_id=None)
    SkillManager._instance = None
