# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Render both Kubernetes releases with the deployment storage choices."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from .test_workbench_publication import run_shell, shell_function


CHART_ROOT = Path(__file__).resolve().parents[3] / "deploy/k8s/helm"
INFRASTRUCTURE = {f"nexent-{name}" for name in ("elasticsearch", "postgresql", "redis", "minio")}
APPLICATION = {
    f"nexent-{name}"
    for name in ("workspace", "skills", "memory-plugins", "logs", "trajectory", "project-config", "ssh-keys")
}


def render(chart, *settings):
    helm = shutil.which("helm")
    assert helm, "Helm is required for persistence template verification"
    command = [helm, "template", "storage-test", str(CHART_ROOT / chart)]
    if chart == "nexent":
        command.extend(["--set-string", "nexent-common.secrets.jwtSecret=storage-test-fixture"])
    for setting in settings:
        command.extend(["--set", setting])
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


@pytest.mark.parametrize("chart,names", [("nexent", APPLICATION), ("nexent-infrastructure", INFRASTRUCTURE)])
def test_default_storage_uses_dynamically_provisioned_claims(chart, names):
    documents = render(chart)
    assert not any(doc["kind"] == "PersistentVolume" for doc in documents)
    claims = {doc["metadata"]["name"]: doc for doc in documents if doc["kind"] == "PersistentVolumeClaim"}
    assert names <= claims.keys()
    for name in names:
        claim = claims[name]
        assert "storageClassName" not in claim["spec"]
        assert "volumeName" not in claim["spec"]
        assert "ReadWriteMany" in claim["spec"]["accessModes"]
        assert claim["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
        assert claim["metadata"]["labels"]["nexent.io/persistence-mode"] == "dynamic"


def test_explicit_local_storage_renders_matching_static_pvs_and_claims():
    documents = render("nexent", "global.sharedStorage.mode=local", "nexent-runtime.replicaCount=1",
                       "global.sandboxProvider=docker")
    documents += render("nexent-infrastructure", *(f"{name}.persistence.mode=local" for name in INFRASTRUCTURE))
    volumes = {doc["metadata"]["name"]: doc["spec"] for doc in documents if doc["kind"] == "PersistentVolume"}
    claims = {doc["metadata"]["name"]: doc for doc in documents if doc["kind"] == "PersistentVolumeClaim"}
    for name in APPLICATION | INFRASTRUCTURE:
        claim = claims[name]
        volume = volumes[claim["spec"]["volumeName"]]
        assert volume["hostPath"]["type"] == "DirectoryOrCreate"
        assert claim["spec"]["storageClassName"] == volume["storageClassName"] == "nexent-local"
        assert "helm.sh/resource-policy" not in claim["metadata"]["annotations"]
    assert volumes["nexent-ssh-keys-pv"]["hostPath"]["path"] == "/var/lib/nexent-data/nexent-ssh-keys"


@pytest.mark.parametrize("mode,claim_name", [
    ("dynamic", "nexent-ssh-keys"), ("local", "nexent-ssh-keys"), ("existing", "shared-ssh-keys"),
])
def test_backend_pods_mount_the_shared_ssh_claim_read_only(mode, claim_name):
    documents = render(
        "nexent", f"global.sharedStorage.mode={mode}", "global.businessPaused=true",
        "nexent-runtime.replicaCount=1",
        "global.sandboxSingleNodeDevelopment=true", "global.sharedStorage.sshKeys.existingClaim=shared-ssh-keys",
    )
    expected_containers = {
        "nexent-config": {"nexent-config"},
        "nexent-runtime": {"nexent-runtime", "wait-for-management", "sandbox-workspace-permissions"},
        "nexent-mcp": {"nexent-mcp", "wait-for-management"},
        "storage-test-system-bootstrap-1": {"nexent-config"},
    }
    pod_specs = {
        doc["metadata"]["name"]: doc["spec"]["template"]["spec"]
        for doc in documents
        if doc["kind"] in {"Deployment", "Job"} and doc["metadata"]["name"] in expected_containers
    }
    assert pod_specs.keys() == expected_containers.keys()
    for name, pod in pod_specs.items():
        volume, = (volume for volume in pod["volumes"] if volume["name"] == "nexent-ssh-keys")
        assert volume["persistentVolumeClaim"] == {"claimName": claim_name, "readOnly": True}
        containers = [*pod["containers"], *pod.get("initContainers", [])]
        assert {container["name"] for container in containers} == expected_containers[name]
        for container in containers:
            mount, = (mount for mount in container["volumeMounts"] if mount["mountPath"] == "/opt/ssh-keys")
            assert mount == {"name": "nexent-ssh-keys", "mountPath": "/opt/ssh-keys", "readOnly": True}

    ssh_claims = [doc for doc in documents if doc["kind"] == "PersistentVolumeClaim"
                  and doc["metadata"]["name"] in {"nexent-ssh-keys", "shared-ssh-keys"}]
    assert [claim["metadata"]["name"] for claim in ssh_claims] == ([] if mode == "existing" else [claim_name])


def test_application_disabled_does_not_provision_ssh_storage():
    documents = render(
        "nexent", "global.deploymentComponents.application=false",
        "nexent-config.enabled=false", "nexent-runtime.enabled=false", "nexent-mcp.enabled=false",
    )
    assert not any(doc["metadata"]["name"] in {"nexent-ssh-keys", "nexent-ssh-keys-pv"} for doc in documents)


def test_deployment_persistence_values_configure_the_ssh_claim():
    functions = "\n".join(shell_function("k8s", name) for name in (
        "yaml_quote", "persistence_existing_claim", "render_shared_storage_persistence_values",
    ))
    result = run_shell(functions + r'''
PERSISTENCE_MODE=existing
STORAGE_CLASS_NAME=shared
LOCAL_PATH="/custom data/"
EXISTING_CLAIM_PREFIX=external
render_shared_storage_persistence_values /dev/stdout
''')
    assert result.returncode == 0, result.stderr
    ssh_keys = yaml.safe_load(result.stdout)["global"]["sharedStorage"]["sshKeys"]
    assert ssh_keys["localPath"] == "/custom data/nexent-ssh-keys"
    assert ssh_keys["existingClaim"] == "external-nexent-ssh-keys"


@pytest.mark.parametrize("storage_class", [None, "custom-rwx"])
def test_monitoring_uses_dynamic_storage(storage_class):
    settings = ["nexent-monitoring.enabled=true", "global.monitoring.provider=phoenix"]
    if storage_class:
        settings.append(f"nexent-monitoring.persistence.storageClassName={storage_class}")
    documents = render("nexent", *settings)
    assert not any(doc["kind"] == "PersistentVolume" for doc in documents)
    claim = next(doc for doc in documents if doc["kind"] == "PersistentVolumeClaim"
                 and doc["metadata"]["name"] == "nexent-phoenix")
    assert claim["spec"].get("storageClassName") == storage_class
    assert "volumeName" not in claim["spec"]
    assert claim["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
