# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for shared deployment settings emitted to the ops chart."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("policy", ["development", "production"])
@pytest.mark.parametrize("component", ["application", "infrastructure"])
@pytest.mark.parametrize("port", ["5016", "15016"])
def test_ops_helm_values_follow_component_and_runtime_settings(policy, component, port):
    git = shutil.which("git")
    git_bash = Path(git).resolve().parent.parent / "bin/bash.exe" if git else None
    bash = (
        str(git_bash)
        if os.name == "nt" and git_bash and git_bash.is_file()
        else shutil.which("bash")
    )
    assert bash, "Bash is required for deployment configuration tests"
    script = """
set -e
source "$1/deploy/common/common.sh"
DEPLOYMENT_COMPONENTS="$2"
DEPLOYMENT_PORT_POLICY="$3"
DEPLOYMENT_IMAGE_SOURCE=general
DEPLOYMENT_APP_VERSION=latest
deployment_apply_image_source
NEXENT_IMAGE=example.invalid/shared/backend:ops-check
OPS_PORT="$4"
deployment_render_helm_chart_values
"""
    result = subprocess.run(
        [
            bash,
            "--noprofile",
            "--norc",
            "-c",
            script,
            "ops-values",
            REPO.as_posix(),
            component,
            policy,
            port,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    values = yaml.safe_load(result.stdout)
    settings = values["nexent-ops"]
    assert (
        values["nexent-web"]["config"]["opsHttpBackend"] == f"http://nexent-ops:{port}"
    )
    assert settings["enabled"] is (component == "application")
    assert settings["images"]["backend"] == {
        "repository": "example.invalid/shared/backend",
        "tag": "ops-check",
        "pullPolicy": "IfNotPresent",
    }
    assert settings["service"] == {
        "type": "NodePort",
        "port": int(port),
        "nodePort": 30016,
    }
    assert "config" not in settings


@pytest.mark.parametrize("enabled", [False, True])
def test_ops_chart_mounts_trajectory_and_supplies_pg_configuration_only_when_enabled(
    enabled,
):
    helm = shutil.which("helm")
    assert helm, "Helm is required for operations deployment template proof"
    chart = REPO / "deploy/k8s/helm/nexent/charts/nexent-ops"
    result = subprocess.run(
        [
            helm,
            "template",
            "ops-test",
            str(chart),
            "--set",
            f"global.monitoring.trajectoryReadEnabled={str(enabled).lower()}",
            "--set",
            "global.monitoring.trajectoryRootDir=/srv/trajectory",
            "--set",
            "global.sharedStorage.trajectory.existingClaim=shared-archives",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    deployment = next(
        doc for doc in yaml.safe_load_all(result.stdout) if doc["kind"] == "Deployment"
    )
    spec = deployment["spec"]["template"]["spec"]
    container = spec["containers"][0]
    mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
    volumes = {volume["name"]: volume for volume in spec["volumes"]}
    assert ("ops-trajectory" in mounts) is enabled
    assert ("envFrom" in container) is enabled
    if enabled:
        assert mounts["ops-trajectory"]["mountPath"] == "/srv/trajectory"
        assert (
            volumes["ops-trajectory"]["persistentVolumeClaim"]["claimName"]
            == "shared-archives"
        )
        assert container["envFrom"] == [
            {"configMapRef": {"name": "nexent-config"}},
            {"secretRef": {"name": "nexent-env"}},
            {"secretRef": {"name": "nexent-monitoring-env"}},
            {"secretRef": {"name": "nexent-secrets"}},
        ]
    assert (
        next(
            item["value"]
            for item in container["env"]
            if item["name"] == "NEXENT_SQL_STARTUP_MODE"
        )
        == "off"
    )


def test_docker_ops_uses_monitoring_configuration_and_same_archive_as_runtime():
    directory = REPO / "deploy/docker/compose"
    ops = yaml.safe_load((directory / "docker-compose-ops.yml").read_text())[
        "services"
    ]["nexent-ops"]
    assert ops["env_file"] == ["../../env/.env", "../../env/monitoring.env"]
    archive_mount = (
        "${ROOT_DIR}/trajectory:${TRAJECTORY_ROOT_DIR:-/mnt/nexent-data/trajectory}"
    )
    assert archive_mount in ops["volumes"]
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = yaml.safe_load((directory / filename).read_text())["services"]
        assert archive_mount in services["nexent-runtime"]["volumes"]
        assert (
            "OPS_HTTP_BACKEND=http://nexent-ops:${OPS_PORT:-5016}"
            in services["nexent-web"]["environment"]
        )
