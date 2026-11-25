# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify disconnected Agent replay and stopping with two Runtime Pods."""

import json
from pathlib import Path

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_live_run import exercise_live_attachment_run
from shared.runtime_scaling_owner_loss import owner_snapshot
from shared.runtime_scaling_public_stream import exercise_public_stream_control
from shared.runtime_scaling_stream import exercise_stream_control
from shared.runtime_scaling_voice import exercise_public_voice


CASE_ID = "RUNTIME-STREAM-CONTROL-D3-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D3"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release(request):
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, separate_workers=True) as release:
        yield release
    write_case_evidence(f"{request.node.name}-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def deploy_runtime_pair(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, 2, initial=True).returncode == 0, "Two-Replica Runtime test deployment failed"
    eligible = cluster.spread_runtime_pair()
    pod_a, pod_b = sorted(cluster.runtime_pods(), key=lambda pod: pod["metadata"]["name"])
    names = [pod["metadata"]["name"] for pod in (pod_a, pod_b)]
    nodes = {pod["spec"]["nodeName"] for pod in (pod_a, pod_b)}
    assert len(set(names)) == len(nodes) == 2 and nodes <= eligible
    generation = cluster.fixed_runtime_deployment()["metadata"]["generation"]
    return cluster, (pod_a, pod_b), {
        "generation": generation, "nodes": sorted(nodes), "producer_pod": names[0], "control_pod": names[1],
    }


def prepare_stream_pair(isolated_release, *, model_mode="stream"):
    cluster, (pod_a, pod_b), deployment = deploy_runtime_pair(isolated_release)
    identities = cluster.seed_runtime_identities(pod_a)
    cluster.create_runtime_model(pod_a, mode=model_mode)
    agent = cluster.seed_runtime_agent(pod_a)

    def probe(source, prefix, *args):
        target = "deployment/nexent-config" if source.name == "public_identity_probe.py" else deployment["control_pod"]
        lines = cluster.run_fixture_python(target, source.read_text(encoding="utf-8"), cluster.run_id, *args).splitlines()
        record, = (line.removeprefix(prefix) for line in lines if line.startswith(prefix))
        return json.loads(record)

    def stream_probe(action, identifier, *generations):
        return probe(Path(__file__).with_name("stream_probe.py"), "SCALING_STREAM ", action, str(identifier), *generations)

    return cluster, (pod_a, pod_b), identities, agent, probe, stream_probe, deployment


def test_cross_pod_agent_replay_and_stop(isolated_release):
    cluster, pods, identities, agent, _, stream_probe, deployment = prepare_stream_pair(isolated_release)
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in pods]
    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        evidence = exercise_stream_control(url_a, url_b, stable_url, identities, agent, cluster.run_id,
                                           control=cluster.runtime_model_control, stream_probe=stream_probe,
                                           wait_seconds=cluster.profile.wait_seconds)
    write_case_evidence("runtime-cross-pod-agent-replay-stop", {**evidence, **deployment})


def test_public_web_and_northbound_replay_and_stop(isolated_release):
    cluster, pods, identities, agent, probe, stream_probe, deployment = prepare_stream_pair(isolated_release)
    cases = Path(__file__).resolve().parents[1]
    credentials = probe(cases / "RUNTIME-ADMISSION-D2-001/public_identity_probe.py", "SCALING_PUBLIC_IDENTITIES ")
    snapshot = owner_snapshot(cluster, pods[1])

    with (cluster.route_runtime_through_transport_fixture(*pods, mode="stream-control") as origins,
          cluster.web_http() as web, cluster.gateway_http() as gateway):
        evidence = exercise_public_stream_control(
            web, gateway, identities["owner"], credentials["api_keys"]["owner"], agent, cluster.run_id,
            control=cluster.runtime_model_control, transport=cluster.runtime_transport_control,
            stream_probe=stream_probe, snapshot=snapshot, origins=origins,
            wait_seconds=min(cluster.profile.wait_seconds, 60),
        )
    write_case_evidence("runtime-public-replay-stop", {
        **evidence, **deployment, "original_service_targets_restored": True,
    })


def test_cross_pod_attachment_run_keeps_access_scoped(isolated_release):
    cluster, pods, identities, agent, _, _, deployment = prepare_stream_pair(isolated_release, model_mode="storage")
    writer, peer = pods
    gateway_a, gateway_b = [cluster.create_runtime_gateway(pod) for pod in pods]
    cases = Path(__file__).resolve().parents[1]
    source = (cases / "RUNTIME-SHARED-STORAGE-D3-001/storage_probe.py").read_text(encoding="utf-8")

    def snapshot():
        prefix = "D3_STORAGE "
        output = cluster.run_fixture_python(peer["metadata"]["name"], source, "live-attachment", cluster.run_id, "b")
        record, = (line.removeprefix(prefix) for line in output.splitlines() if line.startswith(prefix))
        return json.loads(record)

    with (cluster.gateway_http(gateway_a) as url_a, cluster.gateway_http(gateway_b) as url_b,
          cluster.gateway_http() as stable_url):
        _, evidence = exercise_live_attachment_run(
            url_a, url_b, stable_url, identities, agent, cluster.run_id, control=cluster.runtime_model_control,
            live_snapshot=snapshot, peer_name=peer["metadata"]["name"], wait_seconds=cluster.profile.wait_seconds,
        )
    write_case_evidence("runtime-cross-pod-attachment-access", {
        **evidence, "generation": deployment["generation"], "nodes": deployment["nodes"],
        "writer_pod": writer["metadata"]["name"], "consumer_pod": peer["metadata"]["name"],
    })


def test_public_voice_websocket_reconnects_as_new_runtime_session(isolated_release):
    cluster, pods, deployment = deploy_runtime_pair(isolated_release)
    identity = cluster.seed_runtime_identities(pods[0])["owner"]
    with (cluster.route_runtime_through_transport_fixture(*pods, mode="voice") as origins,
          cluster.web_http() as web, cluster.gateway_http() as gateway):
        evidence = exercise_public_voice(web, gateway, f"ws://{RUNTIME}:5014", identity, cluster.run_id,
                                         transport=cluster.runtime_transport_control, origins=origins,
                                         wait_seconds=min(cluster.profile.wait_seconds, 45), assert_pod_ips=True)
    write_case_evidence("runtime-public-voice-sessions", {
        **evidence, **deployment, "original_service_targets_restored": True,
    })
