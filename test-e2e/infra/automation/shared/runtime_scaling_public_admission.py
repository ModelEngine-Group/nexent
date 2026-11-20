# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise public Runtime admission through the real Web and Northbound proxies."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import re

import httpx

from shared.runtime_scaling_admission import assert_conflict, assert_unstarted, new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, check_stream, conversation_history


NORTHBOUND_RUN = "/nb/v1/chat/run"
FIXTURE_AGENT_NAME = "runtime_scaling_fixture"
OTHER_FIXTURE_AGENT_NAME = "runtime_fixture_other_scope"


def stream_prefix(frames, tag):
    for event, cursor, frame in frames:
        assert frame.get("type") != "error", "The public stream failed before the controlled prefix"
        if frame.get("content") == f"stream-prefix:{tag}:界🌊":
            assert event == "message"
            generation = re.fullmatch(r"(execution:[1-9][0-9]*):[0-9]+:[0-9]+", cursor or "")
            assert generation, "The public stream did not forward the durable execution cursor"
            return generation[1]
    raise AssertionError("The public stream ended without the expected prefix")


def stream_completion(frames, generation, tag):
    events = list(frames)
    assert events and not any(frame.get("type") == "error" for _, _, frame in events)
    cursors = [cursor for _, cursor, _ in events if cursor is not None]
    assert cursors and all(cursor.startswith(generation + ":") for cursor in cursors)
    assert len(set(cursors)) == len(cursors)
    answer = "".join(frame["content"] for _, _, frame in events if frame.get("type") == "final_answer")
    assert answer == f"stream-tail:{tag}:结束🌊"


def assert_admission_rejection(response, status, code):
    require_status(response, status, code)
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.headers["Retry-After"] == "1"
    body = response.json()
    assert body["code"] == code and body["retryable"] is True


def exercise_coordination_faults(identifier, *, reject_redis, reject_postgres, probe, check_unchanged, wait_seconds):
    try:
        denied = probe("deny-redis", identifier)
        assert denied == {"coordination_ping_denied": True}
        assert_admission_rejection(reject_redis(), 503, "RUNTIME_COORDINATION_UNAVAILABLE")
    finally:
        restored = probe("restore-redis", identifier)
    assert restored == {"acl_restored": True}
    check_unchanged()

    with ThreadPoolExecutor(max_workers=1) as executor:
        cancellation = executor.submit(probe, "cancel-postgres", identifier)

        def lock_held():
            if cancellation.done():
                cancellation.result()
                raise AssertionError("PostgreSQL probe completed before the request was sent")
            return probe("postgres-ready", identifier)["locked"]

        wait_for(lock_held, min(wait_seconds, 45), "The scoped PostgreSQL advisory lock was not ready")
        assert_admission_rejection(reject_postgres(), 503, "RUNTIME_COORDINATION_UNAVAILABLE")
        canceled = cancellation.result(timeout=wait_seconds)
    assert canceled == {"scoped_waiter_observed": True, "query_canceled": True}
    check_unchanged()
    return {"redis": {**denied, **restored}, "postgres": canceled}


def exercise_peer_coordination_recovery(url_a, url_b, stable_url, identity, agent, token, *, control, snapshot,
                                        capacity, fault_probe, wait_seconds, expected_hosts=None):
    timeout = min(wait_seconds, 60)
    with ExitStack() as stack:
        first, peer, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=httpx.Timeout(15, read=120),
                                                               trust_env=False))
                               for url in (url_a, url_b, stable_url)]
        auth = sign_in(stable, identity)
        routing, holder, candidate = new_conversations(stable, auth, 3)
        routing_tag = "coordination-route-a"
        holder_tag, candidate_tag = "coordination-holder", "coordination-retry"

        def payload(identifier, tag):
            return {**agent, "conversation_id": identifier, "query": f"runtime-stream:{token}:{tag}",
                    "history": [], "stream_cursor": True}

        def read_states():
            result = snapshot(holder, candidate)
            assert result["agent_limit"] == 2
            return tuple(result["conversations"][str(identifier)] for identifier in (holder, candidate))

        def model_calls():
            observed = control("probe")
            assert observed["unexpected_calls"] == 0, observed
            return observed["calls_by_tag"]

        def routing_state():
            return snapshot(routing)["conversations"][str(routing)]

        for state in read_states():
            assert_unstarted(state)
        assert_unstarted(routing_state())
        assert capacity("a")["active_count"] == 0
        try:
            with first.stream("POST", RUN_PATH, headers=auth, json=payload(routing, routing_tag)) as response:
                frames = check_stream(response, routing)
                generation = stream_prefix(frames, routing_tag)
                routed, = routing_state()["reservations"]
                assert routed["status"] == "RUNNING" and generation == f"execution:{routed['id']}"
                assert control(f"release/{routing_tag}") == {"released": True}
                stream_completion(frames, generation, routing_tag)
            wait_for(lambda: routing_state()["reservations"] == [{**routed, "status": "COMPLETED"}], timeout,
                     "The routed pre-fault execution on A did not settle")

            holding = stack.enter_context(peer.stream("POST", RUN_PATH, headers=auth, json=payload(holder, holder_tag)))
            holder_frames = check_stream(holding, holder)
            holder_generation = stream_prefix(holder_frames, holder_tag)
            active, unstarted = read_states()
            original, = active["reservations"]
            assert original["status"] == "RUNNING" and holder_generation == f"execution:{original['id']}"
            assert routed["owner"] != original["owner"], "Both Gateways reached the same Runtime process"
            if expected_hosts is not None:
                assert tuple(row["owner"].split(":", 1)[0] for row in (routed, original)) == expected_hosts
            assert_unstarted(unstarted)
            live_history = conversation_history(peer, auth, holder)["message"]
            assert live_history

            def unchanged():
                assert read_states() == (active, unstarted)
                assert conversation_history(peer, auth, candidate)["message"] == []
                assert model_calls() == {routing_tag: 1, holder_tag: 1}

            def reject_on_a():
                assert conversation_history(peer, auth, holder)["message"] == live_history
                with first.stream("POST", RUN_PATH, headers=auth, json=payload(candidate, candidate_tag)) as response:
                    require_status(response, 503, "Pre-reservation coordination failure on A")
                    response.read()
                    return response

            faults = exercise_coordination_faults(candidate, reject_redis=reject_on_a, reject_postgres=reject_on_a,
                                                   probe=fault_probe, check_unchanged=unchanged, wait_seconds=timeout)
            wait_for(lambda: capacity("a")["active_count"] == 0, timeout, "A kept a worker from a rejected request")
            retry = stack.enter_context(peer.stream("POST", RUN_PATH, headers=auth, json=payload(candidate, candidate_tag)))
            retry_frames = check_stream(retry, candidate)
            retry_generation = stream_prefix(retry_frames, candidate_tag)
            surviving, readmitted = read_states()
            recovered, = readmitted["reservations"]
            assert surviving == active and recovered["status"] == "RUNNING"
            assert recovered["owner"] == original["owner"] and recovered["agent_scope"] == original["agent_scope"]
            assert retry_generation == readmitted["stream"]["generation"] == f"execution:{recovered['id']}"
        finally:
            assert control("release") == {"released": True}

        stream_completion(holder_frames, holder_generation, holder_tag)
        stream_completion(retry_frames, retry_generation, candidate_tag)
        wait_for(lambda: all([row["status"] for row in state["reservations"]] == ["COMPLETED"]
                             for state in read_states()), timeout, "The peer executions did not settle")
        for identifier, tag, state in zip((routing, holder, candidate), (routing_tag, holder_tag, candidate_tag),
                                          (routing_state(), *read_states()), strict=True):
            assert state["messages"] == [f"runtime-stream:{token}:{tag}"]
            assistant, = (message for message in conversation_history(stable, auth, identifier)["message"]
                          if message["role"] == "assistant")
            assert_persisted_answer(stable, auth, identifier, assistant["message_id"], tag)
            path = f"/api/conversation/{identifier}"
            require_status(stable.delete(path, headers=auth), 200, "Delete the owned conversation")
            assert stable.get(path, headers=auth).json()["data"] == []
        wait_for(lambda: all(capacity(slot)["active_count"] == 0 for slot in ("a", "b")), timeout,
                 "The Agent lanes did not return to idle")
        assert model_calls() == {routing_tag: 1, holder_tag: 1, candidate_tag: 1}
        return {**faults, "routed_owners": [routed["owner"], original["owner"]], "readmitted_execution": recovered["id"],
                "failed_requests_left_no_reservation": True, "model_calls": model_calls()}


def exercise_public_admission(web_url, northbound_url, identities, api_keys, agent, token, *, control, snapshot,
                              fault_probe, wait_seconds, expected_hosts=None):
    with ExitStack() as stack:
        stack.callback(control, "release")
        web, northbound = [stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds, trust_env=False))
                           for url in (web_url, northbound_url)]
        session = {role: sign_in(northbound, identity) for role, identity in identities.items()}
        northbound_auth = {role: {"Authorization": f"Bearer {key}"} for role, key in api_keys.items()}
        web_id, northbound_id, recovery_id = new_conversations(web, session["owner"], 3)
        producer_instances = {}

        def marker(tag):
            return f"runtime-stream:{token}:{tag}"

        def web_payload(identifier, tag, *, other_scope=False):
            return {"agent_id": agent["other_agent_id" if other_scope else "agent_id"], "model_id": agent["model_id"],
                    "conversation_id": identifier, "query": marker(tag), "history": [], "stream_cursor": True}

        def northbound_payload(identifier, tag, *, other_scope=False):
            return {"agent_name": OTHER_FIXTURE_AGENT_NAME if other_scope else FIXTURE_AGENT_NAME,
                    "model_id": agent["model_id"], "conversation_id": identifier,
                    "query": marker(tag), "stream_cursor": True}

        def state(identifier):
            return snapshot(identifier)["conversations"][str(identifier)]

        def active(identifier, tag, generation):
            observed = state(identifier)
            reservation, = observed["reservations"]
            assert reservation["status"] == "RUNNING" and generation == f"execution:{reservation['id']}"
            assert observed["messages"] == [marker(tag)] and observed["event_ids"]
            assert observed["stream"]["generation"] == generation
            producer = reservation["owner"]
            if expected_hosts is not None:
                assert producer.split(":", 1)[0] in expected_hosts
            producer_instances[tag] = producer
            return observed

        def settled(identifier, tag, generation):
            def completed():
                observed = state(identifier)
                return observed if observed["reservations"][0]["status"] == "COMPLETED" else None

            observed = wait_for(completed, wait_seconds, "The public run did not settle its reservation")
            reservation, = observed["reservations"]
            assert generation == f"execution:{reservation['id']}" and observed["messages"] == [marker(tag)]
            history = conversation_history(web, session["owner"], identifier)
            assistant, = [message for message in history["message"] if message["role"] == "assistant"]
            assert_persisted_answer(web, session["owner"], identifier, assistant["message_id"], tag)

        with web.stream("POST", RUN_PATH, headers=session["owner"], json=web_payload(web_id, "web")) as response:
            frames = check_stream(response, web_id)
            web_generation = stream_prefix(frames, "web")
            held = active(web_id, "web", web_generation)
            assert_conflict(web.post(RUN_PATH, headers=session["owner"], json=web_payload(web_id, "web-conflict")))
            assert_conflict(northbound.post(NORTHBOUND_RUN, headers=northbound_auth["owner"],
                                           json=northbound_payload(web_id, "nb-conflict")))
            quota_before = snapshot(northbound_id)
            assert quota_before["agent_limit"] == 1
            for denied in (
                web.post(RUN_PATH, headers=session["owner"], json=web_payload(northbound_id, "web-quota")),
                northbound.post(NORTHBOUND_RUN, headers=northbound_auth["owner"],
                                json=northbound_payload(northbound_id, "nb-quota")),
            ):
                assert_admission_rejection(denied, 429, "RUNTIME_CAPACITY_FULL")
            assert snapshot(northbound_id) == quota_before
            fault_before = state(recovery_id)
            assert not fault_before["reservations"] and not fault_before["messages"] and not fault_before["event_ids"]

            def no_fault_side_effects():
                assert state(recovery_id) == fault_before
                assert state(web_id) == held
                assert control("probe")["calls_by_tag"] == {"web": 1}

            no_fault_side_effects()
            fault_evidence = exercise_coordination_faults(
                recovery_id, probe=fault_probe, check_unchanged=no_fault_side_effects, wait_seconds=wait_seconds,
                reject_redis=lambda: web.post(
                    RUN_PATH, headers=session["owner"], json=web_payload(recovery_id, "redis-rejected", other_scope=True),
                ),
                reject_postgres=lambda: northbound.post(
                    NORTHBOUND_RUN, headers=northbound_auth["owner"],
                    json=northbound_payload(recovery_id, "postgres-rejected", other_scope=True),
                ),
            )
            assert control("release/web")["released"] is True
            stream_completion(frames, web_generation, "web")
        settled(web_id, "web", web_generation)

        with northbound.stream("POST", NORTHBOUND_RUN, headers=northbound_auth["owner"],
                               json=northbound_payload(northbound_id, "northbound")) as response:
            frames = check_stream(response, northbound_id)
            assert response.headers["X-Request-Id"]
            nb_generation = stream_prefix(frames, "northbound")
            held = active(northbound_id, "northbound", nb_generation)
            web_history = f"/api/conversation/{northbound_id}"
            web_stop = f"/api/agent/stop/{northbound_id}"
            nb_history = f"/nb/v1/conversations/{northbound_id}"
            nb_stop = f"/nb/v1/chat/stop/{northbound_id}"
            for role in ("peer", "foreign"):
                query = web.get(web_history, headers=session[role])
                require_status(query, 200, "Non-owner Web history")
                assert query.json()["data"] == []
                stop = web.get(web_stop, headers=session[role])
                require_status(stop, 200, "Non-owner Web stop")
                assert stop.json()["already_stopped"] is True
                query = northbound.get(nb_history, headers=northbound_auth[role])
                require_status(query, 200, "Non-owner Northbound history")
                assert query.json()["data"]["history"] == []
                stop = northbound.get(nb_stop, headers=northbound_auth[role])
                require_status(stop, 200, "Non-owner Northbound stop")
                assert stop.json()["message"].startswith("no running agent or preprocess tasks found")
            for client, paths in ((web, (web_history, web_stop)), (northbound, (nb_history, nb_stop))):
                for path in paths:
                    require_status(client.get(path), 401, "Anonymous control or history")
            require_status(web.post(RUN_PATH, json=web_payload(northbound_id, "anonymous-web")), 401,
                           "Anonymous Web admission")
            require_status(northbound.post(NORTHBOUND_RUN, json=northbound_payload(northbound_id, "anonymous-nb")), 401,
                           "Anonymous Northbound admission")
            assert state(northbound_id) == held
            assert control("release/northbound")["released"] is True
            stream_completion(frames, nb_generation, "northbound")
        settled(northbound_id, "northbound", nb_generation)

        with web.stream("POST", RUN_PATH, headers=session["owner"],
                        json=web_payload(recovery_id, "recovered", other_scope=True)) as response:
            frames = check_stream(response, recovery_id)
            recovered = stream_prefix(frames, "recovered")
            active(recovery_id, "recovered", recovered)
            assert control("release/recovered")["released"] is True
            stream_completion(frames, recovered, "recovered")
        settled(recovery_id, "recovered", recovered)

        for identifier in (web_id, northbound_id, recovery_id):
            path = f"/api/conversation/{identifier}"
            require_status(web.delete(path, headers=session["owner"]), 200, "Delete the owned conversation")
            assert web.get(path, headers=session["owner"]).json()["data"] == []
        model = control("probe")
        assert model["calls_by_tag"] == {"web": 1, "northbound": 1, "recovered": 1} and model["unexpected_calls"] == 0
        return {"web_execution": web_generation, "northbound_execution": nb_generation, "conflicts": 2,
                "public_quota_rejections": 2,
                "coordination_faults": fault_evidence, "recovered_execution": recovered,
                "producer_instances": producer_instances,
                "non_owner_roles": ["same-tenant", "cross-tenant", "anonymous"], "model_calls": model["calls_by_tag"],
                "owned_conversations_deleted": True}


def exercise_local_lane(url_a, url_b, stable_url, identity, agent, token, *, control, snapshot, wait_seconds,
                        expected_hosts=None):
    with ExitStack() as stack:
        stack.callback(control, "release")
        first, peer, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds, trust_env=False))
                               for url in (url_a, url_b, stable_url)]
        authorization = sign_in(stable, identity)
        original, candidate = new_conversations(stable, authorization, 2)

        def payload(identifier, tag, scope):
            return {"agent_id": agent[scope], "model_id": agent["model_id"], "conversation_id": identifier,
                    "query": f"runtime-stream:{token}:{tag}", "history": [], "stream_cursor": True}

        def state():
            observed = snapshot(original, candidate)
            assert observed["agent_limit"] == 1
            return observed["conversations"][str(original)], observed["conversations"][str(candidate)]

        with first.stream("POST", RUN_PATH, headers=authorization,
                          json=payload(original, "lane-a", "agent_id")) as response_a:
            frames_a = check_stream(response_a, original)
            generation_a = stream_prefix(frames_a, "lane-a")
            held, before = state()
            reservation_a, = held["reservations"]
            assert reservation_a["status"] == "RUNNING" and generation_a == f"execution:{reservation_a['id']}"
            assert not before["reservations"] and not before["messages"] and not before["event_ids"]
            candidate_payload = payload(candidate, "lane-b", "other_agent_id")
            denied = first.post(RUN_PATH, headers=authorization, json=candidate_payload)
            assert_admission_rejection(denied, 429, "RUNTIME_CAPACITY_FULL")
            assert state() == (held, before)
            assert control("probe")["calls_by_tag"] == {"lane-a": 1}

            with peer.stream("POST", RUN_PATH, headers=authorization, json=candidate_payload) as response_b:
                frames_b = check_stream(response_b, candidate)
                generation_b = stream_prefix(frames_b, "lane-b")
                current, admitted = state()
                reservation_b, = admitted["reservations"]
                assert current == held
                assert reservation_b["status"] == "RUNNING" and generation_b == f"execution:{reservation_b['id']}"
                assert reservation_b["agent_scope"] != reservation_a["agent_scope"]
                assert reservation_b["owner"] != reservation_a["owner"]
                if expected_hosts is not None:
                    assert tuple(row["owner"].split(":", 1)[0] for row in (reservation_a, reservation_b)) == expected_hosts
                assert control("release/lane-b")["released"] is True
                stream_completion(frames_b, generation_b, "lane-b")
            assert control("release/lane-a")["released"] is True
            stream_completion(frames_a, generation_a, "lane-a")

        def settled():
            observed = state()
            return observed if all(row["reservations"][0]["status"] == "COMPLETED" for row in observed) else None

        completed = wait_for(settled, wait_seconds, "The local-lane executions did not settle")
        for identifier, tag, row in zip((original, candidate), ("lane-a", "lane-b"), completed, strict=True):
            reservation, = row["reservations"]
            assert reservation["status"] == "COMPLETED" and row["messages"] == [f"runtime-stream:{token}:{tag}"]
            path = f"/api/conversation/{identifier}"
            require_status(stable.delete(path, headers=authorization), 200, "Delete the owned conversation")
            assert stable.get(path, headers=authorization).json()["data"] == []
        model = control("probe")
        assert model["calls_by_tag"] == {"lane-a": 1, "lane-b": 1} and model["unexpected_calls"] == 0
        return {"local_lane_rejected": True, "same_candidate_accepted_by_peer": True,
                "owners": [reservation_a["owner"], reservation_b["owner"]], "model_calls": model["calls_by_tag"]}


def exercise_agent_backlog(url_a, url_b, stable_url, identity, agent, token, *, control, snapshot, capacity,
                           wait_seconds, expected_hosts=None):
    timeout = min(wait_seconds, 60)
    with ExitStack() as stack:
        clients = [stack.enter_context(httpx.Client(base_url=url, timeout=httpx.Timeout(15, read=120), trust_env=False))
                   for url in (url_a, url_b, stable_url)]
        first, peer, stable = clients
        auth = sign_in(stable, identity)
        tags = ("agent-lane-holder", "agent-lane-queued", "agent-lane-overflow")
        holder, queued, overflow = tags
        ids = dict(zip(tags, new_conversations(stable, auth, len(tags)), strict=True))

        def post(client, tag):
            agent_id = agent["other_agent_id" if tag == overflow else "agent_id"]
            return client.post(RUN_PATH, headers=auth, json={"agent_id": agent_id, "model_id": agent["model_id"],
                               "conversation_id": ids[tag], "query": f"runtime-stream:{token}:{tag}",
                               "history": [], "stream_cursor": True})

        def states():
            observed = snapshot(*ids.values())
            assert observed["agent_limit"] == 2
            return {tag: observed["conversations"][str(identifier)] for tag, identifier in ids.items()}

        def calls():
            observed = control("probe")
            assert observed["unexpected_calls"] == 0, observed
            return observed["calls_by_tag"]

        def occupancy(lane):
            assert (lane["max_workers"], lane["max_queue_size"]) == (1, 1), lane
            assert lane["active_count"] == lane["running_count"] + lane["queued_count"], lane
            return lane["running_count"], lane["queued_count"], lane["available_count"]

        left, right = capacity("a"), capacity("b")
        assert occupancy(left) == occupancy(right) == (0, 0, 2)
        for row in states().values():
            assert_unstarted(row)
        assert not calls()

        with ThreadPoolExecutor(max_workers=3) as executor:
            try:
                holder_request = executor.submit(post, first, holder)
                wait_for(lambda: calls() == {holder: 1}, timeout, "The holder did not reach the controlled model")
                held, = states()[holder]["reservations"]
                assert held["status"] == "RUNNING"
                queued_request = executor.submit(post, first, queued)
                wait_for(lambda: occupancy(capacity("a")) == (1, 1, 0), timeout, "Agent backlog did not fill on A")
                assert not queued_request.done() and capacity("b") == right
                before = states()
                for tag in (queued, overflow):
                    assert_unstarted(before[tag])

                assert_admission_rejection(post(first, overflow), 429, "RUNTIME_CAPACITY_FULL")
                saturated = capacity("a")
                assert occupancy(saturated) == (1, 1, 0) and saturated["rejected_count"] == left["rejected_count"] + 1
                assert states() == before and calls() == {holder: 1}

                peer_request = executor.submit(post, peer, overflow)
                wait_for(lambda: calls() == {holder: 1, overflow: 1}, timeout, "The peer did not accept the same request")
                current = states()
                admitted, = current[overflow]["reservations"]
                assert admitted["status"] == "RUNNING" and admitted["agent_scope"] != held["agent_scope"]
                assert admitted["owner"] != held["owner"]
                if expected_hosts is not None:
                    assert tuple(row["owner"].split(":", 1)[0] for row in (held, admitted)) == expected_hosts
                assert current[queued] == before[queued] and current[holder] == before[holder]
                assert capacity("a") == saturated and occupancy(capacity("b")) == (1, 0, 1)
                assert not queued_request.done()

                assert control(f"release/{holder}") == {"released": True}
                wait_for(lambda: calls() == dict.fromkeys(tags, 1), timeout, "A did not start its own queued request")
                local, = states()[queued]["reservations"]
                assert local["status"] == "RUNNING" and local["owner"] == held["owner"]
                assert local["agent_scope"] == held["agent_scope"]
            finally:
                assert control("release") == {"released": True}

            for tag, future, reservation in zip(tags, (holder_request, queued_request, peer_request),
                                                (held, local, admitted), strict=True):
                frames = check_stream(future.result(timeout=timeout), ids[tag])
                generation = stream_prefix(frames, tag)
                assert generation == f"execution:{reservation['id']}"
                stream_completion(frames, generation, tag)

        def settled():
            rows = states()
            return rows if all([record["status"] for record in row["reservations"]] == ["COMPLETED"]
                               for row in rows.values()) else None

        completed = wait_for(settled, timeout, "The Agent lane executions did not settle")
        for tag, identifier in ids.items():
            assert completed[tag]["messages"] == [f"runtime-stream:{token}:{tag}"]
            history = conversation_history(stable, auth, identifier)
            assistant, = (message for message in history["message"] if message["role"] == "assistant")
            assert_persisted_answer(stable, auth, identifier, assistant["message_id"], tag)
            path = f"/api/conversation/{identifier}"
            require_status(stable.delete(path, headers=auth), 200, "Delete the owned conversation")
            assert stable.get(path, headers=auth).json()["data"] == []
        wait_for(lambda: all(occupancy(capacity(slot)) == (0, 0, 2) for slot in ("a", "b")), timeout,
                 "The two Agent lanes did not return to idle")
        assert calls() == dict.fromkeys(tags, 1)
        return {"saturated_lane": [1, 1, 0], "rejections": 1, "queued_execution": local["id"],
                "owners": {holder: held["owner"], queued: local["owner"], overflow: admitted["owner"]},
                "model_calls": calls()}


def exercise_agent_preparation_failure(url_a, url_b, stable_url, identity, agent, token, *, control, snapshot,
                                       capacity, fault_probe, fault_kind, wait_seconds, expected_hosts=None):
    expected_status = {"message-write": 500, "stream-reset": 503}[fault_kind]
    timeout = min(wait_seconds, 60)
    with ExitStack() as stack:
        first, peer, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=httpx.Timeout(15, read=120),
                                                               trust_env=False))
                               for url in (url_a, url_b, stable_url)]
        auth = sign_in(stable, identity)
        holder, candidate = new_conversations(stable, auth, 2)
        holder_tag, recovery_tag = "prepare-fault-holder", "prepare-fault-retry"

        def payload(identifier, tag):
            return {**agent, "conversation_id": identifier, "query": f"runtime-stream:{token}:{tag}",
                    "history": [], "stream_cursor": True}

        def state():
            observed = snapshot(holder, candidate)
            assert observed["agent_limit"] == 2
            rows = observed["conversations"]
            return rows[str(holder)], rows[str(candidate)]

        def calls():
            observed = control("probe")
            assert observed["unexpected_calls"] == 0, observed
            return observed["calls_by_tag"]

        for row in state():
            assert_unstarted(row)
        assert capacity("a")["active_count"] == 0
        try:
            holding = stack.enter_context(peer.stream("POST", RUN_PATH, headers=auth, json=payload(holder, holder_tag)))
            holder_frames = check_stream(holding, holder)
            holder_generation = stream_prefix(holder_frames, holder_tag)
            held, unstarted = state()
            original, = held["reservations"]
            assert original["status"] == "RUNNING" and holder_generation == f"execution:{original['id']}"
            assert_unstarted(unstarted)

            try:
                installed = fault_probe("install", candidate)
                assert installed["installed"] is True
                with first.stream("POST", RUN_PATH, headers=auth, json=payload(candidate, recovery_tag)) as response:
                    require_status(response, expected_status, f"Agent preparation failure ({fault_kind})")
                    assert response.headers["content-type"].startswith("application/json")
                    if fault_kind == "stream-reset":
                        response.read()
                        assert_admission_rejection(response, expected_status, "RUNTIME_COORDINATION_UNAVAILABLE")
            finally:
                removed = fault_probe("remove", candidate)
                assert removed["installed"] is False
            if fault_kind == "stream-reset":
                assert removed["removed_marker"] is True
                assert removed["wrongtype_errors"] > installed["wrongtype_errors"], (installed, removed)

            def compensated():
                surviving, attempt = state()
                assert surviving == held
                record, = attempt["reservations"]
                assert record["status"] in {"PREPARING", "FAILED"}, record
                return attempt if record["status"] == "FAILED" else None

            failed_state = wait_for(compensated, timeout, "Failed preparation did not settle its durable reservation")
            failed, = failed_state["reservations"]
            assert failed["owner"] != original["owner"] and failed["agent_scope"] == original["agent_scope"]
            if expected_hosts is not None:
                assert tuple(row["owner"].split(":", 1)[0] for row in (failed, original)) == expected_hosts
            assert not failed_state["messages"] and not failed_state["event_ids"]
            if fault_kind == "stream-reset":
                assert not failed_state["stream"]
            assert conversation_history(stable, auth, candidate)["message"] == []
            assert calls() == {holder_tag: 1}
            wait_for(lambda: capacity("a")["active_count"] == 0, timeout, "The failed Runtime worker did not exit")

            retry = stack.enter_context(peer.stream("POST", RUN_PATH, headers=auth, json=payload(candidate, recovery_tag)))
            retry_frames = check_stream(retry, candidate)
            retry_generation = stream_prefix(retry_frames, recovery_tag)
            surviving, readmitted = state()
            failure, recovered = readmitted["reservations"]
            assert surviving == held and failure == failed
            assert recovered["status"] == "RUNNING" and recovered["owner"] == original["owner"]
            assert recovered["agent_scope"] == original["agent_scope"] and recovered["id"] != failed["id"]
            assert readmitted["stream"]["generation"] == retry_generation == f"execution:{recovered['id']}"
        finally:
            assert control("release") == {"released": True}

        stream_completion(holder_frames, holder_generation, holder_tag)
        stream_completion(retry_frames, retry_generation, recovery_tag)

        def settled():
            completed, retried = state()
            return ([row["status"] for row in completed["reservations"]] == ["COMPLETED"]
                    and retried["reservations"] == [failed, {**recovered, "status": "COMPLETED"}])

        wait_for(settled, timeout, "The holder and readmitted execution did not settle independently")
        for identifier, tag, row in zip((holder, candidate), (holder_tag, recovery_tag), state(), strict=True):
            assert row["messages"] == [f"runtime-stream:{token}:{tag}"]
            history = conversation_history(stable, auth, identifier)
            assistant, = (message for message in history["message"] if message["role"] == "assistant")
            assert_persisted_answer(stable, auth, identifier, assistant["message_id"], tag)
            path = f"/api/conversation/{identifier}"
            require_status(stable.delete(path, headers=auth), 200, "Delete the owned conversation")
            assert stable.get(path, headers=auth).json()["data"] == []
        wait_for(lambda: all(capacity(slot)["active_count"] == 0 for slot in ("a", "b")), timeout,
                 "The Agent lanes did not return to idle")
        assert calls() == {holder_tag: 1, recovery_tag: 1}
        return {"fault": fault_kind, "http_failure": response.status_code, "failed_execution": failed["id"],
                "recovered_execution": recovered["id"], "original_owner": failed["owner"],
                "retry_owner": recovered["owner"], "fault_cleanup": removed, "model_calls": calls()}


def exercise_public_transport_failure(web_url, gateway_url, identity, api_key, agent, token, *,
                                      transport, control, snapshot, wait_seconds, expected_hosts=None):
    with ExitStack() as stack:
        web, gateway = [stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds, trust_env=False))
                        for url in (web_url, gateway_url)]
        authorization = sign_in(gateway, identity)
        identifiers = new_conversations(web, authorization, 2)
        evidence = {}
        calls = {}
        for index, (client, path, auth, selector, tag, identifier) in enumerate(zip(
            (web, gateway), (RUN_PATH, NORTHBOUND_RUN), (authorization, {"Authorization": f"Bearer {api_key}"}),
            ({"agent_id": agent["agent_id"], "history": []}, {"agent_name": FIXTURE_AGENT_NAME}),
            ("web-cut", "northbound-cut"), identifiers, strict=True,
        )):
            query = f"runtime-stream:{token}:{tag}"
            payload = {**selector, "model_id": agent["model_id"], "conversation_id": identifier,
                       "query": query, "stream_cursor": True}

            def state():
                return snapshot(identifier)["conversations"][str(identifier)]

            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(client.post, path, headers=auth, json=payload)
                try:
                    def observed_prefix():
                        assert not pending.done(), "The proxy returned before the fixture cut the upstream transport"
                        receipt = transport("probe")[tag]
                        return receipt if receipt["prefix_observed"] else None

                    prefix = wait_for(observed_prefix, wait_seconds, "No real Runtime SSE prefix reached the relay")
                    assert prefix == {"attempts": 1, "prefix_observed": True, "transport_aborted": False}
                    active = state()
                    reservation, = active["reservations"]
                    assert reservation["status"] == "RUNNING" and active["messages"] == [query] and active["event_ids"]
                    assert active["stream"]["generation"] == f"execution:{reservation['id']}"
                    if expected_hosts is not None:
                        assert reservation["owner"].split(":", 1)[0] == expected_hosts[index]
                    assistant = conversation_history(web, authorization, identifier)["streaming_message"]
                    assert assistant["status"] == "streaming"
                    calls[tag] = 1
                    assert control("probe")["calls_by_tag"] == calls

                    assert transport(f"cut/{tag}") == {"cut_requested": True}
                    response = pending.result(timeout=wait_seconds)
                    receipt = transport("probe")[tag]
                    assert receipt == {"attempts": 1, "prefix_observed": True, "transport_aborted": True}, receipt
                    require_status(response, 502, "The proxy reports a lost Runtime connection before headers")
                    assert state() == active, "A response transport failure changed the still-active execution"
                    assert control(f"release/{tag}")["released"] is True
                except BaseException:
                    control("release")
                    raise

            def settled():
                current = state()
                row, = current["reservations"]
                assert row["id"] == reservation["id"] and row["owner"] == reservation["owner"]
                return current if row["status"] == "COMPLETED" else None

            completed = wait_for(settled, wait_seconds, "The original worker did not settle after upstream disconnect")
            assert completed["messages"] == [query]
            history = conversation_history(web, authorization, identifier)
            persisted, = [message for message in history["message"] if message["role"] == "assistant"]
            assert persisted["message_id"] == assistant["message_id"]
            assert_persisted_answer(web, authorization, identifier, assistant["message_id"], tag)
            evidence[tag] = {**receipt, "status": response.status_code, "execution_id": reservation["id"],
                             "owner": reservation["owner"], "original_answer_persisted": True}

        assert transport("probe") == {tag: {"attempts": 1, "prefix_observed": True, "transport_aborted": True}
                                        for tag in evidence}
        model = control("probe")
        assert model["calls_by_tag"] == calls and model["unexpected_calls"] == 0
        for identifier in identifiers:
            path = f"/api/conversation/{identifier}"
            require_status(web.delete(path, headers=authorization), 200, "Delete the owned conversation")
            assert web.get(path, headers=authorization).json()["data"] == []
        return {"proxy_receipts": evidence, "model_calls": calls, "owned_conversations_deleted": True}
