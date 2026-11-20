# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify the safety gates of the Runtime scaling preparation, not product behavior."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))

from shared import runtime_scaling_k8s as runtime


CANDIDATE_DIGEST = "sha256:" + "a" * 64
STALE_DIGEST = "sha256:" + "b" * 64
EPOCH = "4bcc5308-3b8c-4cd2-9efa-0316f414ed09"


@pytest.fixture
def profile(tmp_path):
    config = tmp_path / "runtime-scaling.kubeconfig"
    config.write_text("private test fixture", encoding="utf-8")
    example = ROOT / "test-e2e/infra/config/runtime-scaling-k8s.example.yaml"
    settings = yaml.safe_load(example.read_text(encoding="utf-8"))
    settings.update(enabled=True, cluster_uid="3134807a-85c2-46e4-b75e-063c0eeee25b",
                    backend_image_digests=[CANDIDATE_DIGEST])
    path = tmp_path / "runtime-scaling-k8s.yaml"
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    return path


class ClusterBoundary:
    def __init__(self, profile):
        self.context = profile.context
        self.cluster_uid = profile.cluster_uid
        self.opt_in = "true"
        self.namespace = None
        self.pvs = []
        self.nodes = [self.ready_node(), self.ready_node()]
        self.storage = {"provisioner": "storage.example.test", "reclaimPolicy": "Delete"}
        self.mutations = []
        self.drop_create_response = False

    @staticmethod
    def ready_node():
        return {"metadata": {"labels": {"kubernetes.io/os": "linux"}},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]}}

    def __call__(self, *args, stdin=None, **options):
        if args[0] == "config":
            assert options["source_config"] is True
            return json.dumps({"current-context": self.context, "contexts": [{"name": self.context}]})
        if args[0] == "get":
            resource = args[1]
            if resource == "namespace":
                if args[2] == "kube-system":
                    return json.dumps({"metadata": {"uid": self.cluster_uid, "labels": {runtime.CLUSTER_OPT_IN: self.opt_in}}})
                return json.dumps(self.namespace) if self.namespace else ""
            if resource == "nodes":
                return json.dumps({"items": self.nodes})
            if resource == "storageclass":
                return json.dumps(self.storage)
            if resource == "pv":
                return json.dumps({"items": self.pvs})
        if args[0] == "create":
            assert self.namespace is None
            self.namespace = json.loads(stdin)
            self.namespace["metadata"]["uid"] = "owned-namespace-uid"
            self.mutations.append(("create", self.namespace["metadata"]["labels"]))
            if self.drop_create_response:
                raise runtime.IsolationError("connection lost after successful create")
            return json.dumps(self.namespace)
        if args[0] == "delete":
            assert args == ("delete", "--raw", "/api/v1/namespaces/nexent", "-f", "-")
            options = json.loads(stdin)
            assert options["preconditions"]["uid"] == self.namespace["metadata"]["uid"]
            self.mutations.append(("delete", options["preconditions"]))
            self.namespace = None
            return ""
        raise AssertionError("unexpected test subprocess")


@pytest.fixture
def boundary(profile, tmp_path, monkeypatch):
    parsed = runtime.Profile.load(profile)
    cluster = runtime.RuntimeScalingCluster(parsed, tmp_path)
    server = ClusterBoundary(parsed)
    monkeypatch.setattr(cluster, "_kubectl", server)
    return cluster, server, tmp_path / "kubeconfig.json"


def test_example_is_valid_and_default_disabled(tmp_path):
    example = ROOT / "test-e2e/infra/config/runtime-scaling-k8s.example.yaml"
    path = tmp_path / "runtime-scaling-k8s.yaml"
    path.write_bytes(example.read_bytes())
    with pytest.raises(runtime.IsolationError, match="has not been enabled"):
        runtime.Profile.load(path)


@pytest.mark.parametrize("value,error", [
    (None, "Invalid"), ([], "Invalid"), (["candidate-tag"], "Invalid"),
    ([CANDIDATE_DIGEST, CANDIDATE_DIGEST], "Invalid"),
    ([runtime.UNCONFIGURED_DIGEST], "Configure the candidate backend image digests"),
])
def test_enabled_profile_requires_explicit_candidate_digests(profile, value, error):
    settings = yaml.safe_load(profile.read_text(encoding="utf-8"))
    if value is None:
        del settings["backend_image_digests"]
    else:
        settings["backend_image_digests"] = value
    profile.write_text(yaml.safe_dump(settings), encoding="utf-8")
    with pytest.raises(runtime.IsolationError, match=error):
        runtime.Profile.load(profile)


@pytest.mark.parametrize("problem,message", [
    ("context", "pin the configured Kubernetes context"),
    ("uid", "Cluster UID or owner opt-in"),
    ("not-opted-in", "Cluster UID or owner opt-in"),
    ("occupied", "already exists"),
    ("single-node", "two schedulable Ready Linux nodes"),
    ("disk-retain", "Delete reclaim policy"),
    ("disk-not-dynamic", "dynamically provisioned"),
    ("reserved-class-in-use", "already contains volumes"),
])
def test_rejects_unsafe_scope_before_any_cluster_mutation(boundary, problem, message):
    cluster, server, frozen_config = boundary
    if problem == "context":
        server.context = "unexpected-global-context"
    elif problem == "uid":
        server.cluster_uid = "wrong-cluster"
    elif problem == "not-opted-in":
        server.opt_in = "false"
    elif problem == "occupied":
        server.namespace = {"metadata": {"uid": "existing-deployment"}}
    elif problem == "single-node":
        server.nodes[1]["spec"] = {"unschedulable": True}
    elif problem == "disk-retain":
        server.storage["reclaimPolicy"] = "Retain"
    elif problem == "disk-not-dynamic":
        server.storage["provisioner"] = "kubernetes.io/no-provisioner"
    elif problem == "reserved-class-in-use":
        server.pvs = [{"spec": {"storageClassName": cluster.profile.storage_class}}]

    with pytest.raises(runtime.IsolationError, match=message), cluster.owned_namespace():
        pytest.fail("Unsafe test environment was accepted")
    assert server.mutations == []
    assert not frozen_config.exists()


@pytest.mark.parametrize("failure", ["none", "after-creation", "lost-create-response"])
def test_cleanup_uses_created_uid_even_after_test_or_create_failure(boundary, failure):
    cluster, server, frozen_config = boundary
    server.drop_create_response = failure == "lost-create-response"

    def perform_run():
        with cluster.owned_namespace():
            assert frozen_config.stat().st_mode & 0o777 == 0o600
            if failure == "after-creation":
                raise ValueError("body failed")

    if failure == "after-creation":
        with pytest.raises(ValueError, match="body failed"):
            perform_run()
    elif failure == "lost-create-response":
        with pytest.raises(runtime.IsolationError, match="connection lost"):
            perform_run()
    else:
        perform_run()
    assert server.mutations == [
        ("create", {runtime.RUN_LABEL: cluster.run_id}), ("delete", {"uid": "owned-namespace-uid"}),
    ]
    assert server.namespace is None
    assert not frozen_config.exists()


def test_cleanup_does_not_delete_replacement_namespace(boundary):
    cluster, server, frozen_config = boundary
    with pytest.raises(runtime.IsolationError, match="UID or run ownership changed"), cluster.owned_namespace():
        server.namespace["metadata"]["uid"] = "foreign-namespace"
    assert server.mutations == [("create", {runtime.RUN_LABEL: cluster.run_id})]
    assert not frozen_config.exists()


def test_staging_never_copies_current_deployment_state(tmp_path):
    scratch = tmp_path / "scratch-copy"
    script = runtime.stage_deployment(ROOT, scratch)
    assert script.read_bytes() == (ROOT / "deploy/k8s/deploy.sh").read_bytes()
    assert (scratch / "deploy/env/.env.example").is_file()
    assert (scratch / "deploy/docker/assets/official-skills-zip").is_dir()
    assert not list(scratch.rglob("generated-*.yaml"))
    assert not list(scratch.rglob("deploy.options"))
    assert not list(scratch.rglob(".env"))


@pytest.mark.parametrize("queue_size", [0, 1])
def test_staging_restricts_only_disposable_agent_lane(tmp_path, queue_size):
    scratch = tmp_path / "single-agent-lane"
    runtime.stage_deployment(ROOT, scratch, agent_limit=1, agent_lane_queue_size=queue_size)
    relative = Path("deploy/env/.env.example")
    original = (ROOT / relative).read_text(encoding="utf-8")
    staged = (scratch / relative).read_text(encoding="utf-8")
    overrides = {"RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS": "1", "RUNTIME_AGENT_THREAD_MAX_WORKERS": "1",
                 "RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE": str(queue_size)}
    if queue_size:
        overrides["RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS"] = "90"
    assert staged.splitlines() == [f"{key}={overrides[key]}" if key in overrides else line
                                  for line in original.splitlines() for key in (line.partition("=")[0],)]


def test_staging_only_changes_the_owned_run_ttl(tmp_path):
    scratch = tmp_path / "owner-loss"
    runtime.stage_deployment(ROOT, scratch, run_ttl_seconds=30)
    relative = Path("deploy/env/.env.example")
    original = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    staged = (scratch / relative).read_text(encoding="utf-8").splitlines()
    key = "RUNTIME_RUN_TTL_SECONDS="
    assert [line for line in staged if line.startswith(key)] == [key + "30"]
    assert [line for line in staged if not line.startswith(key)] == [line for line in original if not line.startswith(key)]


def test_initial_deployment_can_use_the_product_default(boundary, monkeypatch):
    cluster, _, _ = boundary
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    calls = []
    verified = []
    monkeypatch.setattr(cluster, "_verify_deployed_backend", verified.append)

    def execute(command, *_args, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime, "_execute", execute)
    script = Path("deploy.sh")
    cluster.deploy(script, initial=True)
    assert "--runtime-replicas" not in calls[0]
    cluster.deploy(script, 2)
    target_option = calls[1].index("--runtime-replicas")
    assert calls[1][target_option + 1] == "2"
    with pytest.raises(ValueError, match="Invalid test deployment target"):
        cluster.deploy(script)
    assert len(calls) == 2
    assert verified == [1, 2]


def test_deployment_command_gates_do_not_change_the_clusters_own_tools(boundary, monkeypatch, tmp_path):
    cluster, _, _ = boundary
    original = dict(cluster._command_env)
    observed = {}

    def which(tool, *, path):
        assert path == original["PATH"]
        return f"/fixture/bin/{tool}"

    def execute(command, environment, **_kwargs):
        observed.update(environment)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    monkeypatch.setattr(runtime.shutil, "which", which)
    monkeypatch.setattr(runtime, "_execute", execute)
    cluster.deploy(Path("deploy.sh"), 2, helm_gate=tmp_path, kubectl_gate=tmp_path)
    assert observed["PATH"].split(os.pathsep) == [str(tmp_path), *original["PATH"].split(os.pathsep)]
    assert observed["D5_REAL_HELM"] == "/fixture/bin/helm" and observed["D5_REAL_KUBECTL"] == "/fixture/bin/kubectl"
    assert observed["D5_HELM_GATE"] == observed["D5_KUBECTL_GATE"] == str(tmp_path)
    assert observed["D5_KUBECTL_LOCK_NAME"] == f"nexent-d5-deployment-{cluster.run_id}"
    assert observed["KUBECONFIG"] == original["KUBECONFIG"] and cluster._command_env == original


def backend_pod(name, container, image_id, *, phase="Running"):
    return {
        "metadata": {"name": name, "uid": f"{name}-uid"},
        "spec": {"containers": [{"name": container, "image": f"example/backend@{CANDIDATE_DIGEST}"}]},
        "status": {"conditions": [{"type": "Ready", "status": "True"}], "phase": phase,
                   "containerStatuses": [{"name": container, "imageID": image_id}]},
    }


@pytest.mark.parametrize("fault", [None, "stale-runtime", "missing-runtime", "stale-maintenance", "foreign-job-pod"])
def test_rollout_checks_actual_candidate_runtime_and_maintenance_images(boundary, monkeypatch, fault):
    cluster, _, _ = boundary
    name = f"nexent-runtime-maintenance-{EPOCH}"
    runtime_ids = [f"containerd://{CANDIDATE_DIGEST}", f"docker-pullable://example/backend@{CANDIDATE_DIGEST}"]
    if fault == "stale-runtime":
        runtime_ids[1] = STALE_DIGEST
    elif fault == "missing-runtime":
        runtime_ids[1] = None
    runtime_pods = [backend_pod(f"runtime-{index}", runtime.RUNTIME, image_id)
                    for index, image_id in enumerate(runtime_ids)]
    job_image = STALE_DIGEST if fault == "stale-maintenance" else CANDIDATE_DIGEST
    job_pod = backend_pod("maintenance-pod", "maintenance", job_image, phase="Succeeded")
    job_pod["metadata"]["ownerReferences"] = [{"kind": "Job", "name": name,
                                               "uid": "foreign-uid" if fault == "foreign-job-pod" else "job-uid"}]
    resources = {
        ("deployment", runtime.RUNTIME): {"metadata": {"annotations": {"nexent.io/maintenance-epoch": EPOCH}},
                                          "spec": {"replicas": 2}},
        ("pods", "-l", f"app={runtime.RUNTIME}"): {"items": runtime_pods},
        ("job", name): {"metadata": {"uid": "job-uid", "labels": {"nexent.io/maintenance-epoch": EPOCH}}},
        ("pods", "-l", f"job-name={name}"): {"items": [job_pod]},
    }
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    monkeypatch.setattr(cluster, "resources", lambda *args: resources[args])
    monkeypatch.setattr(runtime, "_execute", lambda command, *args, **kwargs: subprocess.CompletedProcess(command, 0))
    receipts = {}
    monkeypatch.setattr(runtime, "write_case_evidence", receipts.__setitem__)
    if fault:
        message = "No owned maintenance Pod" if fault == "foreign-job-pod" else "candidate backend image digest"
        with pytest.raises(runtime.IsolationError, match=message):
            cluster.deploy(Path("deploy.sh"), 2, initial=True)
        assert not receipts
        return

    assert cluster.deploy(Path("deploy.sh"), 2, initial=True).returncode == 0
    receipt = receipts[f"runtime-images-{cluster.run_id}-{EPOCH}"]
    assert receipt["epoch"] == EPOCH
    assert [pod["digest"] for pod in receipt["runtime"]] == [CANDIDATE_DIGEST, CANDIDATE_DIGEST]
    assert receipt["maintenance"] == [{"pod": "maintenance-pod", "uid": "maintenance-pod-uid",
                                        "digest": CANDIDATE_DIGEST}]

    job_pod["status"]["phase"] = "Failed"
    assert cluster.maintenance_image_receipts(EPOCH, phase="Failed") == receipt["maintenance"]
    with pytest.raises(runtime.IsolationError, match="No owned maintenance Pod reached Succeeded"):
        cluster.maintenance_image_receipts(EPOCH)


def test_failed_deploy_preserves_original_failure_before_image_checks(boundary, monkeypatch):
    cluster, _, _ = boundary
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    failure = subprocess.CompletedProcess(["deploy.sh"], 1, stderr="fixture failure")
    monkeypatch.setattr(runtime, "_execute", lambda *_args, **_kwargs: failure)
    assert cluster.deploy(Path("deploy.sh"), 2) is failure


def test_fixture_creation_pins_namespace_and_rejects_cluster_resources(boundary, monkeypatch):
    cluster, _, _ = boundary
    calls = []
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)

    def create(*args, stdin):
        calls.append(args)
        return stdin

    monkeypatch.setattr(cluster, "_kubectl", create)
    with pytest.raises(ValueError, match="Unsupported isolated Runtime fixture kind"):
        cluster.create_namespaced_fixture({"kind": "ClusterRole"})
    assert not calls
    fixture = {"kind": "ServiceAccount", "metadata": {"name": "probe", "namespace": "foreign"}}
    result = cluster.create_namespaced_fixture(fixture)
    assert calls == [("create", "-n", runtime.NAMESPACE, "-f", "-", "-o", "json")]
    assert result["metadata"]["namespace"] == runtime.NAMESPACE
    assert fixture["metadata"]["namespace"] == "foreign"


def test_runtime_restart_rejects_foreign_pods_and_sends_the_pod_uid(boundary, monkeypatch):
    cluster, _, _ = boundary
    calls = []
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    monkeypatch.setattr(cluster, "_kubectl", lambda *args, stdin: calls.append((args, json.loads(stdin))))
    metadata = {"name": "nexent-runtime-test", "uid": "original-pod-uid", "namespace": runtime.NAMESPACE,
                "labels": {"app": "nexent-runtime"}}
    for changes in ({"namespace": "foreign"}, {"labels": {"app": "nexent-config"}}):
        with pytest.raises(ValueError, match="Expected a Runtime Pod"):
            cluster.restart_owned_runtime_pod({"metadata": {**metadata, **changes}})
    assert not calls
    cluster.restart_owned_runtime_pod({"metadata": metadata})
    request, options = calls[0]
    assert len(calls) == 1
    assert request == ("delete", "--raw", f"/api/v1/namespaces/{runtime.NAMESPACE}/pods/{metadata['name']}", "-f", "-")
    assert options["preconditions"] == {"uid": metadata["uid"]}
    assert "gracePeriodSeconds" not in options


def test_interrupt_requires_the_live_runtime_uid_and_a_nonzero_grace_period(gateway_boundary, monkeypatch):
    cluster, resources, _, _ = gateway_boundary
    pod = resources[("pod", "runtime-a")]
    stale = deepcopy(pod)
    stale["metadata"]["uid"] = "stale-pod"
    calls = []
    monkeypatch.setattr(cluster, "_kubectl", lambda *args, stdin: calls.append((args, json.loads(stdin))))
    with pytest.raises(runtime.IsolationError, match="Ready owned Runtime Pod"):
        cluster.restart_owned_runtime_pod(stale, interrupt=True)
    assert not calls
    cluster.restart_owned_runtime_pod(pod, interrupt=True)
    (request, options), = calls
    assert request[:2] == ("delete", "--raw")
    assert options["preconditions"] == {"uid": pod["metadata"]["uid"]}
    assert options["gracePeriodSeconds"] == 1


def worker(name, hostname=None, *, control_plane=False):
    node = ClusterBoundary.ready_node()
    node["metadata"]["name"] = name
    labels = node["metadata"]["labels"]
    labels["kubernetes.io/hostname"] = hostname or name
    if control_plane:
        labels["node-role.kubernetes.io/control-plane"] = ""
    return node


@pytest.mark.parametrize("nodes", [
    [worker("worker-a"), worker("worker-b", control_plane=True)],
    [worker("worker-a", "same-host"), worker("worker-b", "same-host")],
])
def test_cross_node_preparation_rejects_a_missing_second_worker_host_before_creation(boundary, nodes):
    cluster, server, _ = boundary
    server.nodes = nodes
    with pytest.raises(runtime.IsolationError, match="at least two schedulable worker hosts"):
        with cluster.owned_namespace(separate_workers=True):
            pytest.fail("Cross-node case adopted an unsuitable cluster")
    assert not server.mutations


@pytest.mark.parametrize("condition", ["active", "paused", "foreign-release", "existing-affinity", "one-replica"])
def test_cross_node_placement_updates_only_the_owned_runtime_pod_template(boundary, monkeypatch, condition):
    cluster, _, _ = boundary
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    metadata = {"namespace": runtime.NAMESPACE, "uid": "runtime-deployment-uid", "resourceVersion": "17",
                "annotations": {"meta.helm.sh/release-name": runtime.NAMESPACE}}
    spec = {"replicas": 2, "selector": {"matchLabels": {"app": runtime.RUNTIME}}, "template": {"spec": {}}}
    if condition == "paused":
        metadata["annotations"]["nexent.io/maintenance-target-replicas"] = "2"
    elif condition == "foreign-release":
        metadata["annotations"]["meta.helm.sh/release-name"] = "foreign"
    elif condition == "existing-affinity":
        spec["template"]["spec"]["affinity"] = {}
    elif condition == "one-replica":
        spec["replicas"] = 1

    def resources(*args):
        assert args == ("deployment", runtime.RUNTIME)
        return {"metadata": metadata, "spec": spec}

    calls = []
    monkeypatch.setattr(cluster, "resources", resources)
    monkeypatch.setattr(cluster, "_read", lambda name: {"items": [
        worker("worker-a"), worker("worker-b"), worker("control-plane", control_plane=True),
    ]})
    monkeypatch.setattr(cluster, "_kubectl", lambda *args, **kwargs: calls.append(args))
    if condition != "active":
        with pytest.raises(runtime.IsolationError, match="Placement"):
            cluster.spread_runtime_pair()
        assert not calls
        return

    assert cluster.spread_runtime_pair() == {"worker-a", "worker-b"}
    assert calls[0][:-1] == ("patch", "deployment", runtime.RUNTIME, "-n", runtime.NAMESPACE, "--type=json", "--patch")
    assert calls[1][:5] == ("rollout", "status", f"deployment/{runtime.RUNTIME}", "-n", runtime.NAMESPACE)
    patch = json.loads(calls[0][-1])
    assert patch[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
    ]
    assert len(patch) == 3 and patch[2]["path"] == "/spec/template/spec/affinity" and patch[2]["op"] == "add"
    affinity = patch[2]["value"]
    spec["template"]["spec"]["affinity"] = affinity
    calls.clear()
    assert cluster.spread_runtime_pair() == {"worker-a", "worker-b"}
    assert len(calls) == 1 and calls[0][:2] == ("rollout", "status")
    required = "requiredDuringSchedulingIgnoredDuringExecution"
    assert affinity["nodeAffinity"][required]["nodeSelectorTerms"] == [
        {"matchFields": [{"key": "metadata.name", "operator": "In", "values": [name]}]}
        for name in ("worker-a", "worker-b")
    ]
    assert affinity["podAntiAffinity"][required] == [
        {"labelSelector": {"matchLabels": {"app": runtime.RUNTIME}}, "topologyKey": "kubernetes.io/hostname"},
    ]


@pytest.mark.parametrize("problem", [None, "explicit-filesystem", "hostPath", "local", "foreign-claim",
                                     "read-write-once", "foreign-class", "block-pvc", "block-pv"])
def test_bound_shared_runtime_volume_requires_the_owned_rwx_binding(boundary, monkeypatch, problem):
    cluster, _, _ = boundary
    claim_name = "nexent-workspace"
    claim = {"metadata": {"namespace": runtime.NAMESPACE, "uid": "owned-claim-uid"}, "status": {"phase": "Bound"},
             "spec": {"volumeName": "test-volume", "storageClassName": cluster.profile.storage_class,
                      "accessModes": ["ReadWriteMany"]}}
    volume = {"status": {"phase": "Bound"}, "spec": {
        "storageClassName": cluster.profile.storage_class, "accessModes": ["ReadWriteMany"],
        "claimRef": {**claim["metadata"], "name": claim_name}, "csi": {"driver": "fixture.example.test"},
    }}
    if problem in {"local", "hostPath"}:
        volume["spec"][problem] = {"path": "/local-storage"}
    elif problem == "foreign-claim":
        volume["spec"]["claimRef"]["uid"] = "other-claim-uid"
    elif problem == "read-write-once":
        volume["spec"]["accessModes"] = ["ReadWriteOnce"]
    elif problem == "foreign-class":
        claim["spec"]["storageClassName"] = "other-class"
    elif problem == "block-pvc":
        claim["spec"]["volumeMode"] = "Block"
    elif problem == "block-pv":
        volume["spec"]["volumeMode"] = "Block"
    elif problem == "explicit-filesystem":
        claim["spec"]["volumeMode"] = volume["spec"]["volumeMode"] = "Filesystem"
    monkeypatch.setattr(cluster, "resources", lambda *args: claim)
    monkeypatch.setattr(cluster, "_read", lambda *args: volume)
    if problem not in {None, "explicit-filesystem"}:
        with pytest.raises(runtime.IsolationError, match="Runtime (volume|claim)"):
            cluster.bound_shared_volume(claim_name)
    else:
        assert cluster.bound_shared_volume(claim_name) == {
            "claim": claim_name, "volume": "test-volume", "storage_class": cluster.profile.storage_class,
            "driver": "fixture.example.test", "volume_mode": "Filesystem",
        }


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_activation_gate_intercepts_only_activation_and_preserves_arguments(tmp_path, decision):
    wrapper = ROOT / "test-e2e/cases/RUNTIME-OFFLINE-DEPLOY-D5-001/hold-activation.sh"
    underlying_helm = tmp_path / "underlying-helm"
    underlying_helm.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    underlying_helm.chmod(0o700)
    environment = {**os.environ, "D5_REAL_HELM": str(underlying_helm), "D5_HELM_GATE": str(tmp_path)}
    epoch = "3134807a-85c2-46e4-b75e-063c0eeee25b"
    template_args = ["template", "nexent", "global.businessPaused=false"]
    template = subprocess.run(["bash", str(wrapper), *template_args],
                              env=environment, capture_output=True, text=True, timeout=5)
    assert template.returncode == 0 and template.stdout.splitlines() == template_args
    assert not (tmp_path / "arrived").exists()

    command = ["bash", str(wrapper), "upgrade", "--install", "nexent", "--set", "global.businessPaused=false",
               "--set-string", f"global.maintenanceEpoch={epoch}"]
    with subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as helm:
        try:
            deadline = monotonic() + 5
            while not (tmp_path / "arrived").exists() and helm.poll() is None and monotonic() < deadline:
                sleep(0.01)
            assert (tmp_path / "arrived").read_text(encoding="utf-8").strip() == epoch
            assert helm.poll() is None
            (tmp_path / "decision").write_text(decision, encoding="utf-8")
            stdout, stderr = helm.communicate(timeout=5)
            assert not stderr
            assert (helm.returncode, stdout.splitlines()) == ((0, command[2:]) if decision == "allow" else (1, []))
        finally:
            if helm.poll() is None:
                helm.kill()
                helm.communicate()


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_maintenance_gate_tags_only_the_deployment_lock_and_holds_only_success(tmp_path, decision):
    wrapper = ROOT / "test-e2e/cases/RUNTIME-OFFLINE-DEPLOY-D5-001/hold-maintenance-result.sh"
    underlying = tmp_path / "underlying-kubectl"
    underlying.write_text('#!/bin/bash\nif [[ "$1" == get ]]; then printf "%s" "$JOB_STATUS"; '
                          'else printf "%s\\n" "$@"; fi\n', encoding="utf-8")
    underlying.chmod(0o700)
    environment = {**os.environ, "D5_REAL_KUBECTL": str(underlying), "D5_KUBECTL_GATE": str(tmp_path),
                   "D5_KUBECTL_LOCK_NAME": "fixture-lock"}

    def invoke(arguments, **env):
        return subprocess.run(["bash", str(wrapper), *arguments], env={**environment, **env},
                              capture_output=True, text=True, timeout=5, check=True).stdout

    lock = ["exec", "-i", "-n", "nexent", "deployment/nexent-postgresql", "-c", "postgresql", "--", "sh", "-c",
            "fixture command", "runtime-deploy-lock", "psql", "-w"]
    assert invoke(lock).splitlines() == [*lock[:8], "env", "PGAPPNAME=fixture-lock", *lock[8:]]
    other = [*lock[:11], "runtime-scaling-d5", *lock[12:]]
    assert invoke(other).splitlines() == other

    job = ["get", "job", f"nexent-runtime-maintenance-{EPOCH}", "-n", "nexent", "-o",
           "jsonpath={.status.succeeded}:{.status.failed}"]
    arrived = tmp_path / "maintenance-arrived"
    assert invoke(job, JOB_STATUS=":1") == ":1"
    assert invoke([*job[:2], "unrelated-job", *job[3:]], JOB_STATUS="1:") == "1:"
    assert not arrived.exists()
    with subprocess.Popen(["bash", str(wrapper), *job], env={**environment, "JOB_STATUS": "1:0"},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as command:
        try:
            deadline = monotonic() + 5
            while not arrived.exists() and command.poll() is None and monotonic() < deadline:
                sleep(0.01)
            assert arrived.read_text(encoding="utf-8").strip() == EPOCH and command.poll() is None
            (tmp_path / "maintenance-decision").write_text(decision, encoding="utf-8")
            output, error = command.communicate(timeout=5)
            assert not error
            assert (command.returncode, output) == ((0, "1:0") if decision == "allow" else (1, ""))
        finally:
            if command.poll() is None:
                command.kill()
                command.communicate()


@pytest.fixture
def gateway_boundary(boundary, monkeypatch):
    cluster, _, _ = boundary
    pod = {"metadata": {"namespace": runtime.NAMESPACE, "name": "runtime-a", "uid": "owned-runtime-uid",
                        "labels": {"app": runtime.RUNTIME}},
           "status": {"podIP": "10.244.1.3", "conditions": [{"type": "Ready", "status": "True"}]}}
    deployment = {"metadata": {"namespace": runtime.NAMESPACE,
                               "annotations": {"meta.helm.sh/release-name": runtime.NAMESPACE}},
                  "spec": {"template": {"spec": {"containers": [{"name": runtime.GATEWAY, "env": [
                      {"name": "GATEWAY_RUNTIME_URL", "value": f"http://{runtime.RUNTIME}:5014"},
                      {"name": "GATEWAY_AUTH_ENABLED", "value": "true"},
                      {"name": "JWT_SECRET", "valueFrom": {"secretKeyRef": {"name": "nexent-secrets", "key": "JWT_SECRET"}}},
                  ]}]}}}}
    service = {"metadata": {"namespace": runtime.NAMESPACE}, "spec": {"selector": {"app": runtime.GATEWAY}}}
    routed_pod = {"metadata": {"namespace": runtime.NAMESPACE,
                               "labels": {"app": runtime.ROUTING_GATEWAY, runtime.RUN_LABEL: cluster.run_id}}}
    resources = {("pod", "runtime-a"): pod, ("deployment", runtime.GATEWAY): deployment,
                 ("service", runtime.GATEWAY): service, ("pod", "routing-gateway"): routed_pod,
                 ("service", runtime.WEB): {"metadata": {"namespace": runtime.NAMESPACE},
                                            "spec": {"selector": {"app": runtime.WEB}}}}
    created, waited = [], []
    monkeypatch.setattr(cluster, "require_owned_namespace", lambda: None)
    monkeypatch.setattr(cluster, "resources", lambda *args: resources[args])
    monkeypatch.setattr(cluster, "create_namespaced_fixture", created.append)
    monkeypatch.setattr(cluster, "wait_for_condition", lambda *args: waited.append(args))
    return cluster, resources, created, waited


@pytest.mark.parametrize("pod_ip,origin", [("10.244.1.3", "http://10.244.1.3:5014"),
                                          ("fd00::1", "http://[fd00::1]:5014")])
def test_directed_gateway_uses_live_runtime_ip_and_preserves_authentication(gateway_boundary, pod_ip, origin):
    cluster, resources, created, waited = gateway_boundary
    pod = resources[("pod", "runtime-a")]
    pod["status"]["podIP"] = pod_ip
    template = resources[("deployment", runtime.GATEWAY)]["spec"]["template"]["spec"]
    original = deepcopy(template)

    name = cluster.create_runtime_gateway(deepcopy(pod))

    manifest, = created
    assert manifest["metadata"] == {"name": name, "labels": {"app": runtime.ROUTING_GATEWAY,
                                                          runtime.RUN_LABEL: cluster.run_id}}
    assert waited == [(f"pod/{name}", "Ready")]
    spec = manifest["spec"]
    assert spec["restartPolicy"] == "Never" and spec["automountServiceAccountToken"] is False
    assert spec["containers"][0]["env"] == [{"name": "GATEWAY_RUNTIME_URL", "value": origin},
                                            *original["containers"][0]["env"][1:]]
    assert template == original


@pytest.mark.parametrize("problem,message", [
    ("new-uid", "Ready owned Runtime Pod"), ("foreign-namespace", "Ready owned Runtime Pod"),
    ("not-ready", "Ready owned Runtime Pod"), ("terminating", "Ready owned Runtime Pod"),
    ("missing-ip", "routable Pod IP"), ("loopback-ip", "routable Pod IP"),
    ("auth-disabled", "production authentication"), ("other-release", "owned Helm release"),
])
def test_directed_gateway_rejects_unowned_or_unsafe_target(gateway_boundary, problem, message):
    cluster, resources, created, waited = gateway_boundary
    pod = resources[("pod", "runtime-a")]
    deployment = resources[("deployment", runtime.GATEWAY)]
    expected = deepcopy(pod)
    if problem == "new-uid":
        pod["metadata"]["uid"] = "different-pod"
    elif problem == "foreign-namespace":
        pod["metadata"]["namespace"] = "another-namespace"
    elif problem == "not-ready":
        pod["status"]["conditions"][0]["status"] = "False"
    elif problem == "terminating":
        pod["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    elif problem == "missing-ip":
        del pod["status"]["podIP"]
    elif problem == "loopback-ip":
        pod["status"]["podIP"] = "127.0.0.1"
    elif problem == "auth-disabled":
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        next(entry for entry in env if entry["name"] == "GATEWAY_AUTH_ENABLED")["value"] = "false"
    else:
        deployment["metadata"]["annotations"]["meta.helm.sh/release-name"] = "another-release"
    with pytest.raises(runtime.IsolationError, match=message):
        cluster.create_runtime_gateway(expected)
    assert not created and not waited


@pytest.mark.parametrize("target,mode", [("stable", "success"), ("web", "success"), ("directed", "body-error"),
                                         ("directed", "command-error"), ("stable", "wrong-bind-address")])
def test_http_forward_is_loopback_and_reaps_process(gateway_boundary, monkeypatch, target, mode):
    cluster, _, _, _ = gateway_boundary
    processes = []
    start_process = subprocess.Popen
    expected_target, remote_port = {"stable": (f"service/{runtime.GATEWAY}", 5013),
                                    "web": (f"service/{runtime.WEB}", 3000),
                                    "directed": ("pod/routing-gateway", 5013)}[target]

    def command(args):
        assert args == ("port-forward", "-n", runtime.NAMESPACE, "--address=127.0.0.1", expected_target,
                        f":{remote_port}")
        if mode == "command-error":
            return [sys.executable, "-c", "raise SystemExit(17)"]
        output_address = "0.0.0.0" if mode == "wrong-bind-address" else "127.0.0.1"
        return [sys.executable, "-c", f"import time; print('Forwarding from {output_address}:43210 -> {remote_port}', "
                "flush=True); time.sleep(30)"]

    def track_start(*args, **kwargs):
        process = start_process(*args, **kwargs)
        processes.append(process)
        return process

    detect_port = runtime._forwarded_port
    monkeypatch.setattr(cluster, "_kubectl_command", command)
    monkeypatch.setattr(runtime.subprocess, "Popen", track_start)
    monkeypatch.setattr(runtime, "_forwarded_port",
                        lambda process, output, _, port: detect_port(process, output, 1, port))
    pod_name = "routing-gateway" if target == "directed" else None

    if mode in {"command-error", "wrong-bind-address"}:
        with pytest.raises(runtime.IsolationError, match="loopback port-forward"):
            with cluster.gateway_http(pod_name):
                pytest.fail("Port forwarding must not yield an unusable target")
    elif mode == "body-error":
        with pytest.raises(RuntimeError, match="test body failed"):
            with cluster.gateway_http(pod_name) as url:
                assert url == "http://127.0.0.1:43210" and processes[0].poll() is None
                raise RuntimeError("test body failed")
    else:
        forward = cluster.web_http() if target == "web" else cluster.gateway_http(pod_name)
        with forward as url:
            assert url == "http://127.0.0.1:43210" and processes[0].poll() is None
    process, = processes
    assert process.poll() is not None


def test_gateway_forward_rejects_a_foreign_routing_gateway(gateway_boundary, monkeypatch):
    cluster, resources, _, _ = gateway_boundary
    resources[("pod", "routing-gateway")]["metadata"]["labels"][runtime.RUN_LABEL] = "foreign-run"
    monkeypatch.setattr(cluster, "_kubectl_command", lambda *_: pytest.fail("Foreign gateway cannot be forwarded"))
    with pytest.raises(runtime.IsolationError, match="owned Runtime routing Gateway"):
        with cluster.gateway_http("routing-gateway"):
            pytest.fail("Foreign gateway cannot be forwarded")


def test_web_forward_rejects_an_unexpected_service_selector(gateway_boundary, monkeypatch):
    cluster, resources, _, _ = gateway_boundary
    resources[("service", runtime.WEB)]["spec"]["selector"]["app"] = "other-workload"
    monkeypatch.setattr(cluster, "_kubectl_command", lambda *_: pytest.fail("Unexpected Web Service cannot be forwarded"))
    with pytest.raises(runtime.IsolationError, match="stable Web Service"):
        with cluster.web_http():
            pytest.fail("Unexpected Web Service cannot be forwarded")


@pytest.fixture
def transport_boundary(gateway_boundary, monkeypatch):
    cluster, resources, created, waited = gateway_boundary
    first = resources[("pod", "runtime-a")]
    first["spec"] = {"containers": [{"name": runtime.RUNTIME, "image": "runtime:test"}]}
    second = deepcopy(first)
    second["metadata"].update(name="runtime-b", uid="runtime-b-uid")
    second["status"]["podIP"] = "10.244.2.3"
    resources[("pod", "runtime-b")] = second
    service = {"metadata": {"uid": "owned-service-uid", "namespace": runtime.NAMESPACE,
                            "annotations": {"meta.helm.sh/release-name": runtime.NAMESPACE}},
               "spec": {"type": "ClusterIP", "ports": [{"port": 5014, "targetPort": 5014}],
                        "selector": {"app": runtime.RUNTIME}}}
    resources[("service", runtime.RUNTIME)] = service

    def create(manifest):
        created.append(manifest)
        return {"metadata": {"uid": "relay-uid"}}

    monkeypatch.setattr(cluster, "create_namespaced_fixture", create)
    return cluster, (first, second), service, created, waited


@pytest.mark.parametrize("failure", [None, "case-body", "endpoint-wait"])
@pytest.mark.parametrize("mode", ["cut", "stream-control", "voice", "northbound-admission"])
def test_transport_route_restores_only_the_original_owned_service(transport_boundary, monkeypatch, failure, mode):
    cluster, pods, service, created, waited = transport_boundary
    original = {"app": runtime.RUNTIME}
    relay = {"app": runtime.TRANSPORT_FIXTURE, runtime.RUN_LABEL: cluster.run_id}
    first_origin, peer_origin = (f"http://{pod['status']['podIP']}:5014" for pod in pods)
    switches, targets = [], []

    def patch(*args):
        expected, replacement = ((original, relay), (relay, original))[len(switches)]
        assert args[:-1] == ("patch", "service", runtime.RUNTIME, "-n", runtime.NAMESPACE, "--type=json", "-p")
        assert json.loads(args[-1]) == [
            {"op": "test", "path": "/metadata/uid", "value": "owned-service-uid"},
            {"op": "test", "path": "/spec/selector", "value": expected},
            {"op": "replace", "path": "/spec/selector", "value": replacement},
        ]
        assert service["spec"]["selector"] == expected
        service["spec"]["selector"] = replacement
        switches.append(replacement)

    def wait(expected):
        targets.append(expected)
        if failure == "endpoint-wait" and expected == {"relay-uid"}:
            raise runtime.IsolationError("relay endpoints did not converge")

    def exercise():
        options = {} if mode == "cut" else {"mode": mode}
        with cluster.route_runtime_through_transport_fixture(*pods, **options) as origins:
            assert failure != "endpoint-wait"
            assert service["spec"]["selector"] == relay
            assert origins == {"producer": first_origin, "peer": peer_origin}
            if failure == "case-body":
                raise RuntimeError("case body failed")

    monkeypatch.setattr(cluster, "_kubectl", patch)
    monkeypatch.setattr(cluster, "_wait_runtime_service_targets", wait)
    if failure:
        with pytest.raises(RuntimeError, match="did not converge|case body failed"):
            exercise()
    else:
        exercise()
    assert switches == [relay, original] and service["spec"]["selector"] == original
    assert targets == [{"relay-uid"}, {pod["metadata"]["uid"] for pod in pods}]
    manifest, = created
    assert manifest["metadata"]["labels"] == relay and not manifest["spec"]["automountServiceAccountToken"]
    assert manifest["spec"]["containers"][0]["command"][-5:] == [
        cluster.run_id, first_origin, peer_origin, "5014", mode,
    ]
    source = manifest["spec"]["containers"][0]["command"][3]
    assert ("def voice_app(" in source) is (mode == "voice")
    assert waited == [(f"pod/{runtime.TRANSPORT_FIXTURE}", "Ready")]


@pytest.mark.parametrize("problem", ["foreign-release", "external-ips", "foreign-selector", "wrong-port"])
def test_transport_route_refuses_unowned_or_external_service(transport_boundary, monkeypatch, problem):
    cluster, pods, service, created, waited = transport_boundary
    if problem == "foreign-release":
        service["metadata"]["annotations"]["meta.helm.sh/release-name"] = "foreign-release"
    elif problem == "external-ips":
        service["spec"]["externalIPs"] = ["192.0.2.1"]
    elif problem == "foreign-selector":
        service["spec"]["selector"] = {"app": "foreign"}
    else:
        service["spec"]["ports"][0]["targetPort"] = 80
    monkeypatch.setattr(cluster, "_kubectl", lambda *_: pytest.fail("Must not patch an unexpected Service"))
    with pytest.raises(runtime.IsolationError, match="outside the disposable Helm release"):
        with cluster.route_runtime_through_transport_fixture(*pods):
            pytest.fail("Must not yield a foreign Service")
    assert not created and not waited


def test_transport_route_rejects_unknown_mode_before_cluster_access(transport_boundary, monkeypatch):
    cluster, pods, _, created, waited = transport_boundary
    monkeypatch.setattr(cluster, "resources", lambda *_: pytest.fail("Unknown mode must not access the cluster"))
    with pytest.raises(ValueError, match="Unsupported Runtime transport fixture mode"):
        with cluster.route_runtime_through_transport_fixture(*pods, mode="unknown"):
            pytest.fail("Unknown mode must not redirect the Service")
    assert not created and not waited
