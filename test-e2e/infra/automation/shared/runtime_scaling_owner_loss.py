# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the durable loss and maintenance boundary of an actual Runtime owner."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
from threading import Barrier

import httpx

from shared.runtime_scaling_admission import assert_conflict, new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status
from shared.runtime_scaling_public_admission import assert_admission_rejection, stream_completion, stream_prefix
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, check_stream


@contextmanager
def owner_client(cluster, pod=None):
    gateway = cluster.create_runtime_gateway(pod) if pod is not None else None
    with cluster.gateway_http(gateway) as url, httpx.Client(base_url=url, timeout=60, trust_env=False) as client:
        yield client


def owner_snapshot(cluster, pod, *, quota=None, ttl=None):
    source = Path(__file__).with_name("runtime_scaling_owner_probe.py").read_text(encoding="utf-8")

    def snapshot(*identifiers):
        output = cluster.run_fixture_python(pod["metadata"]["name"], source, cluster.run_id,
                                            *(str(identifier) for identifier in identifiers))
        record, = (line.removeprefix("SCALING_OWNER_LOSS ") for line in output.splitlines()
                   if line.startswith("SCALING_OWNER_LOSS "))
        observed = json.loads(record)
        assert quota is None or observed["quota"] == quota
        assert ttl is None or observed["ttl_seconds"] == ttl
        return observed

    return snapshot


def model_receipt(control, *tags, rounds=1, allow_auxiliary=False):
    observed = control("probe")
    assert observed["calls_by_tag"] == dict.fromkeys(tags, rounds), observed
    assert observed["stream_calls"] == len(tags) * rounds and observed["unexpected_calls"] == 0, observed
    assert allow_auxiliary or observed["auxiliary_calls"] == 0, observed
    return {key: observed[key] for key in ("calls_by_tag", "stream_calls", "auxiliary_calls", "unexpected_calls")}


def stream_payload(agent, token, identifier, tag, *, minio_files=()):
    payload = {**agent, "conversation_id": identifier, "query": f"runtime-stream:{token}:{tag}",
               "history": [], "stream_cursor": True}
    if minio_files:
        payload["minio_files"] = list(minio_files)
    return payload


def begin_owner_loss(stable, owner, auth, agent, token, *, epoch, snapshot, crash, control, expected_host=None,
                     tag="lost-owner", prior_tags=(), rounds=1, minio_files=()):
    identifier, candidate = new_conversations(stable, auth, 2)
    payload = stream_payload(agent, token, identifier, tag, minio_files=minio_files)
    with owner.stream("POST", RUN_PATH, headers=auth, json=payload) as response:
        frames = check_stream(response, identifier)
        generation = stream_prefix(frames, tag)
        before = snapshot(identifier)
        assert before["quota"] == 1
        active = before["runs"][str(identifier)]
        reservation, = active["reservations"]
        assistant, = active["assistants"]
        assert reservation["status"] == "RUNNING" and not reservation["finished"] and reservation["epoch"] == epoch
        assert generation == f"execution:{reservation['id']}" and active["state"]["generation"] == generation
        assert 0 < active["state_pttl"] <= before["ttl_seconds"] * 1000
        assert assistant["status"] == "streaming" and active["users"] == [payload["query"]] and not active["cancel_ids"]
        if expected_host is not None:
            assert reservation["owner"].split(":", 1)[0] == expected_host
        assert control("probe")["calls_by_tag"] == dict.fromkeys((*prior_tags, tag), rounds)
        crash()
        try:
            for _, _, frame in frames:
                assert frame.get("type") not in {"final_answer", "error"}, "Owner emitted a terminal frame before interruption"
                assert frame.get("status") not in {"completed", "stopped", "failed"}
        except (httpx.RemoteProtocolError, httpx.ReadError):
            pass
        else:
            raise AssertionError("The active Runtime stream was not cut by loss of its worker")
    return identifier, candidate, active


def verify_retained_owner(first, replacement, auth, agent, token, loss, *, snapshot, control, wait_seconds):
    identifier, candidate, active = loss
    reservation, = active["reservations"]

    def current():
        snapshot_by_id = snapshot(identifier, candidate)["runs"]
        return snapshot_by_id[str(identifier)], snapshot_by_id[str(candidate)]

    def expired():
        observed, unused = current()
        assert observed["reservations"] == active["reservations"] and observed["assistants"] == active["assistants"]
        assert observed["users"] == active["users"] and not observed["cancel_ids"]
        assert not unused["reservations"] and not unused["users"] and not unused["assistants"]
        return observed["state_pttl"] == -2 and not observed["state"]

    wait_for(expired, wait_seconds, "The real Redis Runtime state key did not expire")
    barrier = Barrier(2)

    def compete(client, tag):
        barrier.wait(timeout=10)
        return client.post(RUN_PATH, headers=auth, json=stream_payload(agent, token, identifier, tag))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(compete, client, tag) for client, tag in
                   ((first, "race-survivor"), (replacement, "race-replacement"))]
        for future in futures:
            assert_conflict(future.result(timeout=wait_seconds))
    assert_admission_rejection(first.post(RUN_PATH, headers=auth, json=stream_payload(agent, token, candidate, "quota-held")),
                               429, "RUNTIME_CAPACITY_FULL")
    assert expired(), "An unsuccessful request changed the expired stream or the durable owner"

    stop = replacement.get(f"/api/agent/stop/{identifier}", headers=auth)
    require_status(stop, 200, "Stop request for the orphaned execution")
    assert stop.json()["status"] == "success" and not stop.json().get("already_stopped")
    stopped, _ = current()
    assert stopped["cancel_ids"] == [reservation["id"]] and stopped["state_pttl"] == -2
    assert stopped["reservations"] == active["reservations"] and stopped["assistants"] == active["assistants"]
    assert control("probe")["calls_by_tag"] == {"lost-owner": 1}
    return {"redis_key_expired": True, "conflicts": 2, "quota_held": True,
            "stop_signal_without_settlement": True, "interrupted_id": reservation["id"]}


def verify_interrupted_owner(loss, *, epoch, snapshot):
    identifier, _, active = loss
    reservation, = active["reservations"]
    old_assistant, = active["assistants"]
    before = snapshot(identifier)["runs"][str(identifier)]
    interrupted = {**reservation, "status": "FAILED", "finished": True, "error_code": "RUNTIME_OWNER_INTERRUPTED"}
    assert before["reservations"] == [interrupted] and before["users"] == active["users"]
    failed_assistant = {**old_assistant, "status": "failed"}
    assert before["assistants"] == [failed_assistant]
    if before["state"]:
        assert before["state"]["status"] == "failed"
    assert epoch != reservation["epoch"]
    return interrupted, failed_assistant


def delete_owner_conversations(stable, auth, loss):
    for conversation_id in loss[:2]:
        path = f"/api/conversation/{conversation_id}"
        require_status(stable.delete(path, headers=auth), 200, "Delete the owned conversation")
        assert stable.get(path, headers=auth).json()["data"] == []


def verify_after_maintenance(stable, auth, agent, token, loss, *, epoch, snapshot, control, wait_seconds, prior_tags=(),
                             rounds=1, minio_files=()):
    identifier, _, active = loss
    interrupted, failed_assistant = verify_interrupted_owner(loss, epoch=epoch, snapshot=snapshot)
    prior_calls = dict.fromkeys((*prior_tags, "lost-owner"), rounds)
    assert control("probe")["calls_by_tag"] == prior_calls

    def state():
        return snapshot(identifier)["runs"][str(identifier)]

    payload = stream_payload(agent, token, identifier, "after-maintenance", minio_files=minio_files)
    with stable.stream("POST", RUN_PATH, headers=auth, json=payload) as response:
        frames = check_stream(response, identifier)
        generation = stream_prefix(frames, "after-maintenance")
        observed = state()
        old, current = observed["reservations"]
        assert old == interrupted and current["status"] == "RUNNING" and current["epoch"] == epoch
        assert current["owner"] != interrupted["owner"] and generation == f"execution:{current['id']}"
        assert control("release/after-maintenance")["released"] is True
        stream_completion(frames, generation, "after-maintenance")

    def settled():
        observed = state()
        return observed if observed["reservations"][-1]["status"] == "COMPLETED" else None

    completed = wait_for(settled, wait_seconds, "Post-maintenance execution did not settle")
    assert completed["reservations"] == [interrupted, {**current, "status": "COMPLETED", "finished": True}]
    assert completed["users"] == [*active["users"], payload["query"]]
    prior, new = completed["assistants"]
    assert prior == failed_assistant and new["id"] != prior["id"] and new["status"] == "completed"
    assert_persisted_answer(stable, auth, identifier, new["id"], "after-maintenance")
    model = control("probe")
    assert model["calls_by_tag"] == {**prior_calls, "after-maintenance": rounds} and model["unexpected_calls"] == 0
    delete_owner_conversations(stable, auth, loss)
    return {"interrupted_state": interrupted["error_code"], "recovered_execution": current["id"],
            "model_calls": model["calls_by_tag"], "owned_conversations_deleted": True}
