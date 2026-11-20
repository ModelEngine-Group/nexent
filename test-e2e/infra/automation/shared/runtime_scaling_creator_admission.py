# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the real Creator endpoints while a scoped history write is held."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier

import httpx

from shared.runtime_scaling_admission import assert_unstarted, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_public_admission import assert_admission_rejection
from shared.runtime_scaling_stream import conversation_history


def exercise_creator_admission(urls, stable_url, identities, prepared, token, kind, *, control, snapshot,
                               gate, wait_seconds, expected_owners):
    timeout = min(wait_seconds, 85)
    path = {"agent": "/api/agent/nl2agent/run", "skill": "/api/skills/nl2skill/run"}[kind]
    with ExitStack() as stack:
        options = {"timeout": httpx.Timeout(timeout, connect=10), "trust_env": False}
        stable = stack.enter_context(httpx.Client(base_url=stable_url, **options))
        clients = {slot: stack.enter_context(httpx.Client(base_url=url, **options)) for slot, url in urls.items()}
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=3))
        stack.callback(control, "release")
        auth = {role: sign_in(stable, identity) for role, identity in identities.items()}

        def payload(role, label, tag):
            return {**prepared[role][label], "query": f"runtime-stream:{token}:{tag}",
                    "request_id": f"{token}:{tag}", "persist_history": True}

        def identifier(role, label):
            return prepared[role][label]["conversation_id"]

        def read(role):
            labels = prepared[role]
            batch = snapshot(role, *(identifier(role, label) for label in labels))
            assert batch["agent_limit"] == 2
            return {label: batch["conversations"][str(identifier(role, label))] for label in labels}

        def connect(slot, role, label, tag, barrier=None):
            if barrier is not None:
                barrier.wait(timeout=10)
            with clients[slot].stream("POST", path, headers=auth[role], json=payload(role, label, tag)) as response:
                if response.status_code == 409:
                    response.read()
                    assert response.json() == {"message": {"code": "CREATOR_RUN_ACTIVE"}}
                    return None
                if response.status_code != 200:
                    response.read()
                require_status(response, 200, f"Creator {kind} start")
                assert response.headers["content-type"].startswith("text/event-stream")
                assert int(response.headers["conversation_id"]) == identifier(role, label)
                return response.headers["run_id"]

        def calls():
            observed = control("probe")
            assert observed["unexpected_calls"] == 0, observed
            return observed["calls_by_tag"]

        def check_owner(reservation, slot):
            expected = expected_owners[slot]
            assert reservation["owner"] == expected or reservation["owner"].split(":", 1)[0] == expected
            assert reservation["agent_scope"] == f"nl2{kind}_main"

        def running(role, label, slot, tag, generation):
            wait_for(lambda: calls().get(tag) == 1, timeout, f"Creator {tag} did not reach the real model stream")
            row = read(role)[label]
            reservation, = row["reservations"]
            check_owner(reservation, slot)
            assert reservation["status"] == "RUNNING"
            assert generation == row["stream"]["generation"] == f"execution:{reservation['id']}"
            assert row["messages"] == [payload(role, label, tag)["query"]]
            history = conversation_history(stable, auth[role], identifier(role, label))
            message = history["streaming_message"]
            assert int(row["stream"]["message_id"]) == message["message_id"]
            return row, message["message_id"]

        def complete(role, label, tag, original, assistant_id):
            reservation, = original["reservations"]
            assert control(f"release/{tag}") == {"released": True}

            def settled():
                current, = read(role)[label]["reservations"]
                assert current["status"] not in {"FAILED", "STOPPED"}, current
                return current if current["status"] == "COMPLETED" else None

            assert wait_for(settled, timeout, f"Creator {tag} did not settle") == {**reservation, "status": "COMPLETED"}
            history = conversation_history(stable, auth[role], identifier(role, label))
            assistant, = [message for message in history["message"] if message["message_id"] == assistant_id]
            assert assistant["status"] == "completed"
            assert any(f"stream-tail:{tag}:结束🌊" in unit["content"] for unit in assistant["message"])

        for role in prepared:
            for row in read(role).values():
                assert_unstarted(row)

        contested_id = identifier("owner", "contested")
        preparation = executor.submit(gate, "hold", contested_id)
        try:
            def ready():
                if preparation.done():
                    preparation.result()
                    raise AssertionError("The case-owned Creator gate closed before release")
                return gate("probe", contested_id)["stage"]

            wait_for(lambda: ready() == "ready", min(timeout, 25), "The Creator history row was not locked")
            barrier = Barrier(2)
            contenders = {slot: executor.submit(connect, slot, "owner", "contested", f"race-{slot}", barrier)
                          for slot in clients}
            wait_for(lambda: ready() == "blocked", min(timeout, 30), "No Creator worker attempted the real history write")
            in_preparation = read("owner")["contested"]
            first_reservation, = in_preparation["reservations"]
            assert first_reservation["status"] == "PREPARING"
            assert not in_preparation["messages"] and not in_preparation["event_ids"] and calls() == {}
            assert in_preparation["stream"]["generation"] == f"execution:{first_reservation['id']}"

            finished = wait_for(lambda: {slot for slot, result in contenders.items() if result.done()}, min(timeout, 20),
                                "Neither contender returned the expected Creator conflict")
            loser, = finished
            winner, = contenders.keys() - finished
            assert contenders[loser].result() is None and not contenders[winner].done()
            check_owner(first_reservation, winner)

            second_generation = connect(loser, "owner", "second", "second-slot")
            second, second_assistant = running("owner", "second", loser, "second-slot", second_generation)
            assert second["reservations"][0]["owner"] != first_reservation["owner"]
            for slot, client in clients.items():
                response = client.post(path, headers=auth["owner"], json=payload("owner", "candidate", f"quota-{slot}"))
                if kind == "agent":
                    assert_admission_rejection(response, 429, "RUNTIME_CAPACITY_FULL")
                else:
                    require_status(response, 429, "Creator skill shared quota")
                    assert response.json() == {"message": {"code": "RUNTIME_CAPACITY_EXCEEDED", "retryable": True}}
                    assert response.headers["Retry-After"] == "1"
                assert_unstarted(read("owner")["candidate"])
            assert read("owner")["contested"] == in_preparation and calls() == {"second-slot": 1}

            isolated_generation = connect(loser, "foreign", "isolated", "foreign-tenant")
            isolated, isolated_assistant = running("foreign", "isolated", loser, "foreign-tenant", isolated_generation)
            assert read("owner")["contested"] == in_preparation
        finally:
            assert gate("release", contested_id) == {"released": True}

        assert preparation.result(timeout=timeout) == {"history_write_blocked": True}
        winning_tag = f"race-{winner}"
        generation = contenders[winner].result(timeout=timeout)
        first, first_assistant = running("owner", "contested", winner, winning_tag, generation)
        assert first["reservations"] == [{**first_reservation, "status": "RUNNING"}]
        assert connect(loser, "owner", "contested", "repeat-conflict") is None
        preserved, message_id = running("owner", "contested", winner, winning_tag, generation)
        assert first_assistant == message_id and preserved["reservations"] == first["reservations"]
        assert preserved["event_ids"][:len(first["event_ids"])] == first["event_ids"]

        complete("owner", "contested", winning_tag, first, first_assistant)
        retry_generation = connect(loser, "owner", "candidate", "after-release")
        candidate, candidate_assistant = running("owner", "candidate", loser, "after-release", retry_generation)
        assert read("owner")["second"]["reservations"] == second["reservations"]
        complete("owner", "candidate", "after-release", candidate, candidate_assistant)
        complete("owner", "second", "second-slot", second, second_assistant)
        complete("foreign", "isolated", "foreign-tenant", isolated, isolated_assistant)
        assert calls() == {winning_tag: 1, "second-slot": 1, "foreign-tenant": 1, "after-release": 1}

        for role, labels in prepared.items():
            for label in labels:
                conversation_path = f"/api/conversation/{identifier(role, label)}"
                require_status(stable.delete(conversation_path, headers=auth[role]), 200, "Delete owned Creator history")
                removed = stable.get(conversation_path, headers=auth[role])
                require_status(removed, 200, "Check deleted Creator history")
                assert removed.json()["data"] == []
        return {"kind": kind, "winner": winner, "preparing_counted_for_quota": True, "closed_sse_after_start": True,
                "conflict_attempts": 2, "quota_rejections": 2, "same_scope_tenant_isolation": True,
                "readmitted_after_release": True, "model_calls": calls(),
                "owners": [first_reservation["owner"], second["reservations"][0]["owner"]]}
