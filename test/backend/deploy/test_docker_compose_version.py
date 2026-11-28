# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Docker deployment identifies Compose command variants from version output."""

import pytest

from .test_workbench_publication import run_shell, shell_function


@pytest.mark.parametrize(
    ("plugin_output", "standalone_output", "expected"),
    [
        ("Docker Compose version 2.40.3+ds1-0ubuntu1~24.04.1", "docker-compose version 1.29.2", "v2 2.40.3"),
        ("Docker Compose version v2.40.3", "docker-compose version 1.29.2", "v2 2.40.3"),
        ("", "docker-compose version 1.29.2, build 5becea4c", "v1 1.29.2"),
        ("Docker Compose version unavailable", "", "unknown"),
    ],
    ids=["ubuntu-plugin", "prefixed-plugin", "standalone-fallback", "unknown"],
)
def test_get_compose_version(monkeypatch, plugin_output, standalone_output, expected):
    monkeypatch.setenv("FIXTURE_PLUGIN_VERSION", plugin_output)
    monkeypatch.setenv("FIXTURE_STANDALONE_VERSION", standalone_output)

    result = run_shell(shell_function("docker", "get_compose_version") + r'''
set -e
docker() {
  [ "$*" = "compose version" ] && [ -n "$FIXTURE_PLUGIN_VERSION" ] || return 1
  printf '%s\n' "$FIXTURE_PLUGIN_VERSION"
}
docker-compose() {
  [ "$*" = "--version" ] && [ -n "$FIXTURE_STANDALONE_VERSION" ] || return 1
  printf '%s\n' "$FIXTURE_STANDALONE_VERSION"
}
version_info=$(get_compose_version)
printf '%s\n' "$version_info"
''')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
