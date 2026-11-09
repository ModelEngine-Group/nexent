# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retire only the old Compose container while keeping images and volumes intact."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def function(name):
    source = (ROOT / "deploy/docker/deploy.sh").read_text(encoding="utf-8")
    return re.search(r"^" + name + r"\(\) \{.*?^\}", source, re.M | re.S).group()


@pytest.mark.parametrize("identity,missing,expected,mutates", [
    ("nexent/nexent-northbound", False, 0, True),
    ("", True, 0, False), ("other/nexent-northbound", False, 1, False),
    ("nexent/other", False, 1, False),
])
def test_retirement_checks_ownership_and_never_deletes_images_or_volumes(identity, missing, expected, mutates):
    executable = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    script = """docker() {
      if [ "$1" = inspect ]; then
        [ "$FIXTURE_MISSING" = true ] && return 1
        printf '%s' "$FIXTURE_IDENTITY"
        return 0
      fi
      printf 'docker:%s\n' "$*" >&2
    }
    """ + function("retire_legacy_northbound_container") + "\nretire_legacy_northbound_container"
    env = {**os.environ, "FIXTURE_IDENTITY": identity, "FIXTURE_MISSING": "true" if missing else "false"}
    result = subprocess.run([executable, "-c", script], capture_output=True, text=True, encoding="utf-8", env=env, timeout=10)
    assert result.returncode == expected
    commands = [line for line in result.stderr.splitlines() if line.startswith("docker:")]
    assert commands == (["docker:update --restart=no nexent-northbound", "docker:stop --time 30 nexent-northbound",
                         "docker:rm nexent-northbound"] if mutates else [])


def test_old_container_is_retired_before_gateway_startup():
    source = function("deploy_core_services")
    assert source.index("config --quiet") < source.index("retire_legacy_northbound_container")
    assert source.index("retire_legacy_northbound_container") < source.index('up -d "${core_services[@]}"')
    assert "nexent-gateway" in source and "nexent-northbound" not in source
    assert not (ROOT / "backend/northbound_service.py").exists()


def test_invalid_composition_does_not_stop_the_legacy_service():
    executable = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    script = """docker() { printf 'unexpected docker mutation\n' >&2; return 1; }
    mock_compose() { printf 'compose:%s\n' "$*" >&2; return 9; }
    DEPLOYMENT_SELECTED_DOCKER_SERVICES=nexent-gateway
    docker_compose_command=mock_compose
    ROOT_ENV_FILE=fixture
    COMPOSE_DIR=fixture
    COMPOSE_FILE_SUFFIX=.yml
    """ + function("retire_legacy_northbound_container") + "\n" + function("deploy_core_services") + "\ndeploy_core_services"
    result = subprocess.run([executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 1 and "config --quiet" in result.stderr
    assert "unexpected docker mutation" not in result.stderr
    assert "legacy container was left unchanged" in result.stdout


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_composition_defines_only_unified_gateway_entry(filename):
    services = yaml.safe_load((ROOT / "deploy/docker/compose" / filename).read_text(encoding="utf-8"))["services"]
    assert "nexent-northbound" not in services
    assert services["nexent-gateway"]["container_name"] == "nexent-gateway"
    assert "NEXENT_GATEWAY_IMAGE" in services["nexent-gateway"]["image"]
    assert "NEXENT_POSTGRES_PASSWORD" in services["nexent-gateway"]["environment"]
    assert all("northbound_service.py" not in str(service) for service in services.values())


def test_helm_dependency_and_selectors_no_longer_create_legacy_resources():
    chart = ROOT / "deploy/k8s/helm/nexent"
    dependencies = yaml.safe_load((chart / "Chart.yaml").read_text(encoding="utf-8"))["dependencies"]
    assert "nexent-gateway" in {item["name"] for item in dependencies}
    assert "nexent-northbound" not in {item["name"] for item in dependencies}
    assert not (chart / "charts/nexent-northbound").exists()
    for path in (chart / "charts/nexent-gateway/templates").glob("*.yaml"):
        assert "nexent-northbound" not in path.read_text(encoding="utf-8")


def test_mcp_helm_explicit_gateway_environment_overrides_old_root_secret():
    source = (ROOT / "deploy/k8s/helm/nexent/charts/nexent-mcp/templates/deployment.yaml").read_text(encoding="utf-8")
    block = source.split("          env:", 1)[1].split('{{ include "nexent.backendPlatformEnv"', 1)[0]
    values = yaml.safe_load(block)
    assert {row["name"] for row in values} == {"GATEWAY_AUTH_ENABLED", "GATEWAY_SERVICE_URL"}
    gateway = next(row for row in values if row["name"] == "GATEWAY_SERVICE_URL")
    assert gateway["valueFrom"]["configMapKeyRef"] == {"name": "nexent-config", "key": "GATEWAY_SERVICE_URL"}
    assert next(row for row in values if row["name"] == "GATEWAY_AUTH_ENABLED")["value"] == "true"
