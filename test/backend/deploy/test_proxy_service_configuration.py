# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for indexing and Northbound proxy configuration."""

import os
import subprocess

import pytest
import yaml

from .test_workbench_publication import BASH, REPO, shell_function

GATEWAY_URL = "http://nexent-gateway:5013/api"
REMOTE_URL = "https://remote.example.test/prefix/api"


def run_bash(script, env):
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=REPO,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "configured,expected",
    [("", GATEWAY_URL), ("http://nexent-northbound:5013/api", GATEWAY_URL), (REMOTE_URL, REMOTE_URL)],
)
def test_k8s_renders_the_effective_web_northbound_url(tmp_path, configured, expected):
    generated_values = tmp_path / "runtime-values.yaml"
    script = "\n".join(
        shell_function("k8s", name)
        for name in (
            "yaml_quote",
            "env_or_default",
            "render_yaml_literal_file",
            "effective_northbound_api_server",
            "render_k8s_runtime_config_values",
        )
    )
    script += '''
DEPLOY_ROOT="$PWD/deploy"
SQL_INIT_FILE="$DEPLOY_ROOT/sql/init.sql"
render_k8s_runtime_config_values "$FIXTURE_VALUES"
'''
    run_bash(script, {"NORTHBOUND_API_SERVER": configured, "FIXTURE_VALUES": generated_values.as_posix()})
    config = yaml.safe_load(generated_values.read_text(encoding="utf-8"))["nexent-common"]["config"]
    assert config["services"]["northboundServer"] == expected


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_uses_independent_images_without_data_process(filename):
    compose_file = REPO / "deploy" / "docker" / "compose" / filename
    services = yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"]
    assert "nexent-data-process" not in services
    assert "nexent/nexent-management:" in services["nexent-config"]["image"]
    assert "nexent/nexent-runtime:" in services["nexent-runtime"]["image"]
    assert all("nexent-data-process" not in service.get("depends_on", {}) for service in services.values())
