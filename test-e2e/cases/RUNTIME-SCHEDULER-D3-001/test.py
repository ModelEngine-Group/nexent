# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify scheduler lease survival and bidirectional manual/automatic exclusion."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_admission import wait_for
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_scheduler import exercise_scheduler


CASE_ID = "RUNTIME-SCHEDULER-D3-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D3"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release():
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, separate_workers=True, agent_limit=2,
                                  scheduler_case=True) as release:
        yield release
    write_case_evidence("runtime-scheduler-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def test_scheduler_reservation_and_peer_restart(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, 2, initial=True).returncode == 0, "Two-Replica Runtime deployment failed"
    eligible = cluster.spread_runtime_pair()
    pods = {pod["metadata"]["name"]: pod for pod in cluster.runtime_pods()}
    nodes = {pod["spec"]["nodeName"] for pod in pods.values()}
    assert len(pods) == len(nodes) == 2 and nodes <= eligible
    generation = cluster.fixed_runtime_deployment()["metadata"]["generation"]
    probe_pod = next(iter(pods))
    identities = cluster.seed_runtime_identities(pods[probe_pod])
    cluster.create_runtime_model(pods[probe_pod], mode="scheduler")
    agent = cluster.seed_runtime_agent(pods[probe_pod])
    gateways = {name: cluster.create_runtime_gateway(pod, scheduler=True) for name, pod in pods.items()}
    source = Path(__file__).with_name("scheduler_probe.py").read_text(encoding="utf-8")

    def probe_on(pod_name, action, identifier, *arguments):
        lines = cluster.run_fixture_python(gateways[pod_name], source, cluster.run_id, action, str(identifier),
                                          *(str(value) for value in arguments), container="nexent-config").splitlines()
        record, = (line.removeprefix("SCALING_SCHEDULER ") for line in lines if line.startswith("SCALING_SCHEDULER "))
        return json.loads(record)

    def probe(action, identifier, *arguments):
        return probe_on(probe_pod, action, identifier, *arguments)

    def contest(identifier):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(probe_on, pod_name, "compete", identifier, actor)
                       for pod_name, actor in zip(sorted(pods), ("first", "second"), strict=True)]
            return [result.result() for result in results]

    def slot_for_owner(owner):
        name = owner.rsplit("-", 5)[0]
        runtime, = (runtime for runtime, gateway in gateways.items() if gateway == name)
        return runtime

    def restart_peer(peer):
        nonlocal probe_pod
        retired_uid = pods[peer]["metadata"]["uid"]
        owner_pod, = (pod for name, pod in pods.items() if name != peer)
        owner_uid = owner_pod["metadata"]["uid"]
        cluster.remove_runtime_gateway(gateways.pop(peer))
        cluster.restart_owned_runtime_pod(pods[peer])

        def replacements():
            current = cluster.runtime_pods()
            uids = {pod["metadata"]["uid"] for pod in current}
            if len(current) != 2 or retired_uid in uids or owner_uid not in uids:
                return None
            if not all(not pod["metadata"].get("deletionTimestamp") and any(
                entry["type"] == "Ready" and entry["status"] == "True"
                for entry in pod["status"].get("conditions", ())
            ) for pod in current):
                return None
            return current

        ready = wait_for(replacements, min(cluster.profile.wait_seconds, 120), "Non-owner Runtime did not restart")
        assert {pod["spec"]["nodeName"] for pod in ready} == nodes
        owner_after, = (pod for pod in ready if pod["metadata"]["uid"] == owner_uid)
        owner_before_state, = owner_pod["status"]["containerStatuses"]
        owner_after_state, = owner_after["status"]["containerStatuses"]
        assert (owner_after_state["containerID"], owner_after_state["restartCount"]) == (
            owner_before_state["containerID"], owner_before_state["restartCount"],
        )
        replacement, = (pod for pod in ready if pod["metadata"]["uid"] != owner_uid)
        probe_pod = replacement["metadata"]["name"]
        pods.pop(peer)
        pods[probe_pod] = replacement
        gateways[probe_pod] = cluster.create_runtime_gateway(replacement, scheduler=True)
        assert cluster.fixed_runtime_deployment()["metadata"]["generation"] == generation
        return {"retired_uid": retired_uid, "replacement_uid": replacement["metadata"]["uid"],
                "scheduler_slot": probe_pod}

    names = list(gateways)
    with (cluster.gateway_http(gateways[names[0]]) as first, cluster.gateway_http(gateways[names[1]]) as second,
          cluster.gateway_http() as stable):
        evidence = exercise_scheduler(dict(zip(names, (first, second))), stable, identities["owner"], agent,
                                      cluster.run_id, control=cluster.runtime_model_control, probe=probe, contest=contest,
                                      slot_for_owner=slot_for_owner, restart_peer=restart_peer,
                                      wait_seconds=cluster.profile.wait_seconds)
    write_case_evidence("runtime-scheduler-lease-and-exclusion", {**evidence, "generation": generation, "nodes": sorted(nodes)})
