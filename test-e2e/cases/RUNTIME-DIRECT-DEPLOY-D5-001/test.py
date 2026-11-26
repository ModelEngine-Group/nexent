# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify replica-only direct upgrades on an isolated Kubernetes release."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root, test_root
from shared.runtime_scaling_admission import assert_completed, marker, new_conversations, post_agent, wait_for
from shared.runtime_scaling_attachments import sign_in
from shared.runtime_scaling_k8s import RUNTIME, Profile, isolated_runtime_release
from shared.runtime_scaling_owner_loss import owner_client
from shared.runtime_scaling_stream import conversation_history


CASE_ID = "RUNTIME-DIRECT-DEPLOY-D5-001"
APPLICATION_SERVICES = {
    "nexent-config", "nexent-data-process", "nexent-gateway", "nexent-mcp", "nexent-ops", "nexent-web",
}
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.p0, pytest.mark.deploy]


@pytest.fixture
def isolated_release():
    try:
        profile = Profile.load(test_root() / "config/runtime-scaling-k8s.yaml")
    except (OSError, RuntimeError) as exc:
        raise AssetDependencyError("deployment", "runtime_scaling_k8s", CASE_ID, detail=str(exc)) from exc
    with isolated_runtime_release(repo_root(), profile, agent_limit=1) as release:
        yield release
    write_case_evidence("runtime-direct-cleanup", {"owned_namespace_removed": True, "storage_reclaimed": True})


def observe_ready_release(cluster, count):
    runtime = cluster.fixed_runtime_deployment()
    status = runtime["status"]
    assert runtime["metadata"]["generation"] == status["observedGeneration"]
    assert runtime["spec"]["replicas"] == status["readyReplicas"] == status["availableReplicas"] == count

    applications = APPLICATION_SERVICES | {"nexent-northbound", RUNTIME}
    runtime_uids = []
    other_uids = {}
    for pod in cluster.resources("pods")["items"]:
        metadata = pod["metadata"]
        application = metadata.get("labels", {}).get("app")
        if application not in applications:
            continue
        assert not metadata.get("deletionTimestamp") or application == RUNTIME
        if application == RUNTIME:
            if not metadata.get("deletionTimestamp"):
                assert any(condition["type"] == "Ready" and condition["status"] == "True"
                           for condition in pod.get("status", {}).get("conditions", ()))
                runtime_uids.append(metadata["uid"])
        else:
            other_uids.setdefault(application, []).append(metadata["uid"])
    assert len(runtime_uids) == count
    assert APPLICATION_SERVICES <= other_uids.keys()
    jobs = cluster.resources("jobs", "-l", "app=nexent-system-bootstrap")["items"]
    return {
        "runtime_uids": sorted(runtime_uids),
        "other_uids": {application: sorted(uids) for application, uids in other_uids.items()},
        "bootstrap_uids": sorted(job["metadata"]["uid"] for job in jobs),
        "ready": count,
    }


def complete_chat(cluster, gateway, auth, agent, tag):
    conversation, = new_conversations(gateway, auth, 1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(post_agent, gateway, auth, agent, cluster.run_id, conversation, tag)
        try:
            wait_for(lambda: cluster.runtime_model_control("probe")["calls_by_tag"].get(tag) == 1,
                     60, "The requested chat never reached the owned model")
        finally:
            cluster.runtime_model_control("release")
        assert_completed(response.result(timeout=60), conversation, tag)

    def persisted():
        history = conversation_history(gateway, auth, conversation)
        messages = history["message"]
        if [message["role"] for message in messages] != ["user", "assistant"] or messages[1]["status"] != "completed":
            return None
        user, assistant = messages
        assert marker(cluster.run_id, tag) in json.dumps(user, ensure_ascii=False)
        assert f"runtime-admitted:{tag}" in json.dumps(assistant, ensure_ascii=False)
        return history

    return conversation, wait_for(persisted, 45, "The chat history never reached a persisted terminal")


def test_direct_upgrade_retains_pods_and_conversations(isolated_release):
    cluster, script = isolated_release
    assert cluster.deploy(script, 3, initial=True).returncode == 0
    baseline = observe_ready_release(cluster, 3)

    pod = cluster.runtime_pods()[0]
    identity = cluster.seed_runtime_identities(pod)["owner"]
    cluster.create_runtime_model(pod, mode="admission")
    agent = cluster.seed_runtime_agent(pod)
    config = {"agent_id": agent["agent_id"], "model_id": agent["model_id"]}
    with owner_client(cluster) as gateway:
        auth = sign_in(gateway, identity)
        original, original_history = complete_chat(cluster, gateway, auth, config, "direct-before")

    previous = baseline
    transitions = []
    for count in (4, 3):
        with TemporaryDirectory(prefix="direct-upgrade-", dir=cluster.scratch) as temporary:
            gate = Path(temporary)
            for tool in ("helm", "kubectl"):
                wrapper = gate / tool
                shutil.copyfile(Path(__file__).with_name("observe-upgrade.sh"), wrapper)
                wrapper.chmod(0o700)
            upgraded = cluster.deploy(script, count, direct=True, helm_gate=gate, kubectl_gate=gate)
            assert upgraded.returncode == 0, upgraded.stderr
            assert (gate / "application-upgrades").read_text(encoding="utf-8").splitlines() == [str(count)]
            assert not (gate / "forbidden-scale").exists()

        after = observe_ready_release(cluster, count)
        assert after["other_uids"] == baseline["other_uids"]
        assert set(after["bootstrap_uids"]) <= set(previous["bootstrap_uids"])
        previous_runtime = set(previous["runtime_uids"])
        current_runtime = set(after["runtime_uids"])
        if count == 4:
            assert previous_runtime < current_runtime
        else:
            assert current_runtime < previous_runtime

        with owner_client(cluster) as gateway:
            auth = sign_in(gateway, identity)
            assert conversation_history(gateway, auth, original) == original_history
            conversation, _ = complete_chat(cluster, gateway, auth, config, f"direct-after-{count}")
        transitions.append({"target": count, "after": after, "new_conversation_id": conversation})
        previous = after

    assert cluster.runtime_model_control("probe")["calls_by_tag"] == {
        "direct-before": 1, "direct-after-4": 1, "direct-after-3": 1,
    }
    write_case_evidence("runtime-direct-upgrade", {
        "baseline": baseline, "original_conversation_id": original, "transitions": transitions,
    })
