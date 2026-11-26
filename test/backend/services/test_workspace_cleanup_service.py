# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from unittest.mock import patch

import pytest

from infrastructure.workspace_cleanup import cleanup_orphaned_agent_workspaces


def test_cleanup_orphaned_agent_workspaces_removes_only_run_directories(tmp_path):
    root = tmp_path / "workdir"
    user_dir = root / "user-1"
    valid_run = user_dir / ("a" * 32)
    invalid_run = user_dir / "keep-this-directory"
    (valid_run / "outputs").mkdir(parents=True)
    (valid_run / "outputs" / "result.txt").write_text("temporary", encoding="utf-8")
    invalid_run.mkdir()
    (invalid_run / "keep.txt").write_text("persistent", encoding="utf-8")

    removed = cleanup_orphaned_agent_workspaces(str(root))

    assert removed == 1
    assert not valid_run.exists()
    assert invalid_run.exists()


def test_cleanup_orphaned_agent_workspaces_removes_empty_user_directory(tmp_path):
    root = tmp_path / "workdir"
    user_dir = root / "user-1"
    (user_dir / ("b" * 32)).mkdir(parents=True)

    removed = cleanup_orphaned_agent_workspaces(str(root))

    assert removed == 1
    assert not user_dir.exists()
    assert root.exists()


def test_cleanup_orphaned_agent_workspaces_ignores_missing_root(tmp_path):
    assert cleanup_orphaned_agent_workspaces(str(tmp_path / "missing")) == 0


def test_cleanup_orphaned_agent_workspaces_skips_non_directory_user_entry(tmp_path):
    root = tmp_path / "workdir"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    assert cleanup_orphaned_agent_workspaces(str(root)) == 0
    assert marker.exists()


def test_cleanup_orphaned_agent_workspaces_logs_run_removal_failure(tmp_path):
    root = tmp_path / "workdir"
    run_dir = root / "user-1" / ("c" * 32)
    run_dir.mkdir(parents=True)

    with patch(
        "infrastructure.workspace_cleanup.shutil.rmtree",
        side_effect=OSError("busy"),
    ), patch("infrastructure.workspace_cleanup.logger.error") as error:
        removed = cleanup_orphaned_agent_workspaces(str(root))

    assert removed == 0
    assert run_dir.exists()
    error.assert_called_once()


def test_strict_workspace_cleanup_propagates_run_removal_failure(tmp_path):
    run_dir = tmp_path / "user-1" / ("d" * 32)
    run_dir.mkdir(parents=True)

    with patch("infrastructure.workspace_cleanup.shutil.rmtree", side_effect=PermissionError("busy")):
        with pytest.raises(PermissionError, match="busy"):
            cleanup_orphaned_agent_workspaces(str(tmp_path), strict=True)

    assert run_dir.exists()


def test_cleanup_preserves_symlinked_run_and_its_target(tmp_path):
    root = tmp_path / "workdir"
    user_dir = root / "user-1"
    user_dir.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    symlink = user_dir / ("e" * 32)
    symlink.symlink_to(external, target_is_directory=True)

    assert cleanup_orphaned_agent_workspaces(str(root), strict=True) == 0
    assert symlink.is_symlink()
    assert external.exists()
