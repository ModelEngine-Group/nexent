# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise Workbench admission on independently routed Runtime producers."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from threading import Barrier

import httpx

from shared.runtime_scaling_admission import assert_conflict, assert_unstarted, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_public_admission import assert_admission_rejection, stream_prefix
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, check_stream, conversation_history


def exercise_workbench_admission(url_a, url_b, stable_url, identities, prepared, token, *, control, snapshot,
                                 gate, replay_completion, wait_seconds, expected_hosts=None):
    timeout = min(wait_seconds, 90)
    with ExitStack() as stack:
        options = {"timeout": httpx.Timeout(timeout, connect=10), "trust_env": False}
        runtime_a, runtime_b, stable = [stack.enter_context(httpx.Client(base_url=url, **options))
                                        for url in (url_a, url_b, stable_url)]
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=2))
        stack.callback(control, "release")
        clients = {"race-a": runtime_a, "race-b": runtime_b}
        auth = {role: sign_in(stable, identity) for role, identity in identities.items()}

        def payload(role, label, tag):
            return {**prepared[role][label], "entrypoint": "workbench", "history": [], "stream_cursor": True,
                    "query": f"runtime-stream:{token}:{tag}"}

        def conversation_id(role, label):
            return prepared[role][label]["conversation_id"]

        def read(role):
            labels = prepared[role]
            batch = snapshot(role, *(conversation_id(role, label) for label in labels))
            assert batch["agent_limit"] == 2
            return {label: batch["conversations"][str(conversation_id(role, label))] for label in labels}

        def connect(target, role, label, tag, barrier=None):
            if barrier is not None:
                barrier.wait(timeout=10)
            request = payload(role, label, tag)
            with clients[target].stream("POST", RUN_PATH, headers=auth[role], json=request) as response:
                if response.headers.get("X-Stream-Status") == "conflict":
                    response.read()
                    assert_conflict(response)
                    return None
                return stream_prefix(check_stream(response, request["conversation_id"]), tag)

        def calls():
            observed = control("probe")
            assert observed["unexpected_calls"] == 0
            return observed["calls_by_tag"]

        assert expected_hosts is None or clients.keys() == expected_hosts.keys()
        owners = {}

        def active(role, label, tag, target, generation):
            row = read(role)[label]
            reservation, = row["reservations"]
            assert reservation["status"] == "running" and reservation["agent_scope"] == "workbench_main"
            assert owners.setdefault(target, reservation["owner"]) == reservation["owner"]
            assert row["messages"] == [payload(role, label, tag)["query"]]
            assert generation == row["stream"]["generation"] == reservation["id"]
            assert row["event_ids"], "The model prefix must exist in the active stream"
            return row

        def assistant(role, label):
            history = conversation_history(stable, auth[role], conversation_id(role, label))
            message = history["streaming_message"]
            assert message["status"] == "streaming"
            return message["message_id"]

        def settle(role, label, tag, record, message_id, *, prior=()):
            def settled():
                *previous, observed = read(role)[label]["reservations"]
                assert tuple(previous) == prior
                assert observed["status"] not in {"failed", "stopped"}, observed
                return observed if observed["status"] == "completed" else None

            final = wait_for(settled, timeout, f"Workbench run {tag} did not settle")
            assert final == {**record, "status": "completed"}
            identifier = conversation_id(role, label)
            wait_for(lambda: any(message["message_id"] == message_id and message["status"] == "completed"
                                 for message in conversation_history(stable, auth[role], identifier)["message"]),
                     timeout, "Workbench assistant projection did not finish")
            assert_persisted_answer(stable, auth[role], identifier, message_id, tag)

        def complete(role, label, tag, record, message_id):
            assert control(f"release/{tag}") == {"released": True}
            settle(role, label, tag, record, message_id)

        def require_full_quota(prefix):
            for target, client in clients.items():
                request = payload("owner", "candidate", f"{prefix}-{target}")
                with client.stream("POST", RUN_PATH, headers=auth["owner"], json=request) as response:
                    if response.status_code == 429:
                        response.read()
                    assert_admission_rejection(response, 429, "RUNTIME_CAPACITY_FULL")
                assert_unstarted(read("owner")["candidate"])

        @contextmanager
        def held_finalization(identifier, tag):
            finalization = executor.submit(gate, "hold", identifier)
            try:
                def stage():
                    if finalization.done():
                        finalization.result()
                        raise AssertionError("The Workbench finalization gate closed before release")
                    return gate("probe", identifier)["stage"]

                wait_for(lambda: stage() == "ready", min(timeout, 25), "The Workbench history row was not locked")
                assert control(f"release/{tag}") == {"released": True}
                wait_for(lambda: stage() == "blocked", min(timeout, 30), "The assistant projection did not wait for its row")
                yield
            finally:
                assert gate("release", identifier) == {"released": True}
            assert finalization.result(timeout=timeout) == {"assistant_projection_blocked": True}

        for role in prepared:
            for row in read(role).values():
                assert_unstarted(row)

        barrier = Barrier(2)
        racers = {target: executor.submit(connect, target, "owner", "contested", target, barrier)
                  for target in clients}
        outcomes = {target: future.result(timeout=timeout) for target, future in racers.items()}
        winner, = (target for target, generation in outcomes.items() if generation is not None)
        loser, = clients.keys() - {winner}
        first = active("owner", "contested", winner, winner, outcomes[winner])
        first_assistant = assistant("owner", "contested")
        assert calls() == {winner: 1}
        assert connect(loser, "owner", "contested", "repeat-conflict") is None
        held = active("owner", "contested", winner, winner, outcomes[winner])
        assert held["reservations"] == first["reservations"]
        assert held["event_ids"][:len(first["event_ids"])] == first["event_ids"]
        assert assistant("owner", "contested") == first_assistant

        second_generation = connect(loser, "owner", "second", "second-slot")
        second = active("owner", "second", "second-slot", loser, second_generation)
        second_assistant = assistant("owner", "second")
        assert first["reservations"][0]["owner"] != second["reservations"][0]["owner"]
        require_full_quota("quota")
        assert calls() == {winner: 1, "second-slot": 1}

        foreign_generation = connect(loser, "foreign", "isolated", "foreign-tenant")
        foreign = active("foreign", "isolated", "foreign-tenant", loser, foreign_generation)
        foreign_assistant = assistant("foreign", "isolated")
        active("owner", "contested", winner, winner, outcomes[winner])
        active("owner", "second", "second-slot", loser, second_generation)

        contested = conversation_id("owner", "contested")
        with held_finalization(contested, winner):
            finisher = read("owner")["contested"]
            assert finisher["reservations"] == [{**first["reservations"][0], "status": "completed"}]
            assert finisher["messages"] == first["messages"]
            assert finisher["stream"]["generation"] == outcomes[winner]
            assert assistant("owner", "contested") == first_assistant
            assert read("owner")["contested"] == finisher
            active("owner", "second", "second-slot", loser, second_generation)
            assert calls() == {winner: 1, "second-slot": 1, "foreign-tenant": 1}
        settle("owner", "contested", winner, first["reservations"][0], first_assistant)
        candidate_generation = connect(loser, "owner", "candidate", "after-release")
        candidate = active("owner", "candidate", "after-release", loser, candidate_generation)
        active("owner", "second", "second-slot", loser, second_generation)
        complete("owner", "candidate", "after-release", candidate["reservations"][0], assistant("owner", "candidate"))
        complete("owner", "second", "second-slot", second["reservations"][0], second_assistant)
        complete("foreign", "isolated", "foreign-tenant", foreign["reservations"][0], foreign_assistant)
        assert calls() == {winner: 1, "second-slot": 1, "foreign-tenant": 1, "after-release": 1}

        prior = {**first["reservations"][0], "status": "completed"}
        successor_generation = connect(loser, "owner", "contested", "successor")
        successor_assistant = assistant("owner", "contested")
        successor_state = read("owner")["contested"]
        old, successor = successor_state["reservations"]
        assert old == prior and successor["status"] == "running" and successor_assistant != first_assistant
        assert successor["owner"] == second["reservations"][0]["owner"] and successor["owner"] != prior["owner"]
        assert successor_generation == successor_state["stream"]["generation"] == successor["id"]
        assert successor_state["messages"] == [*first["messages"], payload("owner", "contested", "successor")["query"]]

        receipt = replay_completion(winner, contested, prior["id"])
        assert receipt == {"duplicate_completions_ignored": 2, "wrong_owner_rejected": True,
                           "old_execution_id": prior["id"], "surviving_execution_id": successor["id"]}
        assert read("owner")["contested"] == successor_state
        with held_finalization(contested, "successor"):
            projected = read("owner")["contested"]
            assert projected["reservations"] == [prior, {**successor, "status": "completed"}]
            assert assistant("owner", "contested") == successor_assistant

        settle("owner", "contested", "successor", successor, successor_assistant, prior=(prior,))
        assert_persisted_answer(stable, auth["owner"], contested, first_assistant, winner)
        assert calls() == {winner: 1, "second-slot": 1, "foreign-tenant": 1, "after-release": 1, "successor": 1}

        for role, labels in prepared.items():
            for label in labels:
                path = f"/api/conversation/{conversation_id(role, label)}"
                require_status(stable.delete(path, headers=auth[role]), 200, "Delete the owned Workbench conversation")
                deleted = stable.get(path, headers=auth[role])
                require_status(deleted, 200, "Check deleted Workbench conversation")
                assert deleted.json()["data"] == []
        return {"model_calls": calls(), "quota_rejections": 2, "conflict_attempts": 2,
                "assistant_projection_blocked": True,
                "completion_replay": receipt,
                "sse_disconnected_while_active": True, "same_scope_tenant_isolation": True, "readmission": True,
                "owners": [row["reservations"][0]["owner"] for row in (first, second)]}
