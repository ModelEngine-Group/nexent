# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check public HTTP/SSE compatibility through the deployed Web and Gateway Services."""

import json
from pathlib import Path

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_public_admission import (
    exercise_local_lane,
    exercise_public_admission,
    exercise_public_transport_failure,
)


CASE_ID = "RUNTIME-ADMISSION-D2-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D2"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release(request):
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    single_lane = getattr(request, "param", False)
    with isolated_runtime_release(repo_root(), profile, separate_workers=True, agent_limit=1,
                                  agent_lane_queue_size=0 if single_lane else None) as release:
        yield release
    name = "runtime-local-lane-cleanup" if single_lane else "runtime-public-admission-cleanup"
    if request.node.originalname == "test_public_proxies_do_not_retry_an_admitted_post_after_transport_failure":
        name = "runtime-public-transport-cleanup"
    write_case_evidence(name, {"owned_namespace_removed": True, "storage_reclaimed": True})


def deploy_pair(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, 2, initial=True).returncode == 0, "Two-Replica Runtime test deployment failed"
    eligible = cluster.spread_runtime_pair()
    pods = sorted(cluster.runtime_pods(), key=lambda pod: pod["metadata"]["name"])
    nodes = {pod["spec"]["nodeName"] for pod in pods}
    names = {pod["metadata"]["name"] for pod in pods}
    assert len(pods) == len(nodes) == 2 and nodes <= eligible
    epoch = cluster.resources("deployment", RUNTIME)["metadata"]["annotations"]["nexent.io/maintenance-epoch"]
    assert cluster.committed_maintenance_count(epoch) == 1
    return cluster, pods, names, nodes, epoch


def admission_probes(cluster, pod):
    def probe(source, prefix, *args):
        lines = cluster.run_fixture_python(pod["metadata"]["name"], source.read_text(encoding="utf-8"),
                                          cluster.run_id, *args).splitlines()
        record, = (line.removeprefix(prefix) for line in lines if line.startswith(prefix))
        return json.loads(record)

    snapshot_source = Path(__file__).resolve().parents[1] / "RUNTIME-ADMISSION-D3-001" / "admission_probe.py"

    def snapshot(*identifiers):
        return probe(snapshot_source, "SCALING_ADMISSION ", *(str(identifier) for identifier in identifiers))

    return probe, snapshot


def test_public_web_and_northbound_admission(isolated_release):
    cluster, pods, names, nodes, epoch = deploy_pair(isolated_release)
    probe_pod = pods[0]
    identities = cluster.seed_runtime_identities(probe_pod)
    cluster.create_runtime_model(probe_pod, mode="stream")
    agent = cluster.seed_runtime_agent(probe_pod, other_scope=True)
    probe, snapshot = admission_probes(cluster, probe_pod)
    credentials = probe(Path(__file__).with_name("public_identity_probe.py"), "SCALING_PUBLIC_IDENTITIES ")
    identities["peer"] = credentials["peer"]
    fault_source = Path(__file__).with_name("coordination_fault_probe.py")

    def fault(action, identifier):
        return probe(fault_source, "SCALING_COORDINATION_FAULT ", action, str(identifier))

    with cluster.web_http() as web, cluster.gateway_http() as gateway:
        evidence = exercise_public_admission(web, gateway, identities, credentials["api_keys"], agent, cluster.run_id,
                                             control=cluster.runtime_model_control, snapshot=snapshot, fault_probe=fault,
                                             wait_seconds=cluster.profile.wait_seconds, expected_hosts=names)
    write_case_evidence("runtime-public-admission", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})


def test_public_proxies_do_not_retry_an_admitted_post_after_transport_failure(isolated_release):
    cluster, pods, _, nodes, epoch = deploy_pair(isolated_release)
    first, peer = pods
    identity = cluster.seed_runtime_identities(first)["owner"]
    cluster.create_runtime_model(first, mode="stream")
    agent = cluster.seed_runtime_agent(first)
    probe, snapshot = admission_probes(cluster, first)
    credentials = probe(Path(__file__).with_name("public_identity_probe.py"), "SCALING_PUBLIC_IDENTITIES ")
    pod_names = tuple(pod["metadata"]["name"] for pod in pods)
    with (cluster.route_runtime_through_transport_fixture(first, peer), cluster.web_http() as web,
          cluster.gateway_http() as gateway):
        evidence = exercise_public_transport_failure(
            web, gateway, identity, credentials["api_keys"]["owner"], agent, cluster.run_id,
            transport=cluster.runtime_transport_control, control=cluster.runtime_model_control, snapshot=snapshot,
            wait_seconds=min(cluster.profile.wait_seconds, 60), expected_hosts=pod_names,
        )
    write_case_evidence("runtime-public-transport-failure", {
        **evidence, "epoch": epoch, "nodes": sorted(nodes), "original_service_targets_restored": True,
    })


@pytest.mark.parametrize("isolated_release", [True], indirect=True)
def test_local_lane_rejects_without_consuming_peer_capacity(isolated_release):
    cluster, pods, _, nodes, epoch = deploy_pair(isolated_release)
    first, peer = pods
    identities = cluster.seed_runtime_identities(first)
    cluster.create_runtime_model(first, mode="stream")
    agent = cluster.seed_runtime_agent(first, other_scope=True)
    _, snapshot = admission_probes(cluster, first)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in pods]
    pod_names = tuple(pod["metadata"]["name"] for pod in (first, peer))
    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable):
        evidence = exercise_local_lane(url_a, url_b, stable, identities["owner"], agent, cluster.run_id,
                                       control=cluster.runtime_model_control, snapshot=snapshot,
                                       wait_seconds=cluster.profile.wait_seconds, expected_hosts=pod_names)
    write_case_evidence("runtime-local-lane", {**evidence, "epoch": epoch, "nodes": sorted(nodes)})
