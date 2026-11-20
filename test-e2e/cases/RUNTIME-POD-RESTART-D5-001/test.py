# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Test live owner protection and the no-takeover guarantee after owner loss."""

import json
from pathlib import Path

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_admission import wait_for
from shared.runtime_scaling_attachments import sign_in
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_owner_loss import (
    begin_owner_loss, owner_client as client_for, owner_snapshot, verify_after_maintenance, verify_retained_owner,
)
from shared.runtime_scaling_peer_restart import exercise_peer_restart


CASE_ID = "RUNTIME-POD-RESTART-D5-001"
RUN_TTL = 30
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def cluster_profile():
    try:
        return Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc


@pytest.fixture
def isolated_release(cluster_profile):
    with isolated_runtime_release(repo_root(), cluster_profile, separate_workers=True, agent_limit=1,
                                  run_ttl_seconds=RUN_TTL) as release:
        yield release
    write_case_evidence("runtime-owner-loss-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def ready_pair(cluster, eligible):
    pods = cluster.runtime_pods()
    if len(pods) != 2 or any(pod["metadata"].get("deletionTimestamp") or not any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", ())
    ) for pod in pods):
        return None
    nodes = {pod["spec"]["nodeName"] for pod in pods}
    assert len(nodes) == 2 and nodes <= eligible, "The two Ready Runtime Pods must run on separate eligible workers"
    return {pod["metadata"]["uid"]: pod for pod in pods}


def epoch_of(cluster):
    epoch = cluster.resources("deployment", RUNTIME)["metadata"]["annotations"]["nexent.io/maintenance-epoch"]
    assert cluster.committed_maintenance_count(epoch) == 1
    return epoch


def probe_at(cluster, pod, source, prefix, *arguments):
    lines = cluster.run_fixture_python(pod["metadata"]["name"], source, cluster.run_id,
                                      *(str(argument) for argument in arguments)).splitlines()
    record, = (line.removeprefix(prefix) for line in lines if line.startswith(prefix))
    return json.loads(record)


def runtime_container(pod):
    state, = (row for row in pod["status"]["containerStatuses"] if row["name"] == RUNTIME)
    assert state["containerID"] and state["ready"]
    return state["containerID"], state["restartCount"]


def test_restarting_non_owner_preserves_live_chat_evaluation_schedule_and_workspace(cluster_profile):
    with isolated_runtime_release(repo_root(), cluster_profile, separate_workers=True, agent_limit=2,
                                  scheduler_case=True) as (cluster, script):
        assert cluster.deploy(script, 2, initial=True).returncode == 0, "Two-Replica Runtime test deployment failed"
        eligible = cluster.spread_runtime_pair()
        pair = ready_pair(cluster, eligible)
        assert pair
        pods = {pod["metadata"]["name"]: pod for pod in pair.values()}
        nodes = {pod["spec"]["nodeName"] for pod in pair.values()}
        epoch = epoch_of(cluster)
        fixture_pod = next(iter(pair.values()))
        identity = cluster.seed_runtime_identities(fixture_pod)["owner"]
        cluster.create_runtime_model(fixture_pod, mode="stream")
        agent = cluster.seed_runtime_agent(fixture_pod)
        schedule_source = Path(__file__).resolve().parents[1] / "RUNTIME-SCHEDULER-D3-001" / "scheduler_probe.py"
        schedule_source = schedule_source.read_text(encoding="utf-8")
        peer_source = Path(__file__).with_name("peer_restart_probe.py").read_text(encoding="utf-8")

        def schedule(action, identifier, *arguments):
            return probe_at(cluster, next(iter(pods.values())), schedule_source, "SCALING_SCHEDULER ",
                            action, identifier, *arguments)

        def probe(name, action, *arguments):
            return probe_at(cluster, pods[name], peer_source, "SCALING_PEER_RESTART ", action, *arguments)

        def slot_for_owner(lock_owner):
            owner = lock_owner.rsplit("-", 5)[0]
            peer, = pods.keys() - {owner}
            return owner, peer

        def restart_peer(owner, peer):
            owner_pod, peer_pod = pods[owner], pods[peer]
            owner_uid, old_peer_uid = (pod["metadata"]["uid"] for pod in (owner_pod, peer_pod))
            owner_process = runtime_container(owner_pod)
            cluster.restart_owned_runtime_pod(peer_pod)

            def replaced():
                current = ready_pair(cluster, eligible)
                return current if current and old_peer_uid not in current else None

            current = wait_for(replaced, min(cluster_profile.wait_seconds, 120), "Standby Runtime did not restart")
            assert owner_uid in current and runtime_container(current[owner_uid]) == owner_process
            assert epoch_of(cluster) == epoch
            replacement_uid, = current.keys() - {owner_uid}
            replacement = current[replacement_uid]
            assert replacement["spec"]["nodeName"] != owner_pod["spec"]["nodeName"]
            pods.pop(peer)
            pods[replacement["metadata"]["name"]] = replacement
            return replacement["metadata"]["name"], {"owner_pod_uid": owner_uid, "old_peer_pod_uid": old_peer_uid,
                                                    "new_peer_pod_uid": replacement_uid, "epoch": epoch}

        with client_for(cluster) as stable:
            evidence = exercise_peer_restart(
                stable, identity, agent, cluster.run_id, client_for=lambda name: client_for(cluster, pods[name]),
                schedule=schedule, probe=probe, snapshot=lambda name, identifier: owner_snapshot(
                    cluster, pods[name], quota=2, ttl=None,
                )(identifier), slot_for_owner=slot_for_owner, restart_peer=restart_peer,
                control=cluster.runtime_model_control, wait_seconds=60,
            )
    write_case_evidence("runtime-live-peer-restart", {**evidence, "nodes": sorted(nodes), "owned_namespace_removed": True,
                                                      "storage_reclaimed": True})


def test_owner_loss_keeps_reservation_until_full_stop_maintenance(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, 2, initial=True).returncode == 0, "Two-Replica Runtime test deployment failed"
    eligible = cluster.spread_runtime_pair()
    pair = ready_pair(cluster, eligible)
    assert pair
    owner_uid, survivor_uid = sorted(pair)
    owner, survivor = pair[owner_uid], pair[survivor_uid]
    initial_epoch = epoch_of(cluster)
    identity = cluster.seed_runtime_identities(survivor)["owner"]
    cluster.create_runtime_model(survivor, mode="stream")
    agent = cluster.seed_runtime_agent(survivor)
    snapshot = owner_snapshot(cluster, survivor, quota=1, ttl=RUN_TTL)
    control = cluster.runtime_model_control

    with client_for(cluster) as stable, client_for(cluster, owner) as producer, client_for(cluster, survivor) as peer:
        auth = sign_in(stable, identity)
        loss = begin_owner_loss(
            stable, producer, auth, agent, cluster.run_id, epoch=initial_epoch, snapshot=snapshot, control=control,
            crash=lambda: cluster.restart_owned_runtime_pod(owner, interrupt=True),
            expected_host=owner["metadata"]["name"],
        )

        def owner_replaced():
            current = ready_pair(cluster, eligible)
            if not current or owner_uid in current:
                return None
            assert survivor_uid in current, "The other Runtime Pod must not restart during owner loss"
            return current

        after_loss = wait_for(owner_replaced, cluster.profile.wait_seconds, "Replacement Runtime did not become Ready")
        replacement_uid, = after_loss.keys() - {survivor_uid}
        assert epoch_of(cluster) == initial_epoch
        with client_for(cluster, after_loss[replacement_uid]) as replacement:
            retained = verify_retained_owner(peer, replacement, auth, agent, cluster.run_id, loss,
                                             snapshot=snapshot, control=control, wait_seconds=60)

    assert control("release/lost-owner")["released"] is True
    assert cluster.deploy(script, 2).returncode == 0, "Full-stop Runtime maintenance failed"
    new_epoch = epoch_of(cluster)
    assert new_epoch != initial_epoch
    eligible = cluster.spread_runtime_pair()
    reactivated = ready_pair(cluster, eligible)
    assert reactivated and not (reactivated.keys() & after_loss.keys())
    surviving_after_maintenance = next(iter(reactivated.values()))
    with client_for(cluster) as stable:
        recovered = verify_after_maintenance(stable, sign_in(stable, identity), agent, cluster.run_id, loss,
                                             epoch=new_epoch, snapshot=owner_snapshot(
                                                 cluster, surviving_after_maintenance, quota=1, ttl=RUN_TTL,
                                             ),
                                             control=control, wait_seconds=60)
    write_case_evidence("runtime-owner-loss", {
        **retained, **recovered, "initial_epoch": initial_epoch, "new_epoch": new_epoch,
        "old_owner_pod": owner_uid, "replacement_pod": replacement_uid, "unrestarted_peer": survivor_uid,
    })
