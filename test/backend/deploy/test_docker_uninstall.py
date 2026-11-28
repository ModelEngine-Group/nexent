# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Test the Docker uninstall entry point with isolated commands and data."""

import os
import shlex
import shutil
import subprocess

import pytest

from .test_workbench_publication import BASH, REPO


@pytest.fixture
def uninstall(tmp_path, monkeypatch):
    deploy = tmp_path / "project" / "deploy"
    script = deploy / "docker" / "uninstall.sh"
    compose = script.parent / "compose"
    compose.mkdir(parents=True)
    for filename in ("docker-compose-monitoring.yml", "docker-compose.prod.yml", "docker-compose.yml"):
        (compose / filename).touch()
    (deploy / "common").mkdir()
    (deploy / "env").mkdir()
    shutil.copyfile(REPO / "deploy/docker/uninstall.sh", script)
    shutil.copyfile(REPO / "deploy/common/common.sh", deploy / "common/common.sh")

    data = tmp_path / "host data"
    user_home = tmp_path / "home"
    (deploy / "env/.env").write_text(f"ROOT_DIR={shlex.quote(data.as_posix())}\n", encoding="utf-8")
    sentinels = (
        data / "agent-workspace/run/output.txt",
        data / "postgresql/data.txt",
        user_home / "nexent/workspace.txt",
    )
    for path in sentinels:
        path.parent.mkdir(parents=True)
        path.write_text(path.name, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$UNINSTALL_TEST_CALLS"
fail_at() {
  if [ "$UNINSTALL_TEST_FAILURE" = "$1" ]; then
    printf 'simulated error at %s\n' "$1" >&2
    exit 71
  fi
}
case "$1:${2:-}" in
  compose:version) printf 'Docker Compose version v2.24.0\n' ;;
  compose:*)
    while [ "$#" -gt 1 ] && [ "$1" != "-f" ]; do shift; done
    [ "$1" = "-f" ] && [ "$#" -gt 1 ] || exit 99
    fail_at "${2##*/}"
    ;;
  ps:*)
    fail_at list-containers
    if [ "$2" = "-a" ] && [ "$UNINSTALL_TEST_RESOURCES" = true ]; then
      printf 'nexent-phoenix\n'
    fi
    ;;
  rm:-f) fail_at remove-container ;;
  volume:ls)
    fail_at list-volumes
    if [ "$UNINSTALL_TEST_RESOURCES" = true ]; then
      printf 'monitor_phoenix-data\nnexent-cache\n'
    fi
    ;;
  volume:rm)
    if [ "${*:3}" = "-f monitor_phoenix-data" ]; then
      fail_at remove-monitoring-volume
    else
      fail_at remove-named-volume
    fi
    ;;
  *) exit 99 ;;
esac
''', encoding="utf-8")
    fake_docker.chmod(0o700)
    calls_path = tmp_path / "docker.calls"
    monkeypatch.setenv("HOME", user_home.as_posix())
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DEPLOYMENT_LANG", "en")
    monkeypatch.setenv("UNINSTALL_TEST_CALLS", calls_path.as_posix())

    def run(*args, failure="", resources=True):
        monkeypatch.setenv("UNINSTALL_TEST_FAILURE", failure)
        monkeypatch.setenv("UNINSTALL_TEST_RESOURCES", str(resources).lower())
        result = subprocess.run(
            [BASH, script.as_posix(), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=20,
        )
        return result, sentinels, calls_path.read_text(encoding="utf-8")

    return run


@pytest.mark.parametrize("failure", [
    "docker-compose-monitoring.yml",
    "docker-compose.prod.yml",
    "docker-compose.yml",
    "list-containers",
    "remove-container",
    "list-volumes",
    "remove-monitoring-volume",
    "remove-named-volume",
])
def test_uninstall_failure_preserves_host_data(uninstall, failure):
    result, sentinels, _ = uninstall("--delete-volumes", "true", failure=failure)

    assert result.returncode != 0, result.stdout
    assert f"simulated error at {failure}" in result.stderr
    assert "Docker uninstall failed. Host data directories were preserved." in result.stderr
    assert "Docker deployment removed." not in result.stdout
    assert all(path.read_text(encoding="utf-8") == path.name for path in sentinels)


@pytest.mark.parametrize("arguments,deleted", [((), False), (("--keep-volumes",), False), (("--delete-volumes", "true"), True)])
def test_successful_uninstall_respects_delete_volumes(uninstall, arguments, deleted):
    result, sentinels, calls = uninstall(*arguments)

    assert result.returncode == 0, result.stderr
    assert "Docker deployment removed." in result.stdout
    assert "down --remove-orphans" in calls
    for path in sentinels:
        if deleted:
            assert not path.exists()
        else:
            assert path.read_text(encoding="utf-8") == path.name


def test_missing_docker_resources_allow_host_data_cleanup(uninstall):
    result, sentinels, _ = uninstall("--delete-volumes", "true", resources=False)

    assert result.returncode == 0, result.stderr
    assert all(not path.exists() for path in sentinels)
