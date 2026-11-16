# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Request-local path reuse must preserve standalone containment semantics."""

import os

import pytest

from nexent.skills.paths import (
    InvalidSkillNameError,
    SkillPathResolver,
    UnsafeSkillPathError,
    UnsafeSkillRootError,
    resolve_skill_path,
)

TARGETS = [("config", "config.yaml"), ("config", "schema.yaml")]


@pytest.fixture
def roots(tmp_path):
    root = tmp_path / "skills" / "tenant"
    (root / "sample" / "config").mkdir(parents=True)
    return root, tmp_path / "skills"


def symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Host cannot create symlinks: {exc}")


def test_many_paths_match_standalone_and_reuse_roots(roots, mocker):
    root, allowed = roots
    expected = [resolve_skill_path(str(root), "sample", *parts, allowed_root=str(allowed)) for parts in TARGETS]
    realpath = mocker.patch.object(os.path, "realpath", wraps=os.path.realpath)
    resolver = SkillPathResolver(str(root), allowed_root=str(allowed))
    assert realpath.call_count == 2
    for _ in range(3):
        assert resolver.resolve_many("sample", TARGETS) == expected
    assert realpath.call_count == 2 + 3 * 3


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b", "", ".", "..", "/tmp", "C:\\tmp", "a\x00b"])
def test_invalid_skill_names_remain_rejected(roots, name):
    root, allowed = roots
    with pytest.raises(InvalidSkillNameError):
        SkillPathResolver(str(root), allowed_root=str(allowed)).resolve_many(name, TARGETS)


@pytest.mark.parametrize("parts", [("..", "escape"), ("config/../escape",), ("/tmp/file",),
                                    ("C:\\tmp\\file",), ("config", "bad\x00name")])
def test_invalid_relative_parts_remain_rejected(roots, parts):
    root, allowed = roots
    with pytest.raises(UnsafeSkillPathError):
        SkillPathResolver(str(root), allowed_root=str(allowed)).resolve_many("sample", [parts])


def test_root_outside_storage_is_rejected(roots, tmp_path):
    _, allowed = roots
    with pytest.raises(UnsafeSkillRootError):
        SkillPathResolver(str(tmp_path / "outside"), allowed_root=str(allowed))


def test_root_without_allowlist_and_empty_targets(roots):
    root, _ = roots
    resolver = SkillPathResolver(str(root))
    assert resolver.resolve_many("sample", []) == []
    assert resolver.resolve_many("sample", [("config", "nested/file.yaml")]) == [
        resolve_skill_path(str(root), "sample", "config", "nested/file.yaml")]


@pytest.mark.parametrize("level", ["skill", "config", "file"])
def test_escaping_symlinks_are_rejected(roots, tmp_path, level):
    root, allowed = roots
    outside = tmp_path / "outside"
    outside.mkdir()
    if level == "skill":
        symlink(root / "linked", outside, directory=True)
        name = "linked"
    elif level == "config":
        (root / "sample/config").rmdir()
        symlink(root / "sample/config", outside, directory=True)
        name = "sample"
    else:
        (outside / "config.yaml").write_text("secret: true")
        symlink(root / "sample/config/config.yaml", outside / "config.yaml")
        name = "sample"
    with pytest.raises(UnsafeSkillPathError):
        SkillPathResolver(str(root), allowed_root=str(allowed)).resolve_many(name, TARGETS)


def test_internal_file_symlink_matches_existing_policy(roots):
    root, allowed = roots
    target = root / "sample" / "shared.yaml"
    target.write_text("value: true")
    symlink(root / "sample/config/config.yaml", target)
    resolver = SkillPathResolver(str(root), allowed_root=str(allowed))
    assert resolver.resolve_many("sample", TARGETS) == [
        resolve_skill_path(str(root), "sample", *parts, allowed_root=str(allowed)) for parts in TARGETS]


def test_changed_ancestor_symlink_is_checked_on_every_resolution(roots, tmp_path):
    root, allowed = roots
    resolver = SkillPathResolver(str(root), allowed_root=str(allowed))
    resolver.resolve_many("sample", TARGETS)
    original = root / "sample"
    original.rename(root / "saved")
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink(original, outside, directory=True)
    with pytest.raises(UnsafeSkillPathError):
        resolver.resolve_many("sample", TARGETS)


def test_internal_directory_symlink_remains_allowed(roots):
    root, allowed = roots
    folder = root / "sample/shared"
    folder.mkdir()
    (root / "sample/config").rmdir()
    symlink(root / "sample/config", folder, directory=True)
    resolver = SkillPathResolver(str(root), allowed_root=str(allowed))
    assert resolver.resolve_many("sample", TARGETS) == [
        resolve_skill_path(str(root), "sample", *parts, allowed_root=str(allowed)) for parts in TARGETS]


def test_changed_leaf_symlink_is_checked_even_in_same_context(roots, tmp_path):
    root, allowed = roots
    target = root / "sample/shared.yaml"
    target.write_text("value: true")
    leaf = root / "sample/config/config.yaml"
    symlink(leaf, target)
    resolver = SkillPathResolver(str(root), allowed_root=str(allowed))
    resolver.resolve_many("sample", TARGETS)
    leaf.unlink()
    outside = tmp_path / "external.yaml"
    outside.write_text("outside: true")
    symlink(leaf, outside)
    with pytest.raises(UnsafeSkillPathError):
        resolver.resolve_many("sample", TARGETS)


def test_other_skill_in_same_tenant_is_not_a_valid_file_target(roots):
    root, allowed = roots
    sibling = root / "other/config.yaml"
    sibling.parent.mkdir()
    sibling.write_text("other: true")
    symlink(root / "sample/config/config.yaml", sibling)
    with pytest.raises(UnsafeSkillPathError):
        SkillPathResolver(str(root), allowed_root=str(allowed)).resolve_many("sample", TARGETS)
