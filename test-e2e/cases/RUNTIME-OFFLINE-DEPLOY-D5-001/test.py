# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Live fixed-replica sequence and owned maintenance fault recovery."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import UUID

import pytest
import yaml

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_attachments import sign_in, upload_attachment
from shared.runtime_scaling_k8s import NAMESPACE, Profile, isolated_runtime_release
from shared.runtime_scaling_model import INPUT_NAME
from shared.runtime_scaling_owner_loss import (
    begin_owner_loss, delete_owner_conversations, model_receipt, owner_client, owner_snapshot,
    verify_after_maintenance, verify_interrupted_owner,
)


CASE_ID = "RUNTIME-OFFLINE-DEPLOY-D5-001"
RETRY_OWNER_TAG = "retry-owner"
BUSINESS = {"nexent-gateway", "nexent-web", "nexent-northbound", "nexent-config", "nexent-runtime",
            "nexent-mcp", "nexent-data-process"}
AUTOSCALERS = {"horizontalpodautoscalers.autoscaling", "scaledobjects.keda.sh", "scaledjobs.keda.sh"}

pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.p0, pytest.mark.deploy]


def test_fixed_replica_chart_boundaries(tmp_path):
    helm = shutil.which("helm")
    if helm is None:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail="Helm is required")
    command = [helm, "template", "nexent", str(repo_root() / "deploy/k8s/helm/nexent"), "--namespace", NAMESPACE,
               "--show-only", "charts/nexent-runtime/templates/deployment.yaml",
               "--set-string", "nexent-common.secrets.jwtSecret=d5-render-fixture-not-a-deployment-secret"]
    environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(tmp_path), "LANG": "C.UTF-8"}

    def render(*args):
        return subprocess.run([*command, *args], env=environment, capture_output=True, text=True, timeout=45)

    default = render()
    assert default.returncode == 0, "The Runtime Chart did not render with its default replica count"
    assert yaml.safe_load(default.stdout)["spec"]["replicas"] == 1
    paused = render("--set", "global.businessPaused=true")
    assert paused.returncode == 0, "The Runtime Chart did not render in maintenance pause mode"
    deployment = yaml.safe_load(paused.stdout)
    assert deployment["spec"]["replicas"] == 0
    assert deployment["metadata"]["annotations"]["nexent.io/maintenance-target-replicas"] == "1"
    for candidate in ("0", "-1", "1.5", "invalid"):
        for business_paused in ("false", "true"):
            invalid = render("--set", f"nexent-runtime.replicaCount={candidate}",
                             "--set", f"global.businessPaused={business_paused}")
            assert invalid.returncode != 0 and "replicaCount" in invalid.stderr, (candidate, business_paused)


@pytest.fixture
def isolated_release():
    try:
        path = test_root() / "config/runtime-scaling-k8s.yaml"
        profile = Profile.load(path)
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, agent_limit=1) as release:
        yield release
    write_case_evidence("runtime-offline-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def observe_release(cluster):
    deployments = {depl["metadata"]["name"]: depl for depl in cluster.resources("deployments")["items"]
                   if depl["metadata"]["name"] in BUSINESS}
    runtime = deployments["nexent-runtime"]
    business_pods = [pod for pod in cluster.resources("pods")["items"]
                     if pod["metadata"].get("labels", {}).get("app") in BUSINESS]
    annotations = runtime["metadata"].get("annotations", {})
    return {
        "epoch": annotations.get("nexent.io/maintenance-epoch"),
        "target_while_paused": annotations.get("nexent.io/maintenance-target-replicas"),
        "runtime_ready": runtime.get("status", {}).get("readyReplicas", 0),
        "runtime_available": runtime.get("status", {}).get("availableReplicas", 0),
        "runtime_reconciled": runtime.get("status", {}).get("observedGeneration") == runtime["metadata"]["generation"],
        "runtime_observed_replicas": runtime.get("status", {}).get("replicas", 0),
        "counts": {name: deployment["spec"]["replicas"] for name, deployment in deployments.items()},
        "pods": {pod["metadata"]["uid"]: pod["metadata"]["labels"]["app"] for pod in business_pods},
        "runtime_images": sorted({container["imageID"] for pod in business_pods
                                  if pod["metadata"]["labels"]["app"] == "nexent-runtime"
                                  for container in pod.get("status", {}).get("containerStatuses", ())}),
    }


def assert_ready(cluster, state, expected):
    assert state["counts"]["nexent-runtime"] == expected
    assert state["runtime_ready"] == state["runtime_available"] == expected
    assert state["runtime_reconciled"] is True
    assert state["target_while_paused"] is None
    assert state["counts"]["nexent-gateway"] > 0 and state["counts"]["nexent-web"] > 0
    assert list(state["pods"].values()).count("nexent-runtime") == expected
    assert str(UUID(state["epoch"])) == state["epoch"]
    assert cluster.committed_maintenance_count(state["epoch"]) == 1
    assert_no_autoscalers(cluster)


def assert_no_autoscalers(cluster):
    resources = cluster.discovered_resources()
    assert "horizontalpodautoscalers.autoscaling" in resources
    for resource in resources & AUTOSCALERS:
        assert cluster.resources(resource)["items"] == []


def is_fully_paused(state, count):
    return (state["target_while_paused"] == str(count) and not state["pods"]
            and not any(state["counts"].values()) and state["runtime_reconciled"]
            and state["runtime_observed_replicas"] == 0)


@contextmanager
def hold_activation(cluster, script, count, *, retry_epoch=None):
    with TemporaryDirectory(prefix="hold-activation-", dir=cluster.scratch) as directory:
        gate = Path(directory)
        wrapper = gate / "helm"
        shutil.copyfile(Path(__file__).with_name("hold-activation.sh"), wrapper)
        wrapper.chmod(0o700)
        with ThreadPoolExecutor(max_workers=1) as executor:
            deployment = executor.submit(cluster.deploy, script, count, retry_epoch=retry_epoch, helm_gate=gate)
            decision = "deny"
            try:
                arrived = gate / "arrived"
                deadline = monotonic() + 9 * cluster.profile.wait_seconds
                while not arrived.exists() and not deployment.done() and monotonic() < deadline:
                    sleep(0.25)
                assert arrived.is_file(), "Deployment did not request activation"
                epoch = arrived.read_text(encoding="utf-8").strip()
                assert str(UUID(epoch)) == epoch
                if retry_epoch is not None:
                    assert epoch == retry_epoch
                paused = observe_release(cluster)
                assert paused["epoch"] == epoch and is_fully_paused(paused, count)
                assert cluster.committed_maintenance_count(epoch) == 1
                assert_no_autoscalers(cluster)
                yield paused
                decision = "allow"
            finally:
                temp = gate / "decision.tmp"
                temp.write_text(decision, encoding="utf-8")
                temp.replace(gate / "decision")
            result = deployment.result()
        if result.returncode:
            pytest.fail(f"Offline activation of {count} replicas failed (exit {result.returncode})")


def owned_deployment_db(cluster, epoch, query):
    cluster.require_owned_namespace()
    return cluster._kubectl(
        "exec", "-i", "-n", NAMESPACE, "deployment/nexent-postgresql", "-c", "postgresql", "--", "sh", "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        '-X -qAt -w -v ON_ERROR_STOP=1 -v "lock_name=$1" -v "epoch=$2"',
        "runtime-scaling-d5", cluster.deployment_lock_name, epoch, stdin=query,
    )


def committed_maintenance_digest(cluster, epoch):
    row, = owned_deployment_db(cluster, epoch, """
        SELECT row_to_json(reservation)::text FROM nexent.execution_reservation_t AS reservation
        WHERE execution_kind = 'maintenance' AND service_role = 'runtime' AND status = 'COMPLETED'
          AND delete_flag = 'N' AND finished_at IS NOT NULL AND maintenance_epoch = :'epoch';
    """).splitlines()
    return hashlib.sha256(row.encode()).hexdigest()


def terminate_deployment_lock(cluster, epoch):
    query = Path(__file__).with_name("terminate-deployment-lock.sql").read_text(encoding="utf-8")
    result = owned_deployment_db(cluster, epoch, query)
    pid, separator, terminated = result.strip().partition("|")
    assert pid.isdecimal() and separator and terminated == "t", "No owned deployment lock session was terminated"
    return int(pid)


def test_completed_maintenance_without_deployment_lock_cannot_activate(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, initial=True).returncode == 0, "Initial product deployment failed"
    initial = observe_release(cluster)
    assert_ready(cluster, initial, 1)

    target = 2
    with TemporaryDirectory(prefix="lose-deploy-lock-", dir=cluster.scratch) as directory:
        gate = Path(directory)
        for executable, wrapper in (("helm", "hold-activation.sh"), ("kubectl", "hold-maintenance-result.sh")):
            shutil.copyfile(Path(__file__).with_name(wrapper), gate / executable)
            (gate / executable).chmod(0o700)
        (gate / "decision").write_text("deny", encoding="utf-8")
        with ThreadPoolExecutor(max_workers=1) as executor:
            deployment = executor.submit(cluster.deploy, script, target, helm_gate=gate, kubectl_gate=gate)
            decision = "deny"
            try:
                arrived = gate / "maintenance-arrived"
                deadline = monotonic() + 9 * cluster.profile.wait_seconds
                while not arrived.exists() and not deployment.done() and monotonic() < deadline:
                    sleep(0.25)
                assert arrived.is_file(), "Maintenance Job did not report success"
                epoch = arrived.read_text(encoding="utf-8").strip()
                assert str(UUID(epoch)) == epoch and epoch != initial["epoch"]
                paused = observe_release(cluster)
                assert paused["epoch"] == epoch and is_fully_paused(paused, target)
                completion = committed_maintenance_digest(cluster, epoch)
                assert not (gate / "arrived").exists(), "Activation was requested before maintenance finished"
                terminated_pid = terminate_deployment_lock(cluster, epoch)
                decision = "allow"
            finally:
                temporary = gate / "maintenance-decision.tmp"
                temporary.write_text(decision, encoding="utf-8")
                temporary.replace(gate / "maintenance-decision")
            result = deployment.result()
        assert not (gate / "arrived").exists(), "Deployment tried to activate without its lock"
    assert result.returncode != 0 and "Runtime deployment lock or expected maintenance completion" in result.stderr
    failed = observe_release(cluster)
    assert failed["epoch"] == epoch and is_fully_paused(failed, target)
    assert committed_maintenance_digest(cluster, epoch) == completion
    assert_no_autoscalers(cluster)

    with hold_activation(cluster, script, target) as recovery:
        assert recovery["epoch"] not in {initial["epoch"], epoch}
    ready = observe_release(cluster)
    assert_ready(cluster, ready, target)
    assert ready["epoch"] == recovery["epoch"] and committed_maintenance_digest(cluster, epoch) == completion
    write_case_evidence("runtime-offline-deployment-lock-loss", {
        "initial": initial, "paused": paused, "terminated_deployment_lock_pid": terminated_pid,
        "activation_requested_without_lock": False, "maintenance_record_sha256": completion,
        "failed": failed, "recovered": ready,
    })


def test_unfinished_maintenance_job_does_not_pause_the_running_release(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, initial=True).returncode == 0, "Initial product deployment failed"
    before = observe_release(cluster)
    assert_ready(cluster, before, 1)
    epoch = before["epoch"]
    completion = committed_maintenance_digest(cluster, epoch)
    initial_job = f"nexent-runtime-maintenance-{epoch}"
    cluster.wait_for_condition(f"job/{initial_job}", "Complete")
    container, = cluster.resources("job", initial_job)["spec"]["template"]["spec"]["containers"]
    stranded = f"nexent-d5-stranded-maintenance-{cluster.run_id[:12]}"
    labels = {"app": "nexent-runtime-maintenance", "app.kubernetes.io/instance": NAMESPACE}
    cluster.create_namespaced_fixture({
        "apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": stranded, "labels": labels},
        "spec": {"suspend": True, "backoffLimit": 0, "template": {"metadata": {"labels": labels}, "spec": {
            "restartPolicy": "Never", "automountServiceAccountToken": False,
            "containers": [{"name": "stranded", "image": container["image"], "imagePullPolicy": "Never",
                            "command": ["sh", "-c", "exit 1"]}],
        }}},
    })
    previous_job = cluster.resources("job", stranded)
    assert not cluster.resources("pods", "-l", f"job-name={stranded}")["items"]
    jobs_before = {job["metadata"]["uid"] for job in cluster.resources("jobs")["items"]}

    blocked = cluster.deploy(script, 2)
    assert blocked.returncode != 0 and f"Job {NAMESPACE}/{stranded} is not terminal" in blocked.stderr
    assert observe_release(cluster) == before
    assert committed_maintenance_digest(cluster, epoch) == completion
    assert {job["metadata"]["uid"] for job in cluster.resources("jobs")["items"]} == jobs_before
    preserved = cluster.resources("job", stranded)
    assert preserved["metadata"]["uid"] == previous_job["metadata"]["uid"]
    assert preserved["metadata"]["generation"] == previous_job["metadata"]["generation"]
    assert not cluster.resources("pods", "-l", f"job-name={stranded}")["items"]
    write_case_evidence("runtime-offline-stranded-maintenance", {
        "epoch": epoch, "stranded_job_uid": preserved["metadata"]["uid"], "release": before,
        "maintenance_record_sha256": completion, "deployment_rejected": True,
    })


class StateProbe:
    def __init__(self, cluster, initial_epoch):
        self.cluster = cluster
        self.name = f"nexent-d5-maintenance-{cluster.run_id[:12]}"
        self.source = Path(__file__).with_name("maintenance_state_probe.py").read_text(encoding="utf-8")
        self._install(initial_epoch)

    def _install(self, epoch):
        initial_job = self.cluster.resources("job", f"nexent-runtime-maintenance-{epoch}")
        template = deepcopy(initial_job["spec"]["template"]["spec"])
        rbac_api = "rbac.authorization.k8s.io/v1"
        metadata = {"name": self.name}
        self.cluster.create_namespaced_fixture({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": metadata})
        self.cluster.create_namespaced_fixture({"apiVersion": rbac_api, "kind": "Role", "metadata": metadata, "rules": [
            {"apiGroups": ["apps"], "resources": ["deployments"], "resourceNames": ["nexent-runtime"], "verbs": ["get"]},
            {"apiGroups": [""], "resources": ["pods"], "verbs": ["list"]},
        ]})
        self.cluster.create_namespaced_fixture({"apiVersion": rbac_api, "kind": "RoleBinding", "metadata": metadata,
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": self.name},
            "subjects": [{"kind": "ServiceAccount", "name": self.name, "namespace": NAMESPACE}]})
        container, = template["containers"]
        container.update(command=["python", "-c"], args=["from threading import Event; Event().wait()"])
        template.update(serviceAccountName=self.name, automountServiceAccountToken=True, restartPolicy="Never")
        self.cluster.create_namespaced_fixture({"apiVersion": "v1", "kind": "Pod", "metadata": metadata, "spec": template})
        self.cluster.wait_for_condition(f"pod/{self.name}", "Ready")

    def __call__(self, action, *args):
        output = self.cluster.run_fixture_python(self.name, self.source, action, self.cluster.run_id, *args)
        record, = (line.removeprefix("D5_STATE ") for line in output.splitlines() if line.startswith("D5_STATE "))
        return json.loads(record)


class MaintenanceReceipts:
    def __init__(self, storage_probe, control, content):
        self.storage_probe = storage_probe
        self.control = control
        self.digest = hashlib.sha256(content).hexdigest()
        self.tools = {}

    def __call__(self, *tags, allow_auxiliary=False):
        model = model_receipt(self.control, *tags, rounds=2, allow_auxiliary=allow_auxiliary)
        observed = self.storage_probe("read-tool-receipts")
        assert observed.keys() == set(tags), observed
        for tag, versions in observed.items():
            assert len(versions) == 1, f"Tool write count for {tag} is {len(versions)}, expected one"
            version, = versions
            assert version["sha256"] == self.digest
            assert tag not in self.tools or self.tools[tag] == version, f"Tool receipt for {tag} changed"
            self.tools[tag] = version
        return {"model": model, "tools": observed}


def assert_preserved(prior, current):
    for name, key in (("messages", "message_id"), ("evaluations", "agent_evaluation_id"),
                      ("later_messages", "message_id"),
                      ("evaluation_cases", "agent_evaluation_case_id"), ("tasks", "task_id"),
                      ("automation_runs", "run_id"), ("reservations", "execution_id")):
        assert [row[key] for row in current[name]] == [row[key] for row in prior[name]], name
    for name in ("messages", "later_messages", "evaluations", "evaluation_cases", "automation_runs"):
        assert len(prior[name]) == 2
        assert current[name][1] == prior[name][1], f"Terminal record was modified: {name}"
    assert current["reservations"][1] == prior["reservations"][1]
    completed = prior["later_stream"]
    assert completed["run"]["status"] == completed["done"]["status"] == "completed"
    assert completed["run"]["message_id"] == str(prior["later_messages"][1]["message_id"])
    assert completed["run"]["execution_id"] == str(prior["reservations"][1]["execution_id"])
    assert completed["replay"] and completed["events"]
    assert current["later_stream"] == completed, "Recovery changed the newer completed stream in the same conversation"
    assert current["non_run_file"] is not None and current["non_run_file"] == prior["non_run_file"]
    assert current["redis_sentinel"] is not None and current["redis_sentinel"] == prior["redis_sentinel"]


def assert_failed_recovery_did_not_commit(seeded, after_failure):
    assert_preserved(seeded, after_failure)
    for name in ("messages", "later_messages", "evaluations", "evaluation_cases", "reservations",
                 "automation_runs", "tasks"):
        assert after_failure[name] == seeded[name], f"Failed maintenance committed {name}"
    assert after_failure["run_file"] == seeded["run_file"] and seeded["run_file"] is not None
    assert after_failure["redis_status"] == after_failure["redis_done"] == "failed"


def induce_maintenance_failure(cluster, script, probe, seeded, prior_epoch):
    probe("block-cleanup")
    try:
        failed = cluster.deploy(script, 3)
        if failed.returncode == 0:
            pytest.fail("Deployment activated despite an invalid workspace root")
        paused = observe_release(cluster)
        assert is_fully_paused(paused, 3)
        epoch = paused["epoch"]
        assert str(UUID(epoch)) == epoch and epoch != prior_epoch
        failed_job = f"job/nexent-runtime-maintenance-{epoch}"
        cluster.wait_for_condition(failed_job, "Failed")
        cluster.maintenance_image_receipts(epoch, phase="Failed")
        if "Runtime maintenance failed; keep the release paused (ValueError)" not in cluster.fixture_logs(failed_job):
            pytest.fail("Maintenance Job did not report the injected workspace failure")
        assert cluster.committed_maintenance_count(epoch) == 0
        assert_no_autoscalers(cluster)
        assert_failed_recovery_did_not_commit(seeded, probe("snapshot"))
        return paused
    finally:
        probe("restore-cleanup")


def assert_recovered(seeded, recovered):
    assert_preserved(seeded, recovered)
    assert recovered["messages"][0]["status"] == "failed"
    assert recovered["later_messages"][0]["status"] == "failed"
    for name in ("evaluations", "evaluation_cases"):
        assert recovered[name][0]["status"] == "FAILED"
    run, = [row for row in recovered["automation_runs"] if row["status"] != "SUCCEEDED"]
    assert (run["status"], run["error_code"]) == ("TIMEOUT", "AUTOMATION_LEASE_EXPIRED")
    task, = recovered["tasks"]
    assert task["lock_owner"] is None and task["lock_until"] is None
    reservation, completed = recovered["reservations"]
    assert completed["status"] == "COMPLETED"
    assert (reservation["status"], reservation["error_code"]) == ("FAILED", "RUNTIME_OWNER_INTERRUPTED")
    assert reservation["finished_at"] is not None
    assert recovered["run_file"] is None
    assert recovered["redis_status"] == recovered["redis_done"] == "failed"


def retry_and_check_idempotency(cluster, script, probe, epoch, seeded, observe, loss, snapshot):
    with hold_activation(cluster, script, 3, retry_epoch=epoch):
        recovered = probe("snapshot")
        assert_recovered(seeded, recovered)
        verify_interrupted_owner(loss, epoch=epoch, snapshot=snapshot)
        receipts = {"retried_before_activation": observe(RETRY_OWNER_TAG)}
        sentinel = probe("add-run-sentinel")
        after_sentinel = probe("snapshot")
        assert sentinel and sentinel == after_sentinel["run_file"]
        assert probe("repeat-completed", epoch) is False
        assert probe("snapshot") == after_sentinel
        assert cluster.committed_maintenance_count(epoch) == 1
        receipts["after_completed_batch_repeat"] = observe(RETRY_OWNER_TAG)
    ready = observe_release(cluster)
    assert_ready(cluster, ready, 3)
    assert ready["epoch"] == epoch
    return ready, after_sentinel, receipts


def verify_runtime_restart(cluster, probe, ready, expected):
    first = cluster.resources("pods", "-l", "app=nexent-runtime")["items"][0]
    old_uid = first["metadata"]["uid"]
    cluster.restart_owned_runtime_pod(first)
    deadline = monotonic() + cluster.profile.wait_seconds
    while monotonic() < deadline:
        current = observe_release(cluster)
        if (old_uid not in current["pods"] and current["runtime_available"] == 3
                and list(current["pods"].values()).count("nexent-runtime") == 3):
            break
        sleep(0.5)
    else:
        pytest.fail("Replacement Runtime Pod did not become available")
    assert_ready(cluster, current, 3)
    assert current["epoch"] == ready["epoch"]
    observed = probe("snapshot")
    for key in ("redis_status", "redis_done"):
        assert observed.pop(key) in (None, expected[key])
    assert observed == {key: value for key, value in expected.items() if key not in {"redis_status", "redis_done"}}
    return current


def interrupt_live_run(cluster, epoch, identity, agent, *, tag, observe, minio_files, prior_tags=()):
    owner, *peers = cluster.runtime_pods()
    observer = peers[0] if peers else owner
    control = cluster.runtime_model_control

    def interrupt():
        observe(*prior_tags, tag)
        cluster.restart_owned_runtime_pod(owner, interrupt=True)

    with owner_client(cluster) as stable, owner_client(cluster, owner) as producer:
        loss = begin_owner_loss(
            stable, producer, sign_in(stable, identity), agent, cluster.run_id, epoch=epoch,
            snapshot=owner_snapshot(cluster, observer, quota=1), control=control,
            crash=interrupt, expected_host=owner["metadata"]["name"], tag=tag, prior_tags=prior_tags,
            rounds=2, minio_files=minio_files,
        )
    assert control(f"release/{tag}")["released"] is True
    return loss


def test_offline_replica_sequence(isolated_release):
    cluster, script = isolated_release
    initial = cluster.deploy(script, initial=True)
    if initial.returncode:
        pytest.fail(f"Initial product deployment failed (exit {initial.returncode})")
    previous = observe_release(cluster)
    assert_ready(cluster, previous, 1)
    evidence = [{"ready": previous}]
    initial_epoch = previous["epoch"]
    probe = StateProbe(cluster, initial_epoch)
    seeded = probe("seed", initial_epoch)
    assert probe("check-live-rejection", initial_epoch) == "live-runtime-rejected"
    assert probe("snapshot") == seeded
    initial_pod, = cluster.runtime_pods()
    identity = cluster.seed_runtime_identities(initial_pod)["owner"]
    cluster.create_runtime_model(initial_pod, mode="maintenance")
    agent = cluster.seed_runtime_agent(initial_pod)
    control = cluster.runtime_model_control
    minio_service = cluster.resources("service", "nexent-minio")
    assert minio_service["metadata"]["namespace"] == NAMESPACE
    assert minio_service["spec"]["selector"].get("app") == "nexent-minio"
    assert probe("enable-tool-receipts") == "Enabled"
    content = f"offline-maintenance-tool:{cluster.run_id}\n".encode()
    observe = MaintenanceReceipts(probe, control, content)
    observe()
    with owner_client(cluster) as stable:
        artifact = upload_attachment(stable, sign_in(stable, identity), identity["user_id"], INPUT_NAME, content)
    minio_files = ({"object_name": artifact, "name": INPUT_NAME},)
    retry_loss = interrupt_live_run(cluster, initial_epoch, identity, agent, tag=RETRY_OWNER_TAG,
                                    observe=observe, minio_files=minio_files)
    retry_receipts = {"before_failure": observe(RETRY_OWNER_TAG)}
    failed_pause = induce_maintenance_failure(cluster, script, probe, seeded, initial_epoch)
    paused_snapshot = owner_snapshot(cluster, cluster.resources("pod", probe.name))
    retry_identifier, _, retry_active = retry_loss
    after_failure = paused_snapshot(retry_identifier)["runs"][str(retry_identifier)]
    for key in ("reservations", "users", "assistants"):
        assert after_failure[key] == retry_active[key], f"Failed batch committed the live run's {key}"
    retry_receipts["after_failure"] = observe(RETRY_OWNER_TAG)
    ready, post_maintenance, batch_receipts = retry_and_check_idempotency(
        cluster, script, probe, failed_pause["epoch"], seeded, observe, retry_loss, paused_snapshot,
    )
    retry_receipts.update(batch_receipts)
    assert not (previous["pods"].keys() & ready["pods"].keys())
    recovered_pod = cluster.runtime_pods()[0]
    interrupted, _ = verify_interrupted_owner(
        retry_loss, epoch=ready["epoch"], snapshot=owner_snapshot(cluster, recovered_pod, quota=1),
    )
    with owner_client(cluster) as stable:
        delete_owner_conversations(stable, sign_in(stable, identity), retry_loss)
    retry_receipts["after_activation"] = observe(RETRY_OWNER_TAG)
    previous = verify_runtime_restart(cluster, probe, ready, post_maintenance)
    retry_receipts["after_ordinary_restart"] = observe(RETRY_OWNER_TAG)
    evidence.append({"failed_pause": failed_pause, "retried": ready, "single_pod_restarted": previous,
                     "retry_run": {"receipts": retry_receipts, "interrupted_state": interrupted["error_code"],
                                   "interrupted_execution": interrupted["id"], "owned_conversations_deleted": True}})
    epochs = {initial_epoch, ready["epoch"]}
    prior_tags = (RETRY_OWNER_TAG,)
    rollback_tags = (*prior_tags, "lost-owner")
    for count in (2, 1):
        rollback = None
        if count == 1:
            rollback = interrupt_live_run(cluster, previous["epoch"], identity, agent, tag="lost-owner",
                                          observe=observe, minio_files=minio_files, prior_tags=prior_tags)
        receipts = {"before_maintenance": observe(*rollback_tags)} if rollback else None
        with hold_activation(cluster, script, count) as pause:
            assert pause["epoch"] not in epochs
            if rollback:
                receipts["before_activation"] = observe(*rollback_tags)
        ready = observe_release(cluster)
        assert_ready(cluster, ready, count)
        assert pause["epoch"] == ready["epoch"]
        assert not (previous["pods"].keys() & ready["pods"].keys())
        observed = {"pause": pause, "ready": ready}
        if rollback:
            recovered_pod, = cluster.runtime_pods()
            with owner_client(cluster) as stable:
                auth = sign_in(stable, identity)
                receipts["before_explicit_request"] = observe(*rollback_tags)
                recovered = verify_after_maintenance(
                    stable, auth, agent, cluster.run_id, rollback, epoch=ready["epoch"],
                    snapshot=owner_snapshot(cluster, recovered_pod, quota=1), control=control, wait_seconds=60,
                    prior_tags=prior_tags, rounds=2, minio_files=minio_files,
                )
            receipts["after_explicit_request"] = observe(*rollback_tags, "after-maintenance", allow_auxiliary=True)
            observed["rollback_run"] = {**recovered, "receipts": receipts}
        evidence.append(observed)
        epochs.add(ready["epoch"])
        previous = ready
    final_state = probe("snapshot")
    assert_preserved(seeded, final_state)
    assert final_state["run_file"] is None
    write_case_evidence("runtime-offline-replica-sequence", evidence)
