# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise simultaneous Northbound admission through the public Gateway."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier

import httpx

from shared.runtime_scaling_admission import assert_conflict, assert_unstarted, new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_public_admission import (
    FIXTURE_AGENT_NAME,
    NORTHBOUND_RUN,
    assert_admission_rejection,
    stream_prefix,
)
from shared.runtime_scaling_stream import assert_persisted_answer, check_stream, conversation_history


def exercise_northbound_admission(gateway_urls, stable_url, identity, api_key, agent, token, *, control, snapshot,
                                  wait_seconds, hosts):
    timeout = min(wait_seconds, 90)
    with ExitStack() as stack:
        client = stack.enter_context(httpx.Client(base_url=stable_url, timeout=timeout, trust_env=False))
        directed = {side: stack.enter_context(httpx.Client(base_url=url, timeout=timeout, trust_env=False))
                    for side, url in gateway_urls.items()}
        assert directed.keys() == hosts.keys() and len(set(hosts.values())) == 2
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=2))
        stack.callback(control, "release")
        owner = sign_in(client, identity)
        key = {"Authorization": f"Bearer {api_key}"}
        contested, second, candidate = new_conversations(client, owner, 3)

        def query(tag):
            return f"runtime-stream:{token}:{tag}"

        def payload(identifier, tag):
            return {"agent_name": FIXTURE_AGENT_NAME, "model_id": agent["model_id"], "conversation_id": identifier,
                    "query": query(tag), "stream_cursor": True}

        def read():
            data = snapshot(contested, second, candidate)
            assert data["agent_limit"] == 2
            return data["conversations"]

        def connect(identifier, tag, barrier=None):
            if barrier is not None:
                barrier.wait(timeout=10)
            side = tag.rsplit("-", 1)[1]
            with directed[side].stream("POST", NORTHBOUND_RUN, headers=key, json=payload(identifier, tag)) as response:
                if response.headers.get("X-Stream-Status") == "conflict":
                    response.read()
                    assert_conflict(response)
                    return None
                return stream_prefix(check_stream(response, identifier), tag)

        owners = {}

        def model_tags():
            data = control("probe")
            assert data["unexpected_calls"] == 0
            return data["calls_by_tag"]

        def active(identifier, tag, generation):
            row = read()[str(identifier)]
            reservation, = row["reservations"]
            assert reservation["status"] == "running" and reservation["agent_scope"] == f"agent:{agent['agent_id']}"
            side = tag.rsplit("-", 1)[1]
            assert owners.setdefault(side, reservation["owner"]) == reservation["owner"]
            assert row["messages"] == [query(tag)]
            assert generation == row["stream"]["generation"] == reservation["id"]
            assert row["event_ids"]
            return row

        def assistant_id(identifier):
            return conversation_history(client, owner, identifier)["streaming_message"]["message_id"]

        def complete(identifier, tag, reservation, message_id):
            assert control(f"release/{tag}") == {"released": True}

            def settled():
                record, = read()[str(identifier)]["reservations"]
                assert record["status"] not in {"failed", "stopped"}, record
                return record if record["status"] == "completed" else None

            assert wait_for(settled, timeout, f"Northbound run {tag} did not settle") == {
                **reservation, "status": "completed",
            }
            wait_for(lambda: any(message["message_id"] == message_id and message["status"] == "completed"
                                 for message in conversation_history(client, owner, identifier)["message"]),
                     timeout, "Northbound assistant projection did not finish")
            assert_persisted_answer(client, owner, identifier, message_id, tag)

        for row in read().values():
            assert_unstarted(row)
        barrier = Barrier(2)
        futures = {side: executor.submit(connect, contested, f"nb-race-{side}", barrier) for side in directed}
        results = {side: future.result(timeout=timeout) for side, future in futures.items()}
        winner, = (side for side, generation in results.items() if generation is not None)
        loser, = results.keys() - {winner}

        winning_tag, second_tag, retry_tag = f"nb-race-{winner}", f"nb-second-{loser}", f"nb-retry-{loser}"
        first = active(contested, winning_tag, results[winner])
        first_assistant = assistant_id(contested)
        overlap = f"nb-overlap-{loser}"
        assert connect(contested, overlap) is None
        preserved = active(contested, winning_tag, results[winner])
        assert first["reservations"] == preserved["reservations"]
        assert preserved["event_ids"][:len(first["event_ids"])] == first["event_ids"]
        assert assistant_id(contested) == first_assistant and model_tags() == {winning_tag: 1}

        second_generation = connect(second, second_tag)
        admitted = active(second, second_tag, second_generation)
        second_assistant = assistant_id(second)
        first_reservation, = first["reservations"]
        second_reservation, = admitted["reservations"]
        assert first_reservation["owner"] != second_reservation["owner"]
        for side in results:
            tag = f"nb-quota-{side}"
            response = directed[side].post(NORTHBOUND_RUN, headers=key, json=payload(candidate, tag))
            assert_admission_rejection(response, 429, "RUNTIME_CAPACITY_FULL")
            assert_unstarted(read()[str(candidate)])
        assert model_tags() == {winning_tag: 1, second_tag: 1}

        complete(contested, winning_tag, first_reservation, first_assistant)
        retry_generation = connect(candidate, retry_tag)
        retry_reservation, = active(candidate, retry_tag, retry_generation)["reservations"]
        assert active(second, second_tag, second_generation)["reservations"] == [second_reservation]
        complete(candidate, retry_tag, retry_reservation, assistant_id(candidate))
        complete(second, second_tag, second_reservation, second_assistant)
        observed_model_tags = model_tags()
        assert observed_model_tags == {winning_tag: 1, second_tag: 1, retry_tag: 1}

        for identifier in (contested, second, candidate):
            path = f"/api/conversation/{identifier}"
            require_status(client.delete(path, headers=owner), 200, "Delete the owned Northbound conversation")
            removed = client.get(path, headers=owner)
            require_status(removed, 200, "Check deleted Northbound conversation")
            assert removed.json()["data"] == []
        return {"winner": winner, "runtime_pods": hosts, "model_calls": observed_model_tags,
                "owners": [first_reservation["owner"], second_reservation["owner"]], "owned_conversations_removed": 3}
