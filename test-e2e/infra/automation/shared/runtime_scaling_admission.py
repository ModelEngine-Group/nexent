# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise durable Agent admission through two independently routed Runtime instances."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from threading import Barrier
from time import monotonic, sleep

import httpx

from shared.runtime_scaling_attachments import require_status, sign_in


def marker(token, tag):
    return f"runtime-admission:{token}:{tag}"


def new_conversations(client, auth, count):
    identifiers = []
    for index in range(count):
        response = client.put("/api/conversation/create", headers=auth, json={"title": f"Runtime admission {index}"})
        require_status(response, 200, "Create the owned conversation before competing")
        identifiers.append(response.json()["data"]["conversation_id"])
    assert len(set(identifiers)) == count
    return identifiers


def post_agent(client, auth, agent, token, identifier, tag, barrier=None):
    if barrier is not None:
        barrier.wait(timeout=10)
    return client.post("/api/agent/run", headers=auth, json={**agent, "conversation_id": identifier,
                       "query": marker(token, tag), "history": [], "stream_cursor": True})


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]


def assert_conflict(response):
    require_status(response, 200, "Competing turn SSE conflict")
    assert response.headers["X-Stream-Status"] == "conflict"
    assert [event.get("type") for event in events(response)] == ["error"]


def assert_completed(response, identifier, tag):
    require_status(response, 200, "Admitted turn SSE completion")
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    assert int(response.headers["conversation_id"]) == identifier
    assert not any(event.get("type") == "error" for event in events(response))
    answer = "".join(event["content"] for event in events(response) if event.get("type") == "final_answer")
    assert f"runtime-admitted:{tag}" in answer


def wait_for(predicate, timeout, failure):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        observed = predicate()
        if observed:
            return observed
        sleep(0.25)
    raise AssertionError(failure)


def assert_active(state, token, tag, expected_owner=None):
    reservation, = state["reservations"]
    assert reservation["status"] == "RUNNING"
    if expected_owner is not None:
        assert reservation["owner"].split(":", 1)[0] == expected_owner
    assert state["messages"] == [marker(token, tag)]
    assert state["stream"]["generation"] == f"execution:{reservation['id']}"
    assert state["stream"]["execution_id"] == str(reservation["id"])
    return reservation


def assert_unstarted(state):
    assert state == {"reservations": [], "messages": [], "stream": {}, "event_ids": []}


def exercise_admission_race(url_a, url_b, stable_url, identity, agent, token, *, control, snapshot,
                            wait_seconds, expected_hosts=None):
    """Prove exclusion, losing-side effects, and aggregate limit for ordinary Agent turns."""
    timeout = min(wait_seconds, 90)
    main_agent = {"agent_id": agent["agent_id"], "model_id": agent["model_id"]}
    distinct_agent = {**main_agent, "agent_id": agent["other_agent_id"]}
    with ExitStack() as stack:
        options = {"timeout": httpx.Timeout(15, read=330), "trust_env": False}
        runtime_a, runtime_b, stable = [stack.enter_context(httpx.Client(base_url=url, **options))
                                        for url in (url_a, url_b, stable_url)]
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=3))
        auth = sign_in(stable, identity)
        contested, second, quota_a, quota_b, different = new_conversations(stable, auth, 5)

        def read():
            data = snapshot(contested, second, quota_a, quota_b, different)
            assert data["agent_limit"] == 2
            return data["conversations"]

        def provider_tags(*, held=True):
            state = control("probe")
            assert state["unexpected_calls"] == 0, state
            if held:
                assert state["auxiliary_calls"] == 0, "Rejected requests must not call the model while Runs are held"
            assert set(state["auxiliary_tags"]) <= state["calls_by_tag"].keys(), "Unexpected query in an auxiliary model call"
            return state["calls_by_tag"]

        def submit(client, identifier, label, barrier=None, target=main_agent):
            return executor.submit(post_agent, client, auth, target, token, identifier, label, barrier)

        for state in read().values():
            assert_unstarted(state)
        clients = {"race-a": runtime_a, "race-b": runtime_b}
        barrier = Barrier(2)
        racers = {tag: submit(client, contested, tag, barrier) for tag, client in clients.items()}
        try:
            reached = wait_for(provider_tags, timeout, "No contender reached the real provider")
            assert len(reached) == 1 and set(reached) <= clients.keys() and list(reached.values()) == [1]
            winner, = reached
            loser, = clients.keys() - {winner}
            assert_conflict(racers[loser].result(timeout=timeout))
            assert not racers[winner].done(), "Winning Run must remain held at the provider"

            before = read()[str(contested)]
            first = assert_active(before, token, winner, expected_hosts[winner] if expected_hosts else None)
            assert before["event_ids"], "The active stream must have events to preserve"
            assert_conflict(post_agent(clients[loser], auth, main_agent, token, contested, "repeat-conflict"))
            after = read()[str(contested)]
            assert_active(after, token, winner, expected_hosts[winner] if expected_hosts else None)
            assert after["event_ids"][:len(before["event_ids"])] == before["event_ids"]
            assert after["reservations"] == before["reservations"] and provider_tags() == {winner: 1}

            other = submit(clients[loser], second, "second-slot")
            wait_for(lambda: provider_tags().get("second-slot"), timeout, "The other Runtime did not claim the second slot")
            second_record = assert_active(read()[str(second)], token, "second-slot",
                                          expected_hosts[loser] if expected_hosts else None)
            assert first["owner"] != second_record["owner"] and first["agent_scope"] == second_record["agent_scope"]
            for client, identifier, tag in ((runtime_a, quota_a, "quota-a"), (runtime_b, quota_b, "quota-b")):
                response = post_agent(client, auth, main_agent, token, identifier, tag)
                require_status(response, 429, "Excess run at the shared Agent limit")
                assert response.json()["code"] == "RUNTIME_CAPACITY_FULL" and response.headers["Retry-After"] == "1"
            limited = read()
            assert_unstarted(limited[str(quota_a)])
            assert_unstarted(limited[str(quota_b)])
            assert provider_tags() == {winner: 1, "second-slot": 1}
            assert not racers[winner].done() and not other.done()

            isolated = submit(runtime_b, different, "separate-agent", target=distinct_agent)
            wait_for(lambda: provider_tags().get("separate-agent"), timeout,
                     "Another Agent must be accepted while the first Agent is at its limit")
            separated = assert_active(read()[str(different)], token, "separate-agent",
                                      expected_hosts["race-b"] if expected_hosts else None)
            assert separated["agent_scope"] != first["agent_scope"]
            assert not racers[winner].done() and not other.done() and not isolated.done()
        finally:
            assert control("release") == {"released": True}

        assert_completed(racers[winner].result(timeout=timeout), contested, winner)
        assert_completed(other.result(timeout=timeout), second, "second-slot")
        assert_completed(isolated.result(timeout=timeout), different, "separate-agent")

        def settled():
            observed = read()
            return all([item["status"] for item in observed[str(identifier)]["reservations"]] == ["COMPLETED"]
                       for identifier in (contested, second, different))

        wait_for(settled, timeout, "The admitted reservations did not settle")
        assert_completed(post_agent(runtime_b, auth, main_agent, token, quota_b, "after-release"), quota_b, "after-release")
        assert provider_tags(held=False) == {winner: 1, "second-slot": 1, "separate-agent": 1, "after-release": 1}

        def readmission_completed():
            observed = read()[str(quota_b)]
            assert observed["messages"] == [marker(token, "after-release")]
            return [item["status"] for item in observed["reservations"]] == ["COMPLETED"]

        wait_for(readmission_completed, timeout, "Readmitted reservation did not settle")
        return {"winner": winner, "first_execution": first["id"], "second_execution": second_record["id"],
                "distinct_owners": True, "conflict_attempts": 2, "quota_rejections": 2, "readmission": True,
                "separate_agent_accepted": True}
