# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real Kubernetes env injection on an explicitly selected isolated test cluster."""

import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

import pytest
import yaml

from d5.assets import bash_path
from shared.asset_registry import AssetDependencyError
from shared.config import repo_root


CASE_ID = "K8S-ENV-D5-001"
BACKENDS = ("config", "runtime", "mcp", "northbound", "data-process")


def prerequisite(name, value):
    if not value:
        raise AssetDependencyError("k8s_env_injection", name, consumer_case_id=CASE_ID,
                                   detail="Explicit isolated-cluster prerequisite is missing; no cluster access attempted")
    return value


def runtime_configuration():
    for name in ("D5_ENABLE_MUTATING_DEPLOYMENT", "D5_ISOLATED_ENVIRONMENT"):
        prerequisite(name, os.environ.get(name, "").lower() in {"1", "true", "yes"})
    context = prerequisite("context", os.environ.get("NEXENT_D5_K8S_CONTEXT", "").strip())
    image = prerequisite("probe_image", os.environ.get("NEXENT_D5_K8S_PROBE_IMAGE", "").strip())
    commands = {name: prerequisite(name, shutil.which(name)) for name in ("bash", "helm", "kubectl")}
    return context, image, commands


def fixture_configuration(updated=False):
    expected = {
        "INJECTION_SHARED": "root", "INJECTION_VALUE": "new" if updated else "old",
        "INJECTION_UNKNOWN_FEATURE": "enabled", "INJECTION_EMPTY": "",
        "INJECTION_JSON": '{"enabled":false,"value":"a=b # c"}',
        "INJECTION_MULTILINE": "first\nASSIGNMENT_LOOKING=value\nlast\n",
        "HITL_ENABLED": "true", "RUNTIME_AGENT_THREAD_MAX_WORKERS": "17",
        "CAS_DEFAULT_TENANT_ID": "synthetic-tenant", "CAS_DEFAULT_ROLE": "ADMIN",
        "REDIS_URL": "redis://synthetic:6379/4", "DP_PART_PROCESSOR_COUNT": "7",
        "MINIO_ACCESS_KEY": "root-credential", "IS_DEPLOYED_BY_KUBERNETES": "false",
        "KUBERNETES_NAMESPACE": "wrong", "DEPLOYMENT_VERSION": "wrong",
        "NEXENT_SQL_STARTUP_MODE": "wrong", "NEXENT_SQL_FILES_CHECKSUM": "wrong",
        "NEXENT_MCP_DOCKER_IMAGE": "wrong", "NEXENT_SANDBOX_DOCKER_IMAGE": "wrong",
        "NEXENT_SANDBOX_DEFAULT_LEVEL": "wrong",
    }
    if updated:
        expected["INJECTION_ADDED"] = "added"
    else:
        expected["INJECTION_REMOVED"] = "removed"
    content = "\n".join(key + "='" + value + "'" for key, value in expected.items()) + "\n"
    monitoring = {"INJECTION_SHARED": "monitoring", "INJECTION_MONITOR_ONLY": "yes",
                  "MINIO_ACCESS_KEY": "monitor-credential"}
    monitoring_content = "\n".join(key + "='" + value + "'" for key, value in monitoring.items()) + "\n"
    return content, expected, monitoring_content, monitoring


def run_local(command, *, timeout=30):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    assert result.returncode == 0, "Synthetic configuration rendering failed; no live env file was used"
    return result.stdout


def render(repo, directory, commands, namespace, updated=False):
    root_content, root_expected, monitoring_content, monitoring_expected = fixture_configuration(updated)
    root = directory / ".env"
    root.write_text(root_content, encoding="utf-8")
    (directory / "monitoring.env").write_text(monitoring_content, encoding="utf-8")
    output = directory / "generated.yaml"
    runtime = directory / "runtime.yaml"
    script = r'''
set -e
source "$1" --help >/dev/null
source "$2"
ROOT_ENV_FILE="$2"
DEPLOYMENT_ROOT_ENV="$2"
GENERATED_SECRETS_VALUES="$3"
DEPLOYMENT_COMPONENTS="application,data-process"
DEPLOYMENT_SANDBOX_MODE=lightweight
MINIO_ACCESS_KEY=final-access
MINIO_SECRET_KEY=final-secret
NEXENT_POSTGRES_PASSWORD=final-postgres
NEXENT_MCP_DOCKER_IMAGE=synthetic/mcp:chosen
NEXENT_SANDBOX_IMAGE=synthetic/sandbox:chosen
sql_files_checksum() { printf 'synthetic-sql-checksum'; }
deployment_render_image_rollout_checksums() { printf '    backendImage: "synthetic-probe"\n'; }
render_k8s_runtime_config_values "$4"
render_runtime_secret_values
'''
    run_local([commands["bash"], "-c", script, "k8s-env-case",
               bash_path(repo / "deploy/k8s/deploy.sh"), bash_path(root), bash_path(output), bash_path(runtime)])
    assert output.stat().st_mode & 0o777 == 0o600, "Secret values permissions must be private"
    values = yaml.safe_load(output.read_text(encoding="utf-8"))
    for field, expected in (("rootData", root_expected), ("monitoringData", monitoring_expected)):
        data = values["nexent-common"]["envFiles"][field]
        decoded = {key: base64.b64decode(value).decode() for key, value in data.items()}
        assert decoded == expected, "File-declared synthetic values were omitted or altered"
    values["global"].update(namespace=namespace, deploymentVersion="speed", sandboxMode="lightweight")
    values["nexent-common"]["images"] = {
        "mcp": {"repository": "synthetic/mcp", "tag": "chosen"},
        "sandbox": {"repository": "synthetic/sandbox", "tag": "chosen"},
    }
    output.write_text(yaml.safe_dump(values), encoding="utf-8")
    chart = repo / "deploy/k8s/helm/nexent"
    documents = list(yaml.safe_load_all(run_local([
        commands["helm"], "template", "env-probe", str(chart), "-f", str(runtime), "-f", str(output),
    ])))
    infrastructure = list(yaml.safe_load_all(run_local([
        commands["helm"], "template", "env-probe", str(chart.parent / "nexent-infrastructure"),
    ])))
    assert_service_scope(documents, infrastructure)
    return documents, values["global"]["rolloutChecksums"]["env"], root_expected, monitoring_expected


def assert_service_scope(documents, infrastructure):
    found = set()
    for document in documents + infrastructure:
        if not document or document["kind"] != "Deployment":
            continue
        name = document["metadata"]["name"].removeprefix("nexent-")
        for container in document["spec"]["template"]["spec"]["containers"]:
            references = [item.get("secretRef", {}).get("name") for item in container.get("envFrom", [])]
            if name in BACKENDS:
                expected = [None, "nexent-env"]
                if name in ("config", "runtime"):
                    expected.append("nexent-monitoring-env")
                assert references == expected + ["nexent-secrets"], "Incorrect backend envFrom precedence"
                found.add(name)
            else:
                assert "nexent-env" not in references and "nexent-monitoring-env" not in references, "Unexpected complete env Secret reference"
    assert found == set(BACKENDS), "All five backend templates must be rendered"


def probe_resources(documents, image):
    resources = []
    for document in documents:
        if not document:
            continue
        name = document["metadata"]["name"]
        if document["kind"] in ("Secret", "ConfigMap") and name in (
            "nexent-config", "nexent-env", "nexent-monitoring-env", "nexent-secrets",
        ):
            resources.append(document)
        elif document["kind"] == "Deployment" and name.removeprefix("nexent-") in BACKENDS:
            template = document["spec"]["template"]
            original = template["spec"]["containers"][0]
            probe = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": document["metadata"], "spec": {
                "replicas": 1, "strategy": {"type": "Recreate"}, "selector": document["spec"]["selector"],
                "template": {"metadata": copy.deepcopy(template["metadata"]), "spec": {"containers": [{
                    "name": name, "image": image,
                    "command": ["python3", "-c", "import time; time.sleep(3600)"],
                    "envFrom": copy.deepcopy(original["envFrom"]), "env": copy.deepcopy(original["env"]),
                    "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"memory": "64Mi"}},
                    "securityContext": {"allowPrivilegeEscalation": False, "runAsUser": 1000,
                                        "capabilities": {"drop": ["ALL"]}},
                }]}},
            }}
            resources.append(probe)
    return resources


class IsolatedCluster:
    """Restrict every test operation to an explicit context and run-owned namespace."""

    def __init__(self, command, context, namespace):
        self.command = command
        self.context = context
        self.namespace = namespace
        self.created = False

    def call(self, arguments, *, payload=None, timeout=30):
        result = subprocess.run(
            [self.command, "--context", self.context, *arguments],
            input=payload, capture_output=True, text=True, timeout=timeout, check=False,
        )
        assert result.returncode == 0, "Isolated Kubernetes command failed: " + " ".join(arguments[:3])
        return result.stdout

    def create(self):
        # Create fails on collisions. Only a successful create grants cleanup ownership.
        self.call(["create", "namespace", self.namespace])
        self.created = True

    def apply(self, resources):
        assert self.created, "Cannot apply before creating the run-owned namespace"
        for resource in resources:
            assert resource["metadata"]["namespace"] == self.namespace
            assert resource["kind"] in {"Secret", "ConfigMap", "Deployment"}
        self.call(["-n", self.namespace, "apply", "-f", "-"], payload=yaml.safe_dump_all(resources))

    def wait(self):
        for name in BACKENDS:
            self.call(["-n", self.namespace, "rollout", "status", "deployment/nexent-" + name,
                       "--timeout=180s"], timeout=190)

    def snapshot(self, name, keys):
        # Inspect selected synthetic keys only; never dump an entire environment.
        script = "import json,os; print(json.dumps({k:os.environ.get(k) for k in " + repr(sorted(keys)) + "}))"
        output = self.call(["-n", self.namespace, "exec", "deployment/nexent-" + name,
                            "--", "python3", "-c", script])
        return json.loads(output)

    def cleanup(self):
        if self.created:
            self.call(["delete", "namespace", self.namespace, "--wait=true", "--timeout=120s"], timeout=130)
            remaining = self.call(["get", "namespace", self.namespace, "--ignore-not-found", "-o", "name"])
            assert not remaining.strip(), "Run-owned namespace was not cleaned"


def assert_snapshots(cluster, root_expected, monitoring_expected, namespace, updated):
    for name in BACKENDS:
        expected = dict(root_expected)
        if name in ("config", "runtime"):
            expected.update(monitoring_expected)
        expected.update({
            "MINIO_ACCESS_KEY": "final-access", "IS_DEPLOYED_BY_KUBERNETES": "true",
            "KUBERNETES_NAMESPACE": namespace, "DEPLOYMENT_VERSION": "speed",
            "NEXENT_SQL_STARTUP_MODE": {"config": "migrate", "data-process": "off"}.get(name, "wait"),
            "NEXENT_SQL_FILES_CHECKSUM": "synthetic-sql-checksum",
            "NEXENT_MCP_DOCKER_IMAGE": "synthetic/mcp:chosen",
            "NEXENT_SANDBOX_DOCKER_IMAGE": "synthetic/sandbox:chosen",
            "NEXENT_SANDBOX_DEFAULT_LEVEL": "docker", "HOST_ONLY_SENTINEL": None,
            "RUNTIME_STATE_REDIS_URL": "redis://synthetic:6379/4", "WORKER_CONCURRENCY": "8",
        })
        if name not in ("config", "runtime"):
            expected["INJECTION_MONITOR_ONLY"] = None
        if updated:
            expected["INJECTION_REMOVED"] = None
        snapshot = cluster.snapshot(name, expected)
        for key, value in expected.items():
            assert snapshot.get(key) == value, "Unexpected synthetic env value for " + name + "/" + key


@pytest.mark.stage("D5")
@pytest.mark.case_id(CASE_ID)
@pytest.mark.deploy
@pytest.mark.p1
def test_k8s_env_files_runtime(monkeypatch):
    context, image, commands = runtime_configuration()
    repo = repo_root()
    local_env = repo / "deploy/env/.env"
    before = (local_env.stat().st_mtime_ns, local_env.stat().st_size) if local_env.exists() else None
    namespace = "nexent-env-test-" + uuid4().hex[:16]
    cluster = IsolatedCluster(commands["kubectl"], context, namespace)
    monkeypatch.setenv("HOST_ONLY_SENTINEL", "must-not-leak")
    try:
        with tempfile.TemporaryDirectory(prefix="nexent-k8s-env-") as temporary:
            directory = Path(temporary)
            documents, first_checksum, root_expected, monitoring_expected = render(repo, directory, commands, namespace)
            cluster.create()
            cluster.apply(probe_resources(documents, image))
            cluster.wait()
            assert_snapshots(cluster, root_expected, monitoring_expected, namespace, False)
            documents, second_checksum, root_expected, monitoring_expected = render(repo, directory, commands, namespace, True)
            assert first_checksum != second_checksum, "Effective env updates must change the rollout checksum"
            cluster.apply(probe_resources(documents, image))
            cluster.wait()
            assert_snapshots(cluster, root_expected, monitoring_expected, namespace, True)
    finally:
        cluster.cleanup()
        after = (local_env.stat().st_mtime_ns, local_env.stat().st_size) if local_env.exists() else None
        assert before == after, "The real deployment env file was modified"
