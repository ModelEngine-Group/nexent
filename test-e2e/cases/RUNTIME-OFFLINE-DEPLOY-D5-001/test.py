# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify that idle fixed-replica changes complete bootstrap before activation."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

import pytest
import yaml

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_admission import assert_completed, new_conversations, post_agent, wait_for
from shared.runtime_scaling_attachments import sign_in
from shared.runtime_scaling_k8s import NAMESPACE, RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_owner_loss import owner_client
from shared.runtime_scaling_stream import conversation_history


CASE_ID = "RUNTIME-OFFLINE-DEPLOY-D5-001"
BUSINESS = {
    "nexent-gateway", "nexent-web", "nexent-northbound", "nexent-config",
    RUNTIME, "nexent-mcp", "nexent-data-process",
}
AUTOSCALERS = {"horizontalpodautoscalers.autoscaling", "scaledobjects.keda.sh", "scaledjobs.keda.sh"}
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.p0, pytest.mark.deploy]


def test_fixed_replica_chart_boundaries(tmp_path):
    helm = shutil.which("helm")
    if helm is None:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail="Helm is required")
    command = [helm, "template", "nexent", str(repo_root() / "deploy/k8s/helm/nexent"), "--namespace", NAMESPACE,
               "--show-only", "charts/nexent-runtime/templates/deployment.yaml",
               "--set", "nexent-runtime.replicaCount=1", "--set", "global.sandboxProvider=docker",
               "--set-string", "nexent-common.secrets.jwtSecret=d5-render-fixture-not-a-deployment-secret"]
    environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(tmp_path), "LANG": "C.UTF-8"}

    def render(*args):
        return subprocess.run([*command, *args], env=environment, capture_output=True, text=True, timeout=45)

    default = render()
    assert default.returncode == 0, default.stderr
    assert yaml.safe_load(default.stdout)["spec"]["replicas"] == 1
    paused = render("--set", "global.businessPaused=true")
    assert paused.returncode == 0, paused.stderr
    deployment = yaml.safe_load(paused.stdout)
    assert deployment["spec"]["replicas"] == 0
    assert "nexent.io/maintenance-epoch" not in deployment["metadata"].get("annotations", {})
    for candidate in ("0", "-1", "1.5", "invalid"):
        for paused in ("false", "true"):
            invalid = render("--set", f"nexent-runtime.replicaCount={candidate}",
                             "--set", f"global.businessPaused={paused}")
            assert invalid.returncode != 0 and "replicaCount" in invalid.stderr, (candidate, paused)


@pytest.fixture
def isolated_release():
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, agent_limit=1) as release:
        yield release
    write_case_evidence("runtime-offline-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def observe_release(cluster):
    deployments = {entry["metadata"]["name"]: entry for entry in cluster.resources("deployments")["items"]
                   if entry["metadata"]["name"] in BUSINESS}
    runtime = cluster.fixed_runtime_deployment()
    status = runtime.get("status", {})
    return {
        "generation": runtime["metadata"]["generation"],
        "observed_generation": status.get("observedGeneration"),
        "ready": status.get("readyReplicas", 0),
        "available": status.get("availableReplicas", 0),
        "observed_replicas": status.get("replicas", 0),
        "counts": {name: entry["spec"]["replicas"] for name, entry in deployments.items()},
        "pods": {pod["metadata"]["uid"]: pod["metadata"]["labels"]["app"]
                 for pod in cluster.resources("pods")["items"]
                 if pod["metadata"].get("labels", {}).get("app") in BUSINESS},
    }


def assert_ready(cluster, state, expected):
    assert state["counts"][RUNTIME] == state["ready"] == state["available"] == expected
    assert state["generation"] == state["observed_generation"]
    assert state["counts"]["nexent-gateway"] > 0 and state["counts"]["nexent-web"] > 0
    assert list(state["pods"].values()).count(RUNTIME) == expected
    resources = cluster.discovered_resources()
    assert "horizontalpodautoscalers.autoscaling" in resources
    for resource in resources & AUTOSCALERS:
        assert cluster.resources(resource)["items"] == []
    assert not cluster.resources("jobs", "-l", "app=nexent-runtime-maintenance")["items"]


def assert_paused(state):
    assert state["generation"] == state["observed_generation"]
    assert state["observed_replicas"] == 0
    assert not state["pods"] and not any(state["counts"].values())


def install_gate(directory, tool, script):
    wrapper = directory / tool
    shutil.copyfile(Path(__file__).with_name(script), wrapper)
    wrapper.chmod(0o700)


def write_decision(directory, name, decision):
    temporary = directory / f"{name}.tmp"
    temporary.write_text(decision, encoding="utf-8")
    temporary.replace(directory / name)


def test_offline_replica_sequence(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, initial=True).returncode == 0
    previous = observe_release(cluster)
    assert_ready(cluster, previous, 1)
    pod, = cluster.runtime_pods()
    identity = cluster.seed_runtime_identities(pod)["owner"]
    cluster.create_runtime_model(pod, mode="admission")
    agent = cluster.seed_runtime_agent(pod)
    config = {"agent_id": agent["agent_id"], "model_id": agent["model_id"]}
    tag = "idle-completed"
    with owner_client(cluster) as gateway, ThreadPoolExecutor(max_workers=1) as executor:
        auth = sign_in(gateway, identity)
        conversation, = new_conversations(gateway, auth, 1)
        response = executor.submit(post_agent, gateway, auth, config, cluster.run_id, conversation, tag)
        try:
            wait_for(lambda: cluster.runtime_model_control("probe")["calls_by_tag"].get(tag) == 1,
                     60, "The candidate never started the owned chat")
        finally:
            cluster.runtime_model_control("release")
        assert_completed(response.result(timeout=60), conversation, tag)

    source = (Path(__file__).with_name("execution_probe.py")).read_text(encoding="utf-8")

    def execution_receipt():
        pod = cluster.runtime_pods()[0]["metadata"]["name"]
        raw = cluster.run_fixture_python(pod, source, cluster.run_id, str(conversation))
        return next(json.loads(line.removeprefix("SCALING_IDLE "))
                    for line in raw.splitlines() if line.startswith("SCALING_IDLE "))

    def completed_run():
        rows = execution_receipt()
        return rows if len(rows) == 1 and rows[0]["status"] == "completed" else None

    before = wait_for(completed_run, 45, "The chat never reached a durable terminal")
    with owner_client(cluster) as gateway:
        history = conversation_history(gateway, sign_in(gateway, identity), conversation)
    calls = cluster.runtime_model_control("probe")["calls_by_tag"]
    receipts = []
    log_dir = script.parents[2] / "logs/deploy"
    for count in (3, 2, 1):
        previous_logs = set(log_dir.glob("deploy-*"))
        with TemporaryDirectory(prefix="idle-activation-", dir=cluster.scratch) as temporary:
            gate = Path(temporary)
            install_gate(gate, "helm", "hold-activation.sh")
            with ThreadPoolExecutor(max_workers=1) as executor:
                deployment = executor.submit(cluster.deploy, script, count, helm_gate=gate)
                decision = "deny"
                try:
                    wait_for(lambda: (gate / "arrived").exists(),
                             9 * cluster.profile.wait_seconds, "Deployment never requested activation")
                    paused = observe_release(cluster)
                    assert_paused(paused)
                    bootstrap = cluster.bootstrap_image_receipts()
                    deployment_log, = set(log_dir.glob("deploy-*")) - previous_logs
                    assert "[sql-migrations] apply __init.sql" in deployment_log.read_text(encoding="utf-8")
                    decision = "allow"
                finally:
                    write_decision(gate, "decision", decision)
                deployed = deployment.result()
                assert deployed.returncode == 0, deployed.stderr
                assert deployment_log.name in deployed.stdout
                assert "[sql-migrations] apply __init.sql" not in deployed.stdout + deployed.stderr
        ready = observe_release(cluster)
        assert_ready(cluster, ready, count)
        assert not (previous["pods"].keys() & ready["pods"].keys())
        assert execution_receipt() == before
        with owner_client(cluster) as gateway:
            assert conversation_history(gateway, sign_in(gateway, identity), conversation) == history
        assert cluster.runtime_model_control("probe")["calls_by_tag"] == calls
        receipts.append({"paused": paused, "bootstrap": bootstrap, "ready": ready})
        previous = ready
    write_case_evidence("runtime-idle-offline-sequence", {"deployments": receipts, "committed_run": before})


def terminate_deployment_lock(cluster):
    cluster.require_owned_namespace()
    source = Path(__file__).with_name("terminate-deployment-lock.sql").read_text(encoding="utf-8")
    output = cluster._kubectl(
        "exec", "-i", "-n", NAMESPACE, "deployment/nexent-postgresql", "-c", "postgresql", "--", "sh", "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        '-X -qAt -w -v ON_ERROR_STOP=1 -v "lock_name=$1"',
        "runtime-scaling-d5", cluster.deployment_lock_name, stdin=source,
    )
    pid, separator, terminated = output.strip().partition("|")
    assert pid.isdecimal() and separator and terminated == "t"
    return int(pid)


@pytest.mark.parametrize("fault", ("bootstrap-failed", "lock-lost"))
def test_activation_waits_for_bootstrap_and_deploy_lock(isolated_release, fault):
    cluster, script = isolated_release
    assert cluster.deploy(script, initial=True).returncode == 0
    initial = observe_release(cluster)
    assert_ready(cluster, initial, 1)
    with TemporaryDirectory(prefix="bootstrap-result-", dir=cluster.scratch) as temporary:
        gate = Path(temporary)
        install_gate(gate, "helm", "hold-activation.sh")
        install_gate(gate, "kubectl", "hold-bootstrap-result.sh")
        with ThreadPoolExecutor(max_workers=1) as executor:
            deploy = executor.submit(cluster.deploy, script, 2, helm_gate=gate, kubectl_gate=gate)
            decision = "deny"
            try:
                wait_for(lambda: (gate / "bootstrap-arrived").exists(), 9 * cluster.profile.wait_seconds,
                         "The fixture did not observe the successful bootstrap Job")
                assert_paused(observe_release(cluster))
                bootstrap = cluster.bootstrap_image_receipts()
                if fault == "lock-lost":
                    terminate_deployment_lock(cluster)
                decision = "allow" if fault == "lock-lost" else "fail"
            finally:
                write_decision(gate, "bootstrap-decision", decision)
                write_decision(gate, "decision", "deny")
            rejected = deploy.result()
        assert not (gate / "arrived").exists(), "The deployment requested Helm activation after its gate failed"
    error = "Runtime deployment lock" if fault == "lock-lost" else "system Agent bootstrap failed"
    assert rejected.returncode != 0 and error in rejected.stderr
    paused = observe_release(cluster)
    assert_paused(paused)
    assert cluster.deploy(script, 2).returncode == 0
    recovered = observe_release(cluster)
    assert_ready(cluster, recovered, 2)
    write_case_evidence(f"runtime-idle-{fault}", {"paused": paused, "bootstrap": bootstrap, "recovered": recovered})


def test_unfinished_bootstrap_job_does_not_pause_the_running_release(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, initial=True).returncode == 0
    before = observe_release(cluster)
    assert_ready(cluster, before, 1)
    pod, = cluster.runtime_pods()
    container, = (item for item in pod["spec"]["containers"] if item["name"] == RUNTIME)
    name = f"nexent-d5-stranded-bootstrap-{cluster.run_id[:12]}"
    labels = {"app": "nexent-system-bootstrap", "app.kubernetes.io/instance": NAMESPACE}
    cluster.create_namespaced_fixture({
        "apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "labels": labels},
        "spec": {"suspend": True, "backoffLimit": 0, "template": {"metadata": {"labels": labels}, "spec": {
            "restartPolicy": "Never", "automountServiceAccountToken": False,
            "containers": [{"name": "stranded", "image": container["image"], "imagePullPolicy": "Never",
                            "command": ["sh", "-c", "exit 1"]}],
        }}},
    })
    job = cluster.resources("job", name)
    assert not cluster.resources("pods", "-l", f"job-name={name}")["items"]
    blocked = cluster.deploy(script, 2)
    assert blocked.returncode != 0 and f"Job {NAMESPACE}/{name} is not terminal" in blocked.stderr
    assert observe_release(cluster) == before
    after = cluster.resources("job", name)
    assert after["metadata"]["uid"] == job["metadata"]["uid"]
    assert after["metadata"]["generation"] == job["metadata"]["generation"]
    assert not cluster.resources("pods", "-l", f"job-name={name}")["items"]
    write_case_evidence("runtime-idle-stranded-bootstrap", {"job_uid": after["metadata"]["uid"], "ready": before})
