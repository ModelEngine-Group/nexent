# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Benchmark root discovery works for checkouts and exported source trees."""

from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

import pytest

from sdk.benchmark import paths


@pytest.fixture
def layout():
    # Stay outside the real checkout so its parent markers cannot satisfy the search.
    with TemporaryDirectory(prefix="nexent-benchmark-layout-", dir=Path.home()) as temporary:
        root = Path(temporary).resolve()
        nested = root / "sdk" / "benchmark"
        nested.mkdir(parents=True)
        yield root, nested


def populate_source_markers(root):
    for relative in ["sdk/nexent/__init__.py", "backend/pyproject.toml", "VERSION"]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


@pytest.mark.parametrize("pointer", [False, True], ids=["checkout", "worktree"])
def test_finds_git_directory_or_pointer(layout, pointer):
    root, nested = layout
    marker = root / ".git"
    if pointer:
        marker.write_text("gitdir: elsewhere", encoding="utf-8")
    else:
        marker.mkdir()
    assert paths._find_project_root(str(nested)) == str(root)


def test_finds_exported_source_without_git(layout):
    root, nested = layout
    populate_source_markers(root)
    assert not (root / ".git").exists()
    assert paths._find_project_root(str(nested)) == str(root)


@pytest.mark.parametrize("missing", ["sdk/nexent/__init__.py", "backend/pyproject.toml", "VERSION"])
def test_rejects_incomplete_exported_layout(layout, missing):
    root, nested = layout
    populate_source_markers(root)
    (root / missing).unlink()
    with pytest.raises(RuntimeError, match="project root"):
        paths._find_project_root(str(nested))


def test_import_initializes_all_paths_from_exported_source(layout, monkeypatch):
    root, nested = layout
    populate_source_markers(root)
    script = nested / "paths.py"
    script.write_bytes(Path(paths.__file__).read_bytes())
    monkeypatch.setattr(sys, "path", list(sys.path))
    exported = runpy.run_path(str(script))
    assert exported["PROJECT_ROOT"] == str(root)
    assert exported["SDK_DIR"] == str(root / "sdk")
    assert exported["BACKEND_DIR"] == str(root / "backend")
    for target in [root, root / "sdk", root / "backend"]:
        assert sys.path.count(str(target)) == 1
