# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prove the storage and restart boundary of two actual Runtime Pods."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from time import monotonic, sleep

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_attachments import verify_authenticated_attachments
from shared.runtime_scaling_k8s import NAMESPACE, RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_live_run import exercise_live_attachment_pair


CASE_ID = "RUNTIME-SHARED-STORAGE-D3-001"
EXPECTED_MOUNTS = {"nexent-workspace": "/mnt/nexent", "nexent-skills": "/mnt/nexent-data/skills",
                   "nexent-memory-plugins": "/mnt/nexent-data/memory-provider-plugins",
                   "nexent-logs": "/mnt/nexent-data/logs"}

pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D3"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release():
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, separate_workers=True) as release:
        yield release
    write_case_evidence("runtime-shared-storage-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def runtime_container(pod):
    container, = (container for container in pod["spec"]["containers"] if container["name"] == RUNTIME)
    return container


def container_state(pod):
    status, = (status for status in pod["status"]["containerStatuses"] if status["name"] == RUNTIME)
    return status


def runtime_reconciled(deployment):
    spec, status, metadata = deployment["spec"], deployment.get("status", {}), deployment["metadata"]
    return (spec["replicas"] == status.get("readyReplicas") == status.get("availableReplicas") == 2
            and status.get("observedGeneration") == metadata["generation"])


def ready_pair(cluster, eligible, departed_uid=None, wait_seconds=None):
    deadline = monotonic() + min(cluster.profile.wait_seconds, wait_seconds or cluster.profile.wait_seconds)
    while monotonic() < deadline:
        pods = cluster.runtime_pods()
        if len(pods) == 2 and all(
            pod["metadata"].get("namespace") == NAMESPACE
            and not pod["metadata"].get("deletionTimestamp")
            and pod["metadata"]["uid"] != departed_uid
            and pod.get("status", {}).get("phase") == "Running"
            and any(item["type"] == "Ready" and item["status"] == "True"
                    for item in pod["status"].get("conditions", ()))
            for pod in pods
        ) and runtime_reconciled(cluster.resources("deployment", RUNTIME)):
            nodes = {pod["spec"]["nodeName"] for pod in pods}
            assert len(nodes) == 2 and nodes <= eligible, "Runtime pods are not on two eligible worker nodes"
            return sorted(pods, key=lambda pod: pod["metadata"]["name"])
        sleep(0.5)
    pytest.fail("Two cross-node Runtime pods did not become Ready")


def mount_claims(pod):
    volumes = {volume["name"]: volume for volume in pod["spec"]["volumes"]}
    mounts = {mount["name"]: mount for mount in runtime_container(pod)["volumeMounts"]}
    claims = {}
    for name, mount_path in EXPECTED_MOUNTS.items():
        mount = mounts[name]
        assert mount["mountPath"] == mount_path and not mount.get("readOnly")
        assert "subPath" not in mount and "subPathExpr" not in mount
        claims[name] = volumes[name]["persistentVolumeClaim"]["claimName"]
    return claims


def assert_fixed_deployment(cluster, pods, generation):
    deployment = cluster.fixed_runtime_deployment()
    assert runtime_reconciled(deployment)
    assert deployment["metadata"]["generation"] == generation
    for pod in pods:
        environment = {entry["name"]: entry.get("value") for entry in runtime_container(pod)["env"]}
        assert "NEXENT_MAINTENANCE_EPOCH" not in environment
        assert environment["NEXENT_RECOVERY_MODE"] == "fixed_replicas"


class Probe:
    def __init__(self, cluster):
        self.cluster = cluster
        self.source = Path(__file__).with_name("storage_probe.py").read_text(encoding="utf-8")

    def __call__(self, pod, action, role, *arguments):
        management_actions = {"verify-settings", "read-attachment"}
        target = "deployment/nexent-config" if action in management_actions else pod["metadata"]["name"]
        output = self.cluster.run_fixture_python(target, self.source, action, self.cluster.run_id, role, *arguments)
        record, = (line.removeprefix("D3_STORAGE ") for line in output.splitlines() if line.startswith("D3_STORAGE "))
        return json.loads(record)

    def live_attachment(self, pod, role, *arguments):
        identity = {"a": "owner", "b": "foreign"}[role]
        return self(pod, "live-attachment", role, identity, *arguments)


def expected_digest(token, role, stream):
    return hashlib.sha256(f"{token}:{role}:{stream}\n".encode()).hexdigest()


def storage_round_trip(cluster, probe, writer, peer):
    token = cluster.run_id
    record_a = probe(writer, "seed", "a")
    record_b = probe(peer, "seed", "b")
    for local, remote, record, role in ((writer, peer, record_a, "a"), (peer, writer, record_b, "b")):
        assert record == {**{stream: expected_digest(token, role, stream) for stream in ("output", "skills", "plugins")},
                          "keep": expected_digest(token, "a", "non-run"),
                          "settings": {"skill_revision": token, "plugin_revision": token, "plugin_version": "1.0.0"}}
        assert probe(remote, "snapshot", role) == record
        assert probe(local, "upload", role) > 0
        assert probe(remote, "download", role) == record["output"]
    assert probe(writer, "verify-settings", "a") == record_a["settings"]
    return record_a, record_b


def verify_separate_log_rotation(cluster, probe, writer, peer):
    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        issued = [(pod, role, executor.submit(probe, pod, "rotate", role))
                  for pod, role in ((writer, "a"), (peer, "b"))]
        for pod, role, job in issued:
            result = job.result()
            assert result == {
                "directory": f"{EXPECTED_MOUNTS['nexent-logs']}/{pod['metadata']['name']}",
                "rotated": expected_digest(cluster.run_id, role, "before"),
                "current": expected_digest(cluster.run_id, role, "after"),
            }
            results.append({"role": role, **result})
    return results


def exercise_attachment_routes(cluster, probe, writer, peer, restart_writer):
    identities = cluster.seed_runtime_identities(writer)
    gateway_a = cluster.create_runtime_gateway(writer)
    gateway_b = cluster.create_runtime_gateway(peer)
    cluster.create_runtime_model(peer, mode="storage-pair")
    agents = cluster.seed_runtime_agent(peer, storage_pair=True)

    def peer_read(role, user_id, tenant_id, object_name):
        destination = peer if role == "a" else writer
        return probe(destination, "read-attachment", role, user_id, tenant_id, object_name)

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        attachments = verify_authenticated_attachments(url_a, url_b, stable_url, identities, cluster.run_id, peer_read)
        replacement, live = exercise_live_attachment_pair(
            url_a, url_b, stable_url, identities, agents, cluster.run_id,
            control=cluster.runtime_model_control, live_snapshot=lambda role, *args: probe.live_attachment(peer, role, *args),
            restart_writer=restart_writer, pod_names={"a": writer["metadata"]["name"], "b": peer["metadata"]["name"]},
            wait_seconds=cluster.profile.wait_seconds,
        )
        return replacement, attachments, live


def test_runtime_storage_paths_on_separate_workers(isolated_release):
    cluster, script = isolated_release
    deployment = cluster.deploy(script, 2, initial=True)
    if deployment.returncode:
        pytest.fail(f"Two-replica test deployment failed (exit {deployment.returncode})")
    eligible = cluster.spread_runtime_pair()
    writer, peer = ready_pair(cluster, eligible)
    generation = cluster.fixed_runtime_deployment()["metadata"]["generation"]
    assert_fixed_deployment(cluster, (writer, peer), generation)
    claims = mount_claims(writer)
    assert mount_claims(peer) == claims
    volumes = {name: cluster.bound_shared_volume(claim) for name, claim in claims.items()}

    probe = Probe(cluster)
    record_a, record_b = storage_round_trip(cluster, probe, writer, peer)
    logs = verify_separate_log_rotation(cluster, probe, writer, peer)
    assert probe(writer, "finish", "a") is True
    assert probe(peer, "snapshot", "a") == {**record_a, "output": None}
    assert probe(writer, "snapshot", "b") == record_b
    assert probe(peer, "download", "a") == record_a["output"]

    retired_uid = writer["metadata"]["uid"]
    peer_uid = peer["metadata"]["uid"]
    peer_state = container_state(peer)

    def assert_unrelated_storage(pod):
        assert probe(pod, "snapshot", "a") == {**record_a, "output": None}
        assert probe(pod, "snapshot", "b") == record_b

    def restart_writer(active):
        assert_unrelated_storage(peer)
        cluster.restart_owned_runtime_pod(writer)
        after = ready_pair(cluster, eligible, departed_uid=retired_uid, wait_seconds=150)
        assert_fixed_deployment(cluster, after, generation)
        peer_after, = (pod for pod in after if pod["metadata"]["uid"] == peer_uid)
        replacement, = (pod for pod in after if pod["metadata"]["uid"] != peer_uid)
        assert mount_claims(replacement) == claims
        after_state = container_state(peer_after)
        assert after_state["containerID"] == peer_state["containerID"]
        assert after_state["restartCount"] == peer_state["restartCount"]
        assert probe.live_attachment(replacement, "b") == active["b"]
        finished = probe.live_attachment(replacement, "a", active["a"]["run_id"])
        assert finished == {**active["a"], "status": "completed", "run_id": None, "sha256": None,
                            "workspace_exists": False}
        assert_unrelated_storage(replacement)
        return replacement

    replacement, attachments, live = exercise_attachment_routes(cluster, probe, writer, peer, restart_writer)
    assert_unrelated_storage(replacement)
    assert probe(replacement, "download", "b") == record_b["output"]
    assert probe(peer, "finish", "b") is True
    assert probe(replacement, "snapshot", "b") == {**record_b, "output": None}

    write_case_evidence("runtime-shared-storage-paths", {
        "generation": generation, "nodes": [pod["spec"]["nodeName"] for pod in (writer, peer, replacement)],
        "volumes": volumes, "paths": {"a": record_a, "b": record_b}, "log_rotation": logs, "attachments": attachments,
        "surviving_pod_unchanged": True, "live_agents": live,
    })
