# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Drive real scheduled and manual Agent runs on independently routed Runtime instances."""

from contextlib import ExitStack
from datetime import datetime

import httpx

from shared.runtime_scaling_admission import assert_conflict, new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, conversation_history, read_prefix


AUTOMATION_PATH = "/api/agent/automations"


def active_automation(state, seed, prior_runs=()):
    task, runs = state["task"], state["runs"]
    assert runs[:-1] == list(prior_runs)
    run, = runs[len(prior_runs):]
    reservation, = state["reservations"]
    assert task["task_id"] == seed["task_id"] and task["status"] == "ACTIVE"
    assert task["next_fire_at"] == run["scheduled_fire_at"] == seed["scheduled"]
    assert task["fire_count"] == 0 and task["lock_owner"] and task["lock_until"]
    assert run["status"] == reservation["status"] == "RUNNING" and run["trigger_type"] == "SCHEDULED"
    assert task["lock_owner"].rsplit("-", 5)[0] == reservation["owner_instance_id"].split(":")[0]
    return task, run, reservation


def check_settled_schedule(state, seed, status, prior_runs=()):
    task = state["task"]
    runs = state["runs"]
    assert runs[:-1] == list(prior_runs)
    run, = runs[len(prior_runs):]
    assert task["task_id"] == seed["task_id"] and task["status"] == "COMPLETED"
    assert run["status"] == status and run["trigger_type"] == "SCHEDULED"
    assert run["scheduled_fire_at"] == seed["scheduled"] and run["finished_at"]
    assert (task["fire_count"], task["next_fire_at"], task["lock_owner"], task["lock_until"]) == (1, None, None, None)
    return run


def exercise_live_lease_loss(identifier, seed, held, *, snapshot, probe, control, wait_seconds):
    task, run, reservation = active_automation(held, seed)
    fault = probe("expire-live", identifier, run["run_id"], reservation["execution_id"])
    assert fault["owner"] == task["lock_owner"]

    def skipped_while_live():
        state = snapshot(identifier)
        return state if state["task"]["fire_count"] == 1 else None

    skipped = wait_for(skipped_while_live, wait_seconds, "The peer did not settle the reclaimed occurrence")
    timed_out, replay = skipped["runs"]
    assert timed_out["run_id"] == run["run_id"] and timed_out["status"] == "TIMEOUT"
    assert timed_out["error_code"] == "AUTOMATION_LEASE_EXPIRED"
    assert replay["trigger_type"] == "SCHEDULED" and replay["scheduled_fire_at"] == seed["scheduled"]
    assert replay["status"] == "SKIPPED" and replay["error_code"] == "AUTOMATION_RUN_ALREADY_ACTIVE"
    assert replay["user_message_id"] is None and replay["assistant_message_id"] is None
    assert datetime.fromisoformat(fault["expired_at"]) <= datetime.fromisoformat(replay["actual_fire_at"]) < (
        datetime.fromisoformat(fault["claim_before"])
    ), "The old single-slot scheduler could have freed its slot and reclaimed the occurrence itself"
    assert skipped["reservations"] == [reservation] and skipped["messages"] == held["messages"]
    assert control("probe")["calls_by_tag"]["auto"] == 1
    recurring_task = skipped["task"]
    following_fire = recurring_task["next_fire_at"]
    assert following_fire and datetime.fromisoformat(following_fire) > datetime.fromisoformat(seed["scheduled"])
    assert (recurring_task["status"], recurring_task["lock_owner"], recurring_task["lock_until"]) == ("ACTIVE", None, None)

    def cancellation_started():
        state = snapshot(identifier)
        old = state["reservations"][0]
        return old["status"] in {"FINALIZING", "STOPPED"}

    wait_for(cancellation_started, wait_seconds, "The old scheduler did not stop its worker after losing the lease")
    assert control("release/auto")["released"] is True

    def completed_next_occurrence():
        state = snapshot(identifier)
        return state if state["task"]["fire_count"] == 2 and all(
            row["status"] in {"STOPPED", "COMPLETED"} for row in state["reservations"]
        ) else None

    completed = wait_for(completed_next_occurrence, max(wait_seconds, 75),
                         "The original worker did not settle or the next regular occurrence did not finish")
    assert completed["runs"][:2] == [timed_out, replay], "The stale worker rewrote a settled occurrence"
    final_run, = completed["runs"][2:]
    assert final_run["status"] == "SUCCEEDED" and final_run["trigger_type"] == "SCHEDULED"
    assert final_run["scheduled_fire_at"] == following_fire and final_run["finished_at"]
    old, new = completed["reservations"]
    assert old["execution_id"] == reservation["execution_id"] and old["status"] == "STOPPED"
    assert new["execution_id"] != old["execution_id"] and new["status"] == "COMPLETED"
    final_task = completed["task"]
    assert final_task["task_id"] == seed["task_id"] and final_task["status"] == "COMPLETED"
    assert not any(final_task[key] for key in ("next_fire_at", "lock_owner", "lock_until"))
    return completed, final_run, {"expired_run": timed_out["run_id"], "replay_skipped": replay["run_id"],
                                  "next_occurrence": final_run["run_id"], "old_execution": old["execution_id"]}


def exercise_settled_lease_loss(identifier, seed, *, snapshot, probe, control, wait_seconds):
    wait_for(lambda: control("probe")["calls_by_tag"].get("settled") == 1, wait_seconds,
             "The first occurrence did not reach the provider")
    held = snapshot(identifier)
    _, started, reservation = active_automation(held, seed)
    assert started["user_message_id"] is not None
    assert probe("park-settled", identifier)["parked"] is True
    assert control("release/settled")["released"] is True

    def original_worker_exited():
        state = snapshot(identifier)
        terminal = state["reservations"][0]["status"] in {"COMPLETED", "FAILED", "STOPPED"}
        return state if terminal and state["task"]["lock_owner"] is None else None

    terminal = wait_for(original_worker_exited, wait_seconds, "The old root execution still owns the conversation")
    assert terminal["task"]["status"] == "PAUSED" and terminal["runs"][0]["status"] == "RUNNING"
    original, = terminal["reservations"]
    assert original["execution_id"] == reservation["execution_id"]
    assert probe("rearm-settled", identifier)["rearmed"] is True

    def first_fire_settled():
        state = snapshot(identifier)
        return state if state["task"]["fire_count"] == 1 else None

    skipped = wait_for(first_fire_settled, wait_seconds, "The expired occurrence did not advance")
    timed_out, replay = skipped["runs"]
    assert timed_out["run_id"] == started["run_id"] and timed_out["error_code"] == "AUTOMATION_LEASE_EXPIRED"
    assert replay["scheduled_fire_at"] == seed["scheduled"]
    assert (replay["status"], replay["error_code"]) == ("SKIPPED", "AUTOMATION_OCCURRENCE_ALREADY_STARTED"), (
        "A reclaimed occurrence invoked the model again after the original worker exited"
    )
    assert replay["user_message_id"] is None and replay["assistant_message_id"] is None
    assert skipped["reservations"] == [original] and skipped["messages"] == terminal["messages"]
    assert control("probe")["calls_by_tag"]["settled"] == 1
    next_fire = skipped["task"]["next_fire_at"]
    assert datetime.fromisoformat(next_fire) > datetime.fromisoformat(seed["scheduled"])

    def next_fire_settled():
        state = snapshot(identifier)
        return state if state["task"]["fire_count"] == 2 and state["reservations"][-1]["status"] == "COMPLETED" else None

    completed = wait_for(next_fire_settled, max(wait_seconds, 75), "The subsequent legal occurrence did not finish")
    assert completed["runs"][:2] == [timed_out, replay] and completed["reservations"][0] == original
    next_run, = completed["runs"][2:]
    assert next_run["status"] == "SUCCEEDED" and next_run["scheduled_fire_at"] == next_fire
    assert control("probe")["calls_by_tag"]["settled"] == 2
    return completed, {"original": timed_out["run_id"], "skipped": replay["run_id"], "next": next_run["run_id"]}


def exercise_scheduler(urls, stable_url, identity, agent, token, *, control, probe, contest, slot_for_owner, restart_peer,
                       wait_seconds):
    with ExitStack() as stack:
        stack.callback(control, "release")
        runtimes = {name: stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds, trust_env=False))
                    for name, url in urls.items()}
        stable = stack.enter_context(httpx.Client(base_url=stable_url, timeout=wait_seconds, trust_env=False))
        authorization = sign_in(stable, identity)
        auto_conversation, manual_conversation, pending_conversation, race_conversation, settled_conversation = (
            new_conversations(stable, authorization, 5)
        )

        def query(tag):
            return f"runtime-stream:{token}:{tag}"

        def payload(identifier, tag):
            return {**agent, "conversation_id": identifier, "query": query(tag), "history": [], "stream_cursor": True}

        def snapshot(identifier):
            return probe("snapshot", identifier)

        def settled(identifier, status):
            state = snapshot(identifier)
            return state if any(row["status"] == status for row in state["runs"]) else None

        def seed(identifier, tag):
            return probe("seed", identifier, tag, agent["agent_id"], agent["model_id"])

        assert snapshot(auto_conversation)["scheduler_capacity"] == 1
        auto_seed = seed(auto_conversation, "auto")
        wait_for(lambda: control("probe")["calls_by_tag"].get("auto") == 1, wait_seconds,
                 "No scheduler made the expected model call for the due occurrence")
        held = snapshot(auto_conversation)
        task, run, reservation = active_automation(held, auto_seed)
        winner = slot_for_owner(task["lock_owner"])
        peer, = set(runtimes) - {winner}
        assert_conflict(runtimes[peer].post(RUN_PATH, headers=authorization,
                                            json=payload(auto_conversation, "manual-rejected")))
        assert snapshot(auto_conversation)["messages"] == held["messages"]

        _, manual_generation = read_prefix(runtimes[winner], authorization,
                                           payload(manual_conversation, "manual"), "manual")
        manual_before = snapshot(manual_conversation)
        manual_reservation, = manual_before["reservations"]
        assert manual_generation == f"execution:{manual_reservation['execution_id']}"
        assert manual_reservation["owner_instance_id"] == reservation["owner_instance_id"]
        busy_seed = seed(manual_conversation, "busy")
        skipped = wait_for(lambda: settled(manual_conversation, "SKIPPED"), wait_seconds,
                           "The other scheduler did not report a busy occurrence")
        skipped_run = check_settled_schedule(skipped, busy_seed, "SKIPPED")
        assert skipped_run["error_code"] == "AUTOMATION_RUN_ALREADY_ACTIVE"
        assert skipped_run["user_message_id"] is None and skipped_run["assistant_message_id"] is None
        assert skipped["reservations"] == manual_before["reservations"]
        assert skipped["messages"] == manual_before["messages"]
        assert control("probe")["calls_by_tag"] == {"auto": 1, "manual": 1}
        assert control("release/manual")["released"] is True
        manual_assistant, = [message for message in skipped["messages"] if message["message_role"] == "assistant"]
        manual_id = manual_assistant["message_id"]
        wait_for(lambda: any(message["message_id"] == manual_id and message["status"] == "completed"
                             for message in conversation_history(stable, authorization, manual_conversation)["message"]),
                 wait_seconds, "The manual Agent did not finish after the conflicting scheduled occurrence")
        assert_persisted_answer(stable, authorization, manual_conversation, manual_id, "manual")

        def lease_expiry():
            observed = snapshot(auto_conversation)
            current_task, current_run, current_reservation = active_automation(observed, auto_seed)
            assert current_task["lock_owner"] == task["lock_owner"]
            assert current_run == run and current_reservation == reservation and observed["messages"] == held["messages"]
            return datetime.fromisoformat(current_task["lock_until"])

        pending_seed = seed(pending_conversation, "pending")
        pending_before = snapshot(pending_conversation)
        assert pending_before["task"]["lock_owner"] == pending_seed["fixture_lock"]
        assert pending_before["task"]["next_fire_at"] == pending_seed["scheduled"]
        assert not any(pending_before[key] for key in ("runs", "reservations", "messages"))
        before_restart = lease_expiry()
        replacement = restart_peer(peer)
        after_restart = lease_expiry()
        assert after_restart >= before_restart
        assert snapshot(pending_conversation) == pending_before, "Peer startup changed the due occurrence"
        wait_for(lambda: lease_expiry() > after_restart, min(wait_seconds, 60),
                 "The active owner did not renew its lease after peer startup")
        assert control("probe")["calls_by_tag"] == {"auto": 1, "manual": 1}
        assert probe("unblock", pending_conversation)["unblocked"] is True
        wait_for(lambda: control("probe")["calls_by_tag"].get("pending") == 1, wait_seconds,
                 "The restarted scheduler skipped a recurring occurrence that was due before its own startup")
        pending_task, pending_active, _ = active_automation(snapshot(pending_conversation), pending_seed)
        assert slot_for_owner(pending_task["lock_owner"]) == replacement["scheduler_slot"] != winner

        lease_expiry()
        race_seed = seed(race_conversation, "race")
        contenders = contest(race_conversation)
        assert {record["actor"] for record in contenders} == {"first", "second"} and len(contenders) == 2
        assert all(record["released_from_barrier"] for record in contenders)
        accepted, = (record for record in contenders if record["claimed"])
        raced = snapshot(race_conversation)
        assert raced["task"]["lock_owner"] == accepted["owner"]
        assert not any(raced[key] for key in ("runs", "reservations", "messages"))
        fault = probe("reclaim", race_conversation, accepted["actor"])
        rejected = snapshot(race_conversation)
        expired_run, = rejected["runs"]
        assert expired_run["run_id"] == fault["expired_run_id"] and expired_run["status"] == "TIMEOUT"
        assert not rejected["reservations"] and not rejected["messages"]
        assert control("probe")["calls_by_tag"] == {"auto": 1, "manual": 1, "pending": 1}
        assert control("release/pending")["released"] is True
        pending_completed = wait_for(lambda: settled(pending_conversation, "SUCCEEDED"), wait_seconds,
                                     "The restarted scheduler did not finish the previously due occurrence")
        pending_run = check_settled_schedule(pending_completed, pending_seed, "SUCCEEDED")
        assert pending_run["run_id"] == pending_active["run_id"]
        assert_persisted_answer(stable, authorization, pending_conversation, pending_run["assistant_message_id"],
                                "pending")

        wait_for(lambda: control("probe")["calls_by_tag"].get("race") == 1, wait_seconds,
                 "The legitimate scheduler did not execute the recovered occurrence")
        race_task, race_active, _ = active_automation(snapshot(race_conversation), race_seed, (expired_run,))
        assert slot_for_owner(race_task["lock_owner"]) == replacement["scheduler_slot"]
        assert control("release/race")["released"] is True
        race_completed = wait_for(lambda: settled(race_conversation, "SUCCEEDED"), wait_seconds,
                                  "The recovered occurrence did not persist success")
        race_run = check_settled_schedule(race_completed, race_seed, "SUCCEEDED", (expired_run,))
        assert race_run["run_id"] == race_active["run_id"]
        assert_persisted_answer(stable, authorization, race_conversation, race_run["assistant_message_id"], "race")
        lease_expiry()
        completed, final_run, live_loss = exercise_live_lease_loss(
            auto_conversation, auto_seed, held, snapshot=snapshot, probe=probe, control=control,
            wait_seconds=wait_seconds,
        )
        assert_persisted_answer(stable, authorization, auto_conversation, final_run["assistant_message_id"], "auto")
        manual_completed = snapshot(manual_conversation)
        assert [(row["execution_id"], row["status"]) for row in manual_completed["reservations"]] == [
            (manual_reservation["execution_id"], "COMPLETED"),
        ]
        settled_completed, settled_loss = exercise_settled_lease_loss(
            settled_conversation, seed(settled_conversation, "settled"), snapshot=snapshot, probe=probe,
            control=control, wait_seconds=wait_seconds,
        )
        for identifier, tag, state in ((auto_conversation, "auto", completed),
                                       (manual_conversation, "manual", manual_completed),
                                       (pending_conversation, "pending", pending_completed),
                                       (race_conversation, "race", race_completed),
                                       (settled_conversation, "settled", settled_completed)):
            user_messages = [message for message in state["messages"] if message["message_role"] == "user"]
            source = "CHAT" if tag == "manual" else "AUTOMATION"
            assert [(message["message_content"], message["message_source"]) for message in user_messages] == [
                (query(tag), source),
            ] * (2 if tag in {"auto", "settled"} else 1)
            task_id = state["task"]["task_id"]
            require_status(stable.post(f"{AUTOMATION_PATH}/{task_id}/pause", headers=authorization), 200, "Pause task")
            run_paths = [f"{AUTOMATION_PATH}/runs/{row['run_id']}" for row in state["runs"]]
            for path in (*run_paths, f"{AUTOMATION_PATH}/{task_id}"):
                deleted = stable.delete(path, headers=authorization)
                require_status(deleted, 200, "Delete the owned automation resource")
                assert deleted.json()["data"] is True
            removed = snapshot(identifier)
            assert removed["task"] is None and not removed["runs"]
            history_path = f"/api/conversation/{identifier}"
            require_status(stable.delete(history_path, headers=authorization), 200, "Delete the owned conversation")
            assert stable.get(history_path, headers=authorization).json()["data"] == []

        model = control("probe")
        assert model["calls_by_tag"] == {"auto": 2, "manual": 1, "pending": 1, "race": 1, "settled": 2}
        assert model["unexpected_calls"] == 0
        return {"scheduler": winner, "peer_replacement": replacement, "successful_occurrence": final_run["run_id"],
                "skipped_occurrence": skipped_run["run_id"], "pending_occurrence": pending_run["run_id"],
                "same_row_claim_winner": accepted["actor"], "lease_loss": fault, "recovered_occurrence": race_run["run_id"],
                "live_worker_lease_loss": live_loss, "settled_worker_lease_loss": settled_loss,
                "model_calls": model["calls_by_tag"],
                "lease_renewed": True, "test_records_removed": True}
