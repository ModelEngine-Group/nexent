# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared Config pods must avoid shadowing Python standard-library modules."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("paused", [False, True])
def test_config_chart_launches_the_package_module(paused):
    helm = shutil.which("helm")
    assert helm, "Helm is required for backend launcher template verification"
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [helm, "template", "launcher-test", str(root / "deploy/k8s/helm/nexent"),
         "--set", f"global.businessPaused={str(paused).lower()}",
         "--set", "global.sandboxProvider=docker",
         "--set", "nexent-runtime.replicaCount=1",
         "--set", "nexent-common.secrets.jwtSecret=isolated-launcher-fixture"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    documents = [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]
    deployment = next(doc for doc in documents if doc.get("kind") == "Deployment"
                      and doc["metadata"]["name"] == "nexent-config")
    config = next(container for container in deployment["spec"]["template"]["spec"]["containers"]
                  if container["name"] == "nexent-config")
    assert config["command"] == [
        "/opt/nexent/scripts/start-backend.sh", "python", "-m", "backend.http.config_service",
    ]
    assert {"name": "NEXENT_SQL_SKIP_IF_CURRENT", "value": "true"} in config["env"]
    jobs = [doc for doc in documents if doc.get("kind") == "Job"
            and "-system-bootstrap-" in doc["metadata"]["name"]]
    assert bool(jobs) is paused
    if paused:
        bootstrap = jobs[0]["spec"]["template"]["spec"]["containers"][0]
        assert {"name": "NEXENT_SQL_SKIP_IF_CURRENT", "value": "false"} in bootstrap["env"]
        assert bootstrap["command"][:2] == ["sh", "-c"]
        assert "python -m management.services.agent.system_initialize" in bootstrap["command"][2]
        assert "python -m management.services.agent.system_release" in bootstrap["command"][2]


@pytest.mark.parametrize("suffix", [".yml", ".prod.yml"])
def test_docker_config_checks_migration_records_before_executing_sql(suffix):
    root = Path(__file__).resolve().parents[3]
    compose = root / f"deploy/docker/compose/docker-compose{suffix}"
    config = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]["nexent-config"]
    assert config["environment"]["NEXENT_SQL_STARTUP_MODE"] == "migrate"
    assert config["environment"]["NEXENT_SQL_SKIP_IF_CURRENT"] == "true"


def test_data_process_chart_skips_ops_initialization_with_shared_monitoring_enabled():
    helm = shutil.which("helm")
    assert helm, "Helm is required for backend launcher template verification"
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [helm, "template", "launcher-test", str(root / "deploy/k8s/helm/nexent"),
         "--set", "global.sandboxProvider=docker",
         "--set", "nexent-runtime.replicaCount=1",
         "--set", "nexent-common.secrets.jwtSecret=isolated-launcher-fixture"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    documents = [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]
    deployment = next(doc for doc in documents if doc.get("kind") == "Deployment"
                      and doc["metadata"]["name"] == "nexent-data-process")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    settings = {entry["name"]: entry for entry in container["env"]}
    assert settings["NEXENT_SQL_STARTUP_MODE"]["value"] == "off"
    assert "OPS_MONITORING_ENABLED" not in settings
    assert "backend.http.data_process_service" in container["command"][-1]
