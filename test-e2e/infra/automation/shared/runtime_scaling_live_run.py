# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run a real Agent using an attachment sent to the other Runtime instance."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
from time import monotonic, sleep
from urllib.parse import quote
from uuid import UUID

import httpx

from shared.runtime_scaling_attachments import require_status, sign_in, upload_attachment
from shared.runtime_scaling_model import INPUT_NAME, OUTPUT_NAME


def collect_agent_run(client, auth, agent, token, object_name, *, role=None):
    marker = f"runtime-storage-completed:{token}"
    query = f"runtime-storage-run:{token}"
    if role is not None:
        query, marker = f"runtime-storage-pair:{token}:{role}", f"{marker}:{role}"
    response = client.post("/api/agent/run", headers=auth, json={
        **agent, "query": query, "history": [],
        "minio_files": [{"object_name": object_name, "name": INPUT_NAME}],
    })
    require_status(response, 200, "Attachment Run on the peer Runtime")
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
    assert not any(event.get("type") == "error" for event in events), "Attachment Run emitted an error"
    final = "".join(event["content"] for event in events if event.get("type") == "final_answer")
    assert marker in final, "Attachment Run did not emit its controlled final answer"
    return int(response.headers["conversation_id"])


def wait_for_model(control, execution, timeout, *, role=None):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        progress = control("probe")
        if role is not None and progress["calls_by_tag"].get(role):
            assert progress["unexpected_calls"] == 0 and progress["calls_by_tag"][role] == 1
            assert role not in progress["released_tags"] and not execution.done()
            return
        if role is None and progress["entered"]:
            assert progress == {"stream_calls": 1, "unexpected_calls": 0, "entered": True, "released": False}
            return
        if execution.done():
            execution.result()
            raise AssertionError("Attachment Run completed before reaching the provider barrier")
        sleep(0.3)
    raise AssertionError("Attachment Run did not reach the controlled provider")


def check_private_object(client, object_name, owner_auth, foreign_auth, content):
    path = f"/api/file/download/{quote(object_name, safe='/')}"
    mode = {"download": "stream"}
    downloaded = client.get(path, headers=owner_auth, params=mode)
    require_status(downloaded, 200, "Owner object download through the stable Gateway")
    assert downloaded.content == content
    for headers, status in ((foreign_auth, 403), ({}, 401)):
        denied = client.get(path, headers=headers, params=mode)
        require_status(denied, status, "Unauthorized object download")
        assert content not in denied.content


def delete_owned_object(client, object_name, authorization):
    escaped = quote(object_name, safe="/")
    deleted = client.delete(f"/api/file/storage/{escaped}", headers=authorization)
    require_status(deleted, 200, "Delete the exact owned test object")
    assert deleted.json()["success"] is True
    require_status(client.get(f"/api/file/download/{escaped}", headers=authorization, params={"download": "stream"}),
                   404, "Verify the owned test object was removed")


def verify_completed_attachment(stable, execution, active, snapshot, owner, owner_auth, foreign_auth,
                                object_name, content, wait_seconds):
    conversation = execution.result(timeout=min(wait_seconds, 120))
    assert active["conversation_id"] == conversation
    deadline = monotonic() + min(wait_seconds, 30)
    while True:
        terminal = snapshot()
        assert terminal["execution_id"] == active["execution_id"] and terminal["owner"] == active["owner"]
        if terminal["status"] == "completed" and terminal["run_id"] is None and not terminal.get("workspace_exists"):
            break
        assert monotonic() < deadline, "The Run did not settle and remove its own workspace"
        sleep(0.2)

    artifact = f"workspace/{owner['user_id']}/{active['run_id']}/outputs/{OUTPUT_NAME}"
    check_private_object(stable, artifact, owner_auth, foreign_auth, content)
    for owned_object in (artifact, object_name):
        delete_owned_object(stable, owned_object, owner_auth)
    history = f"/api/conversation/{conversation}"
    require_status(stable.delete(history, headers=owner_auth), 200, "Delete the owned attachment conversation")
    assert stable.get(history, headers=owner_auth).json()["data"] == []
    return {"execution_id": active["execution_id"], "conversation_id": conversation, "run_id": active["run_id"],
            "artifact_sha256": active["sha256"], "model_calls": 2, "input_and_output_access_isolated": True,
            "owned_objects_and_conversation_deleted": True}


def exercise_live_attachment_run(url_a, url_b, stable_url, identities, agent, token, *, control,
                                 live_snapshot, peer_name, wait_seconds, restart_writer=None):
    """Verify a peer-owned Run, optionally while replacing the writer Runtime."""
    content = f"live-runtime-attachment:{token}\n".encode()
    digest = hashlib.sha256(content).hexdigest()
    with ExitStack() as stack:
        timeout = httpx.Timeout(15, read=330)
        writer, peer, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=timeout, trust_env=False))
                                for url in (url_a, url_b, stable_url)]
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        owner = identities["owner"]
        foreign = identities["foreign"]
        assert owner["tenant_id"] != foreign["tenant_id"] and owner["user_id"] != foreign["user_id"]
        owner_auth = sign_in(stable, owner)
        foreign_auth = sign_in(stable, foreign)
        object_name = upload_attachment(writer, owner_auth, owner["user_id"], INPUT_NAME, content)
        check_private_object(stable, object_name, owner_auth, foreign_auth, content)
        execution = executor.submit(collect_agent_run, peer, owner_auth, agent, token, object_name)
        replacement = None
        try:
            wait_for_model(control, execution, min(wait_seconds, 90))
            active = live_snapshot()
            assert active["status"] == "running" and UUID(hex=active["owner"]).hex == active["owner"]
            assert active["run_id"] and active["sha256"] == digest
            if restart_writer is not None:
                replacement = restart_writer()
                assert not execution.done(), "Peer Run ended while the writer was being replaced"
                assert live_snapshot() == active, "Peer reservation or attachment changed during the writer replacement"
            assert control("probe") == {"stream_calls": 1, "unexpected_calls": 0, "entered": True, "released": False}
        finally:
            assert control("release") == {"released": True}
        evidence = verify_completed_attachment(stable, execution, active, live_snapshot, owner, owner_auth,
                                               foreign_auth, object_name, content, wait_seconds)
        assert control("probe") == {"stream_calls": 2, "unexpected_calls": 0, "entered": True, "released": True}
        return replacement, {**evidence, "runtime_pod": peer_name}


def exercise_live_attachment_pair(url_a, url_b, stable_url, identities, agents, token, *, control, live_snapshot,
                                  pod_names, wait_seconds, restart_writer):
    """Finish A's actual Run and replace A while B's actual Run stays live."""
    roles = {"a": "owner", "b": "foreign"}
    with ExitStack() as stack:
        timeout = httpx.Timeout(15, read=330)
        clients = {role: stack.enter_context(httpx.Client(base_url=url, timeout=timeout, trust_env=False))
                   for role, url in (("a", url_a), ("b", url_b), ("stable", stable_url))}
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=2))
        stable = clients["stable"]
        owners = {role: identities[identity] for role, identity in roles.items()}
        assert all(owners["a"][key] != owners["b"][key] for key in ("user_id", "tenant_id"))
        auth = {role: sign_in(stable, owner) for role, owner in owners.items()}
        content = {role: f"live-runtime-attachment:{token}:{role}\n".encode() for role in roles}
        objects = {}
        executions = {}
        active = {}
        evidence = {}

        def complete(role, other):
            assert control(f"release/{role}") == {"released": True}
            return verify_completed_attachment(
                stable, executions[role], active[role], lambda: live_snapshot(role, active[role]["run_id"]),
                owners[role], auth[role], auth[other], objects[role], content[role], wait_seconds,
            )

        try:
            for role, peer in (("a", "b"), ("b", "a")):
                objects[role] = upload_attachment(clients[peer], auth[role], owners[role]["user_id"],
                                                  INPUT_NAME, content[role])
                check_private_object(stable, objects[role], auth[role], auth[peer], content[role])
                executions[role] = executor.submit(collect_agent_run, clients[role], auth[role], agents[roles[role]],
                                                   token, objects[role], role=role)
            for role in roles:
                wait_for_model(control, executions[role], min(wait_seconds, 90), role=role)
                active[role] = live_snapshot(role)
                assert active[role]["status"] == "running"
                assert UUID(hex=active[role]["owner"]).hex == active[role]["owner"]
                assert active[role]["run_id"] and active[role]["sha256"] == hashlib.sha256(content[role]).hexdigest()
            assert all(active["a"][key] != active["b"][key]
                       for key in ("execution_id", "conversation_id", "run_id", "owner"))
            evidence["a"] = complete("a", "b")
            assert not executions["b"].done() and live_snapshot("b") == active["b"], "A completion changed B's Run"
            replacement = restart_writer(active)
            assert not executions["b"].done() and live_snapshot("b") == active["b"], "A replacement changed B's Run"
            progress = control("probe")
            assert progress["calls_by_tag"] == {"a": 2, "b": 1} and progress["released_tags"] == ["a"]
            evidence["b"] = complete("b", "a")
            progress = control("probe")
            assert progress["calls_by_tag"] == {"a": 2, "b": 2} and progress["released_tags"] == ["a", "b"]
            assert progress["stream_calls"] == 4 and progress["unexpected_calls"] == 0
        finally:
            assert control("release") == {"released": True}
        return replacement, {role: {**value, "runtime_pod": pod_names[role]} for role, value in evidence.items()}
