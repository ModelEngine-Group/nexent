# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise two real Runtime evaluation workers against the same pending claim."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from shared.runtime_scaling_admission import wait_for


RACE_TAG = "admission-eval-race"
LOST_CLAIM_TAG = "admission-eval-lost-claim"
QUEUE_NAMES = tuple(f"admission-eval-queue-{index}" for index in range(1, 13))
OVERFLOW_TAG = "admission-eval-overflow"


def exercise_evaluation_admission(agent, *, probe, control, wait_seconds, expected_owners):
    timeout = min(wait_seconds, 70)
    race = probe("a", "seed-evaluation", agent["agent_id"], agent["model_id"], RACE_TAG)
    lost_claim = probe("a", "seed-evaluation", agent["agent_id"], agent["model_id"], LOST_CLAIM_TAG)

    def read(evaluation_id, tag):
        return probe("a", "admission-read", evaluation_id, tag)

    def dispatch(slot, evaluation_id, tag, barrier=None):
        if barrier is not None:
            barrier.wait(timeout=8)
        return probe(slot, "admission-dispatch", evaluation_id, tag)

    def model_calls():
        observed = control("probe")
        assert observed["unexpected_calls"] == 0
        return observed["calls_by_tag"]

    def wait_gate(gate, evaluation_id, tag):
        def ready():
            if gate.done():
                gate.result()
                raise AssertionError("The evaluation gate closed before dispatch")
            return probe("a", "admission-ready", evaluation_id, tag)["ready"]

        wait_for(ready, min(timeout, 30), "The scoped PostgreSQL evaluation gate did not become ready")

    initial, unclaimed = read(race, RACE_TAG), read(lost_claim, LOST_CLAIM_TAG)
    for state in (initial, unclaimed):
        assert state["run"]["status"] == state["case"]["status"] == "PENDING"
        assert state["run"]["progress"] == 0
    assert model_calls() == {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        try:
            gate = executor.submit(probe, "a", "admission-gate", race, RACE_TAG)
            wait_gate(gate, race, RACE_TAG)
            barrier = Barrier(2)
            futures = {slot: executor.submit(dispatch, slot, race, RACE_TAG, barrier) for slot in expected_owners}
            race_receipt = gate.result(timeout=timeout)
            assert race_receipt == {"waiting_claimants": 2, "mode": "race"}
            results = {slot: future.result(timeout=timeout) for slot, future in futures.items()}
            accepted = {"accepted": True, "agent_evaluation_id": race}
            winner, = (slot for slot, result in results.items() if result["status"] == 202 and result["body"] == accepted)
            loser, = results.keys() - {winner}
            assert results[loser]["status"] == 202 and results[loser]["body"] == {**accepted, "already_running": True}

            wait_for(lambda: model_calls() == {RACE_TAG: 1}, timeout, "The unique evaluation did not reach the model")
            held = read(race, RACE_TAG)
            assert held["run"] == {**initial["run"], "status": "RUNNING"}
            assert held["case"] == {**initial["case"], "status": "RUNNING"}
            assert dispatch(loser, race, RACE_TAG)["body"] == {**accepted, "already_running": True}
            assert read(race, RACE_TAG) == held and model_calls() == {RACE_TAG: 1}

            claimant_gate = executor.submit(probe, "a", "admission-gate", lost_claim, LOST_CLAIM_TAG)
            wait_gate(claimant_gate, lost_claim, LOST_CLAIM_TAG)
            claimant = executor.submit(dispatch, loser, lost_claim, LOST_CLAIM_TAG)
            claim_receipt = claimant_gate.result(timeout=timeout)
            assert claim_receipt == {"waiting_claimants": 1, "mode": "claim"}
            failed_dispatch = {"accepted": False, "already_finished": True, "status": "FAILED",
                               "agent_evaluation_id": lost_claim}
            assert claimant.result(timeout=timeout) == {
                "status": 409, "body": {"detail": "Agent evaluation run is no longer pending"}, "retry_after": None,
            }
            after_loss = read(lost_claim, LOST_CLAIM_TAG)
            assert after_loss == {**unclaimed, "run": {**unclaimed["run"], "status": "FAILED",
                                  "error": "Case changed the pending status while the conditional claim was waiting"}}
            assert dispatch(winner, lost_claim, LOST_CLAIM_TAG)["body"] == failed_dispatch
            assert read(race, RACE_TAG) == held and model_calls() == {RACE_TAG: 1}

            assert control(f"release/{RACE_TAG}") == {"released": True}

            def settled():
                observed = read(race, RACE_TAG)
                status = observed["run"]["status"]
                assert status != "FAILED", observed
                return observed if status == "COMPLETED" else None

            completed = wait_for(settled, timeout, "The winning evaluation did not settle")
            assert completed == {
                "run": {**held["run"], "status": "COMPLETED", "progress": 1, "score": 1.0},
                "case": {**held["case"], "status": "COMPLETED", "score": {f"Admission exact match: {RACE_TAG}": 1.0},
                         "predict": {"answer": f"stream-tail:{RACE_TAG}:结束🌊"}},
            }
            for slot in expected_owners:
                assert dispatch(slot, race, RACE_TAG)["body"] == {"accepted": False, "already_finished": True,
                                                          "status": "COMPLETED", "agent_evaluation_id": race}
            assert read(race, RACE_TAG) == completed and read(lost_claim, LOST_CLAIM_TAG) == after_loss
            assert model_calls() == {RACE_TAG: 1}
            return {"winner": winner, "dispatch_worker": expected_owners[winner], "evaluation_id": race,
                    "claim_gate": claim_receipt, "race_gate": race_receipt, "model_calls": model_calls(),
                    "score": completed["run"]["score"], "lost_claim_did_not_dispatch": True}
        finally:
            control("release")


def exercise_evaluation_submission(agent, *, probe, control, wait_seconds, expected_owners):
    timeout = min(wait_seconds, 100)
    runs = probe("a", "submission-seed", agent["agent_id"], agent["model_id"])
    worker_tags = sorted(runs.keys() - {*QUEUE_NAMES, OVERFLOW_TAG})

    def read(*tags):
        return probe("a", "submission-read", *(item for tag in tags for item in (tag, runs[tag])))

    def lane(slot):
        return probe(slot, "submission-lane")

    def calls():
        observed = control("probe")
        assert observed["unexpected_calls"] == 0, observed
        return observed["calls_by_tag"]

    def accepted(tag):
        return {"status": 202, "body": {"accepted": True, "agent_evaluation_id": runs[tag]}, "retry_after": None}

    left, right = lane("a"), lane("b")
    for idle in (left, right):
        assert (idle["max_workers"], idle["max_queue_size"], idle["available_count"]) == (len(worker_tags), 12, 18)
        assert idle["active_count"] == idle["running_count"] == idle["queued_count"] == 0
    initial = read(*runs)
    assert all(row["run"]["status"] == row["case"]["status"] == "PENDING" for row in initial.values())
    assert not calls()

    try:
        holders = probe("a", "submission-dispatch", "workers", *(runs[tag] for tag in worker_tags))
        assert holders == [accepted(tag) for tag in worker_tags]
        held_calls = dict.fromkeys(worker_tags, 1)
        wait_for(lambda: calls() == held_calls, timeout, "The actual evaluation workers did not reach the model")
        running = read(*worker_tags)
        assert all(row["run"]["status"] == row["case"]["status"] == "RUNNING" for row in running.values())

        queued = probe("a", "submission-dispatch", "queue", *(runs[tag] for tag in QUEUE_NAMES))
        assert queued == [accepted(tag) for tag in QUEUE_NAMES]
        full = lane("a")
        assert full["running_count"] == len(worker_tags) and full["queued_count"] == full["max_queue_size"] == 12
        assert full["rejected_count"] == left["rejected_count"] and full["available_count"] == 0
        rejected, = probe("a", "submission-dispatch", "overflow", runs[OVERFLOW_TAG])
        assert rejected == {"status": 500, "retry_after": None,
                            "body": {"detail": "Failed to submit agent evaluation run"}}
        assert lane("a") == {**full, "rejected_count": full["rejected_count"] + 1}
        assert read(OVERFLOW_TAG) == {OVERFLOW_TAG: initial[OVERFLOW_TAG]}
        assert calls() == held_calls and lane("b") == right

        retried, = probe("b", "submission-dispatch", "overflow", runs[OVERFLOW_TAG])
        assert retried == accepted(OVERFLOW_TAG)
        wait_for(lambda: calls() == {**held_calls, OVERFLOW_TAG: 1}, min(timeout, 25),
                 "The restored evaluation did not reach the provider from the peer")
        assert read(OVERFLOW_TAG)[OVERFLOW_TAG]["case"]["status"] == "RUNNING"
        assert read(*worker_tags) == running
        assert control("release") == {"released": True}

        def settled():
            observations = read(*runs)
            for row in observations.values():
                assert row["run"]["status"] != "FAILED", row
                if row["run"]["status"] != "COMPLETED" or row["case"]["status"] != "COMPLETED":
                    return None
            return observations

        finished = wait_for(settled, timeout, "The actual evaluations did not settle and restore capacity")
        for tag, state in finished.items():
            assert state["run"]["progress"] == 1 and state["run"]["score"] == 1.0
            assert state["case"]["predict"] == {"answer": f"stream-tail:{tag}:结束🌊"}
        assert calls() == dict.fromkeys(runs, 1)
        for slot, idle in (("a", left), ("b", right)):
            target = {**idle, "rejected_count": idle["rejected_count"] + (slot == "a")}
            wait_for(lambda: lane(slot) == target, timeout, "The Management evaluation lane did not recover")
        return {"running_when_rejected": full["running_count"], "queued_when_rejected": full["queued_count"],
                "submission_rejection": rejected["status"], "failed_claim_rolled_back": True,
                "retired_capacity_owner": expected_owners["a"], "retried_on_peer": expected_owners["b"],
                "recovered_lane_capacity": True, "model_calls": calls()}
    finally:
        control("release")
