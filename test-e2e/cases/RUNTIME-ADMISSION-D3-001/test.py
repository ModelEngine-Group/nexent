# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify admission contention and quota using the actual two Runtime Pods."""

import json
from pathlib import Path

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_admission import exercise_admission_race
from shared.runtime_scaling_creator_admission import exercise_creator_admission
from shared.runtime_scaling_evaluation_admission import exercise_evaluation_admission, exercise_evaluation_submission
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_northbound_admission import exercise_northbound_admission
from shared.runtime_scaling_public_admission import (
    exercise_agent_backlog, exercise_agent_preparation_failure, exercise_peer_coordination_recovery,
)
from shared.runtime_scaling_workbench_admission import exercise_workbench_admission


CASE_ID = "RUNTIME-ADMISSION-D3-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D3"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release(request):
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, separate_workers=True, agent_limit=2,
                                  agent_lane_queue_size=getattr(request, "param", None)) as release:
        yield release
    receipts = {"test_agent_backlog_stays_on_origin_when_peer_accepts": "runtime-agent-backlog-cleanup",
                "test_agent_coordination_faults_do_not_mutate_peer": "runtime-agent-coordination-faults-cleanup",
                "test_workbench_cross_pod_conflict_and_tenant_quota": "runtime-workbench-admission-cleanup",
                "test_northbound_cross_pod_conflict_and_quota": "runtime-northbound-admission-cleanup",
                "test_evaluation_cross_pod_claim_and_rollback": "runtime-evaluation-admission-cleanup",
                "test_evaluation_submission_capacity_rejects_only_on_full_pod": "runtime-evaluation-submission-cleanup"}
    if request.node.originalname == "test_creator_cross_pod_conflict_and_preparing_quota":
        kind = request.node.callspec.params["kind"]
        receipt = f"runtime-creator-{kind}-admission-cleanup"
    elif request.node.originalname == "test_agent_failed_preparation_releases_shared_quota":
        receipt = f"runtime-agent-{request.node.callspec.params['fault_kind']}-failure-cleanup"
    else:
        receipt = receipts.get(request.node.originalname, "runtime-admission-cleanup")
    write_case_evidence(receipt, {"owned_namespace_removed": True, "storage_reclaimed": True})


def deploy_admission_pair(isolated_release):
    cluster, script = isolated_release
    deployed = cluster.deploy(script, 2, initial=True)
    assert deployed.returncode == 0, "Two-Replica Runtime test deployment failed"
    eligible = cluster.spread_runtime_pair()
    pod_a, pod_b = sorted(cluster.runtime_pods(), key=lambda pod: pod["metadata"]["name"])
    names = {tag: pod["metadata"]["name"] for tag, pod in (("race-a", pod_a), ("race-b", pod_b))}
    nodes = {pod["spec"]["nodeName"] for pod in (pod_a, pod_b)}
    assert len(set(names.values())) == len(nodes) == 2 and nodes <= eligible
    epoch = cluster.resources("deployment", RUNTIME)["metadata"]["annotations"]["nexent.io/maintenance-epoch"]
    assert cluster.committed_maintenance_count(epoch) == 1
    return cluster, pod_a, pod_b, names, nodes, epoch


def call_admission_probe(cluster, pod, *arguments):
    source = Path(__file__).with_name("admission_probe.py").read_text(encoding="utf-8")
    lines = cluster.run_fixture_python(pod, source, cluster.run_id, *arguments).splitlines()
    record, = (line.removeprefix("SCALING_ADMISSION ") for line in lines if line.startswith("SCALING_ADMISSION "))
    return json.loads(record)


def read_snapshot(cluster, pod, role, identifiers):
    options = ("--foreign",) if role == "foreign" else ()
    return call_admission_probe(cluster, pod, *options, *(str(identifier) for identifier in identifiers))


def test_agent_cross_pod_conflict_and_quota(isolated_release):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)

    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="admission")
    agent = cluster.seed_runtime_agent(pod_a, other_scope=True)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]

    def snapshot(*identifiers):
        return read_snapshot(cluster, names["race-a"], "owner", identifiers)

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_admission_race(url_a, url_b, stable_url, identities["owner"], agent, cluster.run_id,
                                           control=cluster.runtime_model_control, snapshot=snapshot,
                                           wait_seconds=cluster.profile.wait_seconds, expected_hosts=names)
    write_case_evidence("runtime-ordinary-agent-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


@pytest.mark.parametrize("isolated_release", [1], indirect=True)
def test_agent_backlog_stays_on_origin_when_peer_accepts(isolated_release):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a, other_scope=True)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]

    def snapshot(*identifiers):
        return read_snapshot(cluster, names["race-a"], "owner", identifiers)

    def capacity(slot):
        return call_admission_probe(cluster, names[f"race-{slot}"], "--agent-lane")

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_agent_backlog(url_a, url_b, stable_url, identities["owner"], agent, cluster.run_id,
                                          control=cluster.runtime_model_control, snapshot=snapshot, capacity=capacity,
                                          wait_seconds=cluster.profile.wait_seconds,
                                          expected_hosts=(names["race-a"], names["race-b"]))
    write_case_evidence("runtime-agent-backlog", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def test_agent_coordination_faults_do_not_mutate_peer(isolated_release):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]
    probe_path = Path(__file__).resolve().parents[1] / "RUNTIME-ADMISSION-D2-001" / "coordination_fault_probe.py"
    source = probe_path.read_text(encoding="utf-8")

    def snapshot(*identifiers):
        return read_snapshot(cluster, names["race-b"], "owner", identifiers)

    def fault_probe(action, identifier):
        lines = cluster.run_fixture_python(names["race-b"], source, cluster.run_id, action, str(identifier)).splitlines()
        prefix = "SCALING_COORDINATION_FAULT "
        record, = (line.removeprefix(prefix) for line in lines if line.startswith(prefix))
        return json.loads(record)

    def capacity(slot):
        return call_admission_probe(cluster, names[f"race-{slot}"], "--agent-lane")

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_peer_coordination_recovery(
            url_a, url_b, stable_url, identities["owner"], agent, cluster.run_id,
            control=cluster.runtime_model_control, snapshot=snapshot, capacity=capacity, fault_probe=fault_probe,
            wait_seconds=cluster.profile.wait_seconds, expected_hosts=(names["race-a"], names["race-b"]),
        )
    write_case_evidence("runtime-agent-coordination-faults", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


@pytest.mark.parametrize("fault_kind", ["message-write", "stream-reset"])
def test_agent_failed_preparation_releases_shared_quota(isolated_release, fault_kind):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]

    def snapshot(*identifiers):
        return read_snapshot(cluster, names["race-b"], "owner", identifiers)

    def fault_probe(action, identifier):
        option = {"message-write": "--user-message-fault", "stream-reset": "--stream-reset-fault"}[fault_kind]
        return call_admission_probe(cluster, names["race-b"], option, action, str(identifier))

    def capacity(slot):
        return call_admission_probe(cluster, names[f"race-{slot}"], "--agent-lane")

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_agent_preparation_failure(
            url_a, url_b, stable_url, identities["owner"], agent, cluster.run_id,
            control=cluster.runtime_model_control, snapshot=snapshot, capacity=capacity, fault_probe=fault_probe,
            fault_kind=fault_kind,
            wait_seconds=cluster.profile.wait_seconds, expected_hosts=(names["race-a"], names["race-b"]),
        )
    write_case_evidence(f"runtime-agent-{fault_kind}-failure", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def test_workbench_cross_pod_conflict_and_tenant_quota(isolated_release):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    prepared = cluster.seed_runtime_workbench(pod_a)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]

    def snapshot(role, *identifiers):
        return read_snapshot(cluster, names["race-a"], role, identifiers)

    def gate(action, identifier):
        return call_admission_probe(cluster, names["race-a"], "--workbench-finalization", action, str(identifier))

    def replay_completion(slot, identifier, execution_id):
        return call_admission_probe(cluster, names[slot], "--workbench-replay-completion", str(identifier), str(execution_id))

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_workbench_admission(url_a, url_b, stable_url, identities, prepared, cluster.run_id,
                                                control=cluster.runtime_model_control, snapshot=snapshot, gate=gate,
                                                replay_completion=replay_completion,
                                                wait_seconds=cluster.profile.wait_seconds, expected_hosts=names)
    write_case_evidence("runtime-workbench-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def test_northbound_cross_pod_conflict_and_quota(isolated_release):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identity = cluster.seed_runtime_identities(pod_a)["owner"]
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a)
    source = Path(__file__).resolve().parents[1] / "RUNTIME-ADMISSION-D2-001" / "public_identity_probe.py"
    lines = cluster.run_fixture_python(names["race-a"], source.read_text(encoding="utf-8"), cluster.run_id).splitlines()
    credentials, = (line.removeprefix("SCALING_PUBLIC_IDENTITIES ") for line in lines
                    if line.startswith("SCALING_PUBLIC_IDENTITIES "))
    api_key = json.loads(credentials)["api_keys"]["owner"]

    def snapshot(*identifiers):
        return read_snapshot(cluster, names["race-a"], "owner", identifiers)

    with (cluster.route_runtime_through_transport_fixture(pod_a, pod_b, mode="northbound-admission") as origins,
          cluster.gateway_http() as stable_url):
        evidence = exercise_northbound_admission(
            stable_url, identity, api_key, agent, cluster.run_id, control=cluster.runtime_model_control,
            snapshot=snapshot, transport=cluster.runtime_transport_control, origins=origins,
            wait_seconds=cluster.profile.wait_seconds, expected_hosts={"a": names["race-a"], "b": names["race-b"]},
        )
    write_case_evidence("runtime-northbound-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def evaluation_probe(cluster, owners):
    probe_path = Path(__file__).resolve().parents[1] / "RUNTIME-POD-RESTART-D5-001" / "peer_restart_probe.py"
    source = probe_path.read_text(encoding="utf-8")
    def probe(slot, action, *arguments):
        args = (cluster.run_id, action, *(str(value) for value in arguments))
        lines = cluster.run_fixture_python(owners[slot], source, *args).splitlines()
        record, = (line.removeprefix("SCALING_PEER_RESTART ") for line in lines
                   if line.startswith("SCALING_PEER_RESTART "))
        return json.loads(record)

    return probe


def test_evaluation_cross_pod_claim_and_rollback(isolated_release):
    cluster, pod_a, _, names, nodes, epoch = deploy_admission_pair(isolated_release)
    cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a)
    owners = {side: names[f"race-{side}"] for side in ("a", "b")}
    probe = evaluation_probe(cluster, owners)
    evidence = exercise_evaluation_admission(agent, probe=probe, control=cluster.runtime_model_control,
                                             wait_seconds=cluster.profile.wait_seconds, expected_owners=owners)
    write_case_evidence("runtime-evaluation-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def test_evaluation_submission_capacity_rejects_only_on_full_pod(isolated_release):
    cluster, pod_a, _, names, nodes, epoch = deploy_admission_pair(isolated_release)
    cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode="stream")
    agent = cluster.seed_runtime_agent(pod_a)
    owners = {side: names[f"race-{side}"] for side in ("a", "b")}
    evidence = exercise_evaluation_submission(
        agent, probe=evaluation_probe(cluster, owners), control=cluster.runtime_model_control,
        wait_seconds=cluster.profile.wait_seconds, expected_owners=owners,
    )
    write_case_evidence("runtime-evaluation-submission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


@pytest.mark.parametrize("kind", ["agent", "skill"])
def test_creator_cross_pod_conflict_and_preparing_quota(isolated_release, kind):
    cluster, pod_a, pod_b, names, nodes, epoch = deploy_admission_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a, creator=True)
    cluster.create_runtime_model(pod_a, mode="stream")
    prepared = cluster.seed_runtime_creators(pod_a, kind)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in (pod_a, pod_b)]
    owners = {side: names[f"race-{side}"] for side in ("a", "b")}

    def snapshot(role, *identifiers):
        return read_snapshot(cluster, owners["a"], role, identifiers)

    def gate(action, identifier):
        return call_admission_probe(cluster, owners["a"], "--creator-preparation", action, str(identifier))

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_creator_admission(
            {"a": url_a, "b": url_b}, stable_url, identities, prepared, cluster.run_id, kind,
            control=cluster.runtime_model_control, snapshot=snapshot, gate=gate,
            wait_seconds=cluster.profile.wait_seconds, expected_owners=owners,
        )
    write_case_evidence(f"runtime-creator-{kind}-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})
