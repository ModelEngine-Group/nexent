# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for indexing and Northbound proxy configuration."""

import os
import subprocess

import pytest
import yaml

from .test_workbench_publication import BASH, REPO, shell_function

GATEWAY_URL = "http://nexent-gateway:5013/api"
LEGACY_INDEX_URL = "http://nexent-config:5010/api"
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
def test_compose_worker_reads_index_endpoint_from_the_env_file(filename):
    compose_file = REPO / "deploy" / "docker" / "compose" / filename
    worker = yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"]["nexent-data-process"]
    assert "ELASTICSEARCH_SERVICE" not in worker["environment"]
    assert "../../env/.env" in worker["env_file"]
    assert "nexent-gateway" not in worker["depends_on"]


@pytest.mark.parametrize(
    "components,configured,expected",
    [
        ("infrastructure,application,data-process", LEGACY_INDEX_URL, GATEWAY_URL),
        ("application,data-process", REMOTE_URL, REMOTE_URL),
        ("data-process", REMOTE_URL, REMOTE_URL),
        ("data-process", LEGACY_INDEX_URL, LEGACY_INDEX_URL),
    ],
)
def test_docker_upgrade_only_migrates_the_old_full_stack_default(tmp_path, components, configured, expected):
    env_file = tmp_path / ".env"
    env_file.write_text(f'ELASTICSEARCH_SERVICE="{configured}"\nUNCHANGED=1\n', encoding="utf-8")
    script = 'source deploy/common/common.sh\n' + shell_function("docker", "migrate_legacy_index_gateway")
    script += '''
ROOT_ENV_FILE="$FIXTURE_ENV_FILE"
DEPLOYMENT_COMPONENTS="$FIXTURE_COMPONENTS"
migrate_legacy_index_gateway && migrate_legacy_index_gateway
'''
    run_bash(script, {"FIXTURE_ENV_FILE": env_file.as_posix(), "FIXTURE_COMPONENTS": components})
    assert env_file.read_text(encoding="utf-8") == f'ELASTICSEARCH_SERVICE="{expected}"\nUNCHANGED=1\n'
