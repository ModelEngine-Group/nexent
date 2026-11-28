# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit coverage for Docker agent workspace directory initialization."""

import subprocess

import pytest

from .test_workbench_publication import BASH, shell_function


@pytest.mark.parametrize("state", ["fresh", "existing", "conflict"])
def test_prepare_agent_workspace(tmp_path, state):
    root = tmp_path / "nexent data"
    root.mkdir()
    workspace = root / "agent-workspace"
    if state == "existing":
        workspace.mkdir()
        (workspace / "input").write_text("keep-workspace-data", encoding="utf-8")
    elif state == "conflict":
        workspace.write_text("existing-file", encoding="utf-8")

    script = shell_function("docker", "prepare_directory_and_data") + r'''
ROOT_DIR="$1"
SQL_DIR="$ROOT_DIR/sql"
DOCKER_ASSETS_DIR="$ROOT_DIR/assets"
create_dir_with_permission() { :; }
prepare_project_config_dir() { echo "PROJECT_CONFIG_STARTED"; }
migrate_legacy_project_config() { :; }
chmod() { :; }
cp() { :; }
prepare_directory_and_data
'''
    result = subprocess.run(
        [BASH, "-c", script, "workspace-test", root.as_posix()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=20,
    )

    if state == "conflict":
        assert result.returncode == 1
        assert "PROJECT_CONFIG_STARTED" not in result.stdout
        assert workspace.read_text(encoding="utf-8") == "existing-file"
    else:
        assert result.returncode == 0, result.stderr
        assert workspace.is_dir()
        if state == "existing":
            assert (workspace / "input").read_text(encoding="utf-8") == "keep-workspace-data"
