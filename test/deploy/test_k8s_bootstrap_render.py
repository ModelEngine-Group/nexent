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

BUSINESS = {"nexent-config", "nexent-runtime", "nexent-mcp", "nexent-gateway", "nexent-web", "nexent-data-process"}
BOOTSTRAP_RUN_ID = "3134807a-85c2-46e4-b75e-063c0eeee25b"
AUTH_ARGS = ["--set", "nexent-common.secrets.jwtSecret=helm-test-fixture-not-a-deployment-secret"]
chart_dirs = _chart_dirs


@pytest.mark.parametrize("storage", ["local", "dynamic", "existing"])
def test_paused_release_creates_isolated_job_with_shared_environment_and_storage(chart_dirs, storage):
    args = _application_dynamic_args() if storage == "dynamic" else _application_existing_args() if storage == "existing" else []
    result = _template(chart_dirs["application"], "nexent", [*args, *AUTH_ARGS, "--set", "global.businessPaused=true",
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


@pytest.mark.parametrize("storage", ["dynamic", "existing"])
@pytest.mark.parametrize("replicas,paused", [(3, False), (2, False), (3, True)])
def test_runtime_fixed_replicas_render_with_the_same_shared_claims(chart_dirs, storage, replicas, paused):
    storage_args = _application_dynamic_args() if storage == "dynamic" else _application_existing_args()
    rendered = _template(chart_dirs["application"], "nexent", [*storage_args, *AUTH_ARGS,
        "--set", f"global.businessPaused={str(paused).lower()}",
        "--set", f"nexent-runtime.replicaCount={replicas}"])
    assert rendered.returncode == 0, rendered.stderr
    documents = _documents(rendered.stdout)
    deployments = {item["metadata"]["name"]: item["spec"] for item in documents if item["kind"] == "Deployment"}
    runtime = deployments["nexent-runtime"]
    assert runtime["replicas"] == (0 if paused else replicas)
    assert runtime["strategy"] == {"type": "Recreate"}
    assert deployments["nexent-config"]["replicas"] == (0 if paused else 1)
    assert not {item["kind"] for item in documents} & {"HorizontalPodAutoscaler", "ScaledObject"}
    runtime_volumes = runtime["template"]["spec"]["volumes"]
    config_volumes = deployments["nexent-config"]["template"]["spec"]["volumes"]
    claims = {volume["name"]: volume["persistentVolumeClaim"]["claimName"]
              for volume in runtime_volumes if "persistentVolumeClaim" in volume}
    assert set(claims) == {"nexent-workspace", "nexent-skills", "nexent-logs", "nexent-memory-plugins", "nexent-trajectory"}
    assert claims == {volume["name"]: volume["persistentVolumeClaim"]["claimName"]
                      for volume in config_volumes if volume["name"] in claims}


@pytest.mark.parametrize("replicas", ["0", "-1", "1.5", "true", "2147483648"])
def test_invalid_runtime_target_is_rejected_even_while_paused(chart_dirs, replicas):
    rendered = _template(chart_dirs["application"], "nexent", [*_application_dynamic_args(),
        "--set", "global.businessPaused=true", "--set", f"nexent-runtime.replicaCount={replicas}"])
    assert rendered.returncode != 0
    assert "replicaCount" in rendered.stderr


@pytest.mark.parametrize("overrides,error", [
    (["--set", "global.sharedStorage.mode=local"], "requires dynamic or existing shared RWX storage"),
    (["--set", "global.sharedStorage.storageClassName="], "requires an explicit RWX StorageClass"),
    (["--set", "global.sharedStorage.storageClassName=nexent-local"], "requires an explicit RWX StorageClass"),
    (["--set", "global.sharedStorage.accessModes={ReadWriteOnce}"], "requires ReadWriteMany"),
])
def test_runtime_chart_rejects_unqualified_multi_replica_configuration(chart_dirs, overrides, error):
    rendered = _template(chart_dirs["application"], "nexent", [*_application_dynamic_args(),
        "--set", "nexent-runtime.replicaCount=2", *overrides])
    assert rendered.returncode != 0
    assert error in rendered.stderr


def test_bootstrap_job_identity_is_scoped_to_paused_helm_release(chart_dirs):
    chart = chart_dirs["application"]
    args = [*_application_existing_args(), *AUTH_ARGS]
    paused = _template(chart, "example", [*args, "--set", "global.businessPaused=true",
        "--set-string", f"global.bootstrapRunId={BOOTSTRAP_RUN_ID}"])
    active = _template(chart, "example", args)
    assert paused.returncode == active.returncode == 0, paused.stderr + active.stderr
    paused_docs, active_docs = _documents(paused.stdout), _documents(active.stdout)
    bootstrap, = [doc for doc in paused_docs if doc["kind"] == "Job"]
    assert bootstrap["metadata"]["labels"]["nexent.io/bootstrap-run-id"] == BOOTSTRAP_RUN_ID
    assert not any(doc["kind"] == "Job" for doc in active_docs)
    for docs, count in ((paused_docs, 0), (active_docs, 1)):
        assert not any(doc["metadata"]["name"] == "nexent-runtime-maintenance" for doc in docs)
        for name in ("nexent-runtime", "nexent-config"):
            deployment, = [doc for doc in docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == name]
            annotations = deployment["metadata"].get("annotations", {})
            assert "nexent.io/maintenance-epoch" not in annotations
            assert "nexent.io/bootstrap-run-id" not in annotations
            assert deployment["spec"]["replicas"] == count
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            environment = {entry["name"]: entry.get("value") for entry in container["env"]}
            assert environment["NEXENT_RECOVERY_MODE"] == "fixed_replicas"
            assert "NEXENT_MAINTENANCE_EPOCH" not in environment
            if name == "nexent-runtime":
                assert environment["LOG_DIR"] == "/mnt/nexent-data/logs/$(POD_NAME)"


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
