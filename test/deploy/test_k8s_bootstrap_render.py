# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Render real Helm manifests and execute the generated bootstrap command safely."""

import os
import shlex
import subprocess

import pytest
from test_k8s_helm import (
    _application_dynamic_args,
    _application_existing_args,
    _documents,
    _template,
)
from test_k8s_helm import (
    chart_dirs as _chart_dirs,
)

BUSINESS = {"nexent-config", "nexent-runtime", "nexent-mcp", "nexent-northbound", "nexent-web", "nexent-data-process"}
chart_dirs = _chart_dirs


@pytest.mark.parametrize("storage", ["local", "dynamic", "existing"])
def test_paused_release_creates_isolated_job_with_shared_environment_and_storage(chart_dirs, storage):
    args = _application_dynamic_args() if storage == "dynamic" else _application_existing_args() if storage == "existing" else []
    result = _template(chart_dirs["application"], "nexent", [*args, "--set", "global.businessPaused=true",
        "--set", "nexent-config.images.backend.tag=review-new"])
    assert result.returncode == 0, result.stderr
    docs = _documents(result.stdout)
    deployments = {doc["metadata"]["name"]: doc for doc in docs if doc.get("kind") == "Deployment"}
    assert all(deployments[name]["spec"]["replicas"] == 0 for name in BUSINESS)
    assert all(doc["spec"]["replicas"] == 1 for name, doc in deployments.items() if name.startswith("nexent-supabase"))
    job, = [doc for doc in docs if doc.get("kind") == "Job"]
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] > 0
    pod = job["spec"]["template"]
    assert pod["metadata"]["labels"]["app"] == "nexent-system-bootstrap"
    config = deployments["nexent-config"]["spec"]["template"]["spec"]
    assert pod["spec"]["restartPolicy"] == "Never"
    assert pod["spec"]["volumes"] == config["volumes"]
    assert pod["spec"]["serviceAccountName"] == config["serviceAccountName"]
    container = pod["spec"]["containers"][0]
    original = config["containers"][0]
    for key in ("image", "env", "envFrom", "volumeMounts", "resources"):
        assert container[key] == original[key]
    assert container["image"].endswith(":review-new")
    assert "ports" not in container and "livenessProbe" not in container and "startupProbe" not in container
    assert "exec" in container["readinessProbe"]


def test_active_release_restores_declared_replicas_and_removes_bootstrap_job(chart_dirs):
    result = _template(chart_dirs["application"], "nexent", [*_application_dynamic_args(),
        "--set", "global.businessPaused=false", "--set", "nexent-web.replicaCount=3"])
    assert result.returncode == 0, result.stderr
    docs = _documents(result.stdout)
    assert not [doc for doc in docs if doc.get("kind") == "Job"]
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc["metadata"]["name"] in BUSINESS:
            assert doc["spec"]["replicas"] == (3 if doc["metadata"]["name"] == "nexent-web" else 1)


@pytest.mark.parametrize("failure", ["", "sql", "initialize", "release"])
def test_rendered_job_command_orders_sql_initialize_release_and_propagates_errors(chart_dirs, tmp_path, failure):
    result = _template(chart_dirs["application"], "nexent", [*_application_dynamic_args(), "--set", "global.businessPaused=true"])
    assert result.returncode == 0, result.stderr
    job, = [doc for doc in _documents(result.stdout) if doc.get("kind") == "Job"]
    command = job["spec"]["template"]["spec"]["containers"][0]["command"][2]
    for module in ("system_initialize", "system_release"):
        path = tmp_path / f"management/services/agent/{module}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    (tmp_path / "start").write_text("")
    entrypoint = tmp_path / "entrypoint"
    entrypoint.write_text('#!/bin/sh\necho SQL\n[ "$FAILED_STAGE" != sql ] || exit 13\nexec "$@"\n')
    entrypoint.chmod(0o755)
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\necho "PYTHON:$2"\ncase "$2" in *"$FAILED_STAGE"*) [ -z "$FAILED_STAGE" ] || exit 14 ;; esac\n')
    python.chmod(0o755)
    command = command.replace("/opt/nexent/scripts/start-backend.sh", shlex.quote(str(entrypoint)))
    command = command.replace("/opt/backend", shlex.quote(str(tmp_path)))
    command = command.replace("/tmp/nexent-bootstrap-ready", shlex.quote(str(tmp_path / "ready")))
    command = command.replace("/tmp/nexent-bootstrap-start", shlex.quote(str(tmp_path / "start")))
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAILED_STAGE": failure}
    executed = subprocess.run(["bash", "-c", command], check=False, env=environment, capture_output=True, text=True, timeout=10)
    expected = ["SQL", "PYTHON:management.services.agent.system_initialize", "PYTHON:management.services.agent.system_release"]
    if failure:
        expected = expected[:1 if failure == "sql" else 2 if failure == "initialize" else 3]
    assert executed.stdout.splitlines() == expected
    assert executed.returncode == (13 if failure == "sql" else 14 if failure else 0), executed.stderr
