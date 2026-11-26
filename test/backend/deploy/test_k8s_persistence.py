# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Render both Kubernetes releases with the deployment storage choices."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


CHART_ROOT = Path(__file__).resolve().parents[3] / "deploy/k8s/helm"
INFRASTRUCTURE = {f"nexent-{name}" for name in ("elasticsearch", "postgresql", "redis", "minio")}
APPLICATION = {f"nexent-{name}" for name in ("workspace", "skills", "memory-plugins", "logs", "trajectory", "project-config")}


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
