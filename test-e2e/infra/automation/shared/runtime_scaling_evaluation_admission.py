# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise two real Runtime evaluation workers against the same pending claim."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from shared.runtime_scaling_admission import wait_for


RACE_TAG = "admission-eval-race"
LOST_CLAIM_TAG = "admission-eval-lost-claim"
QUEUED_TAG = "admission-eval-backlog"
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
        assert state["run"]["progress"] == 0 and not state["reservations"]
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
            winner, = (slot for slot, result in results.items() if result == accepted)
            loser, = results.keys() - {winner}
            assert results[loser] == {**accepted, "already_running": True}

            wait_for(lambda: model_calls() == {RACE_TAG: 1}, timeout, "The unique evaluation did not reach the model")
            held = read(race, RACE_TAG)
            reservation, = held["reservations"]
            expected_owner = expected_owners[winner]
            assert reservation["owner"] == expected_owner or reservation["owner"].split(":", 1)[0] == expected_owner
            assert reservation["status"] == "RUNNING" and reservation["error"] is None
            assert held["run"] == {**initial["run"], "status": "RUNNING"}
            assert held["case"] == {**initial["case"], "status": "RUNNING"}
            assert dispatch(loser, race, RACE_TAG) == {**accepted, "already_running": True}
            assert read(race, RACE_TAG) == held and model_calls() == {RACE_TAG: 1}

            claimant_gate = executor.submit(probe, "a", "admission-gate", lost_claim, LOST_CLAIM_TAG)
            wait_gate(claimant_gate, lost_claim, LOST_CLAIM_TAG)
            claimant = executor.submit(dispatch, loser, lost_claim, LOST_CLAIM_TAG)
            claim_receipt = claimant_gate.result(timeout=timeout)
            assert claim_receipt == {"waiting_claimants": 1, "mode": "claim"}
            failed_dispatch = {"accepted": False, "already_finished": True, "status": "FAILED",
                               "agent_evaluation_id": lost_claim}
            assert claimant.result(timeout=timeout) == failed_dispatch
            after_loss = read(lost_claim, LOST_CLAIM_TAG)
            assert after_loss == {**unclaimed, "run": {**unclaimed["run"], "status": "FAILED",
                                  "error": "Case changed the pending status while the conditional claim was waiting"}}
            assert dispatch(winner, lost_claim, LOST_CLAIM_TAG) == failed_dispatch
            assert read(race, RACE_TAG) == held and model_calls() == {RACE_TAG: 1}

            assert control(f"release/{RACE_TAG}") == {"released": True}

            def settled():
                observed = read(race, RACE_TAG)
                current, = observed["reservations"]
                assert current["status"] not in {"FAILED", "STOPPED"}, observed
                return observed if current["status"] == "COMPLETED" else None

            completed = wait_for(settled, timeout, "The winning evaluation did not settle")
            assert completed == {
                "reservations": [{**reservation, "status": "COMPLETED"}],
                "run": {**held["run"], "status": "COMPLETED", "progress": 1, "score": 1.0},
                "case": {**held["case"], "status": "COMPLETED", "score": {f"Admission exact match: {RACE_TAG}": 1.0},
                         "predict": {"answer": f"stream-tail:{RACE_TAG}:结束🌊"}},
            }
            for slot in expected_owners:
                assert dispatch(slot, race, RACE_TAG) == {"accepted": False, "already_finished": True,
                                                          "status": "COMPLETED", "agent_evaluation_id": race}
            assert read(race, RACE_TAG) == completed and read(lost_claim, LOST_CLAIM_TAG) == after_loss
            assert model_calls() == {RACE_TAG: 1}
            return {"winner": winner, "owner": reservation["owner"], "execution_id": reservation["id"],
                    "claim_gate": claim_receipt, "race_gate": race_receipt, "model_calls": model_calls(),
                    "score": completed["run"]["score"], "rolled_back_losing_reservation": True}
        finally:
            control("release")


def exercise_evaluation_submission(agent, *, probe, control, wait_seconds, expected_owners):
    timeout = min(wait_seconds, 65)
    runs = probe("a", "submission-seed", agent["agent_id"], agent["model_id"])
    worker_tags = sorted(runs.keys() - {QUEUED_TAG, OVERFLOW_TAG})

    def read(*tags):
        return probe("a", "submission-read", *(item for tag in tags for item in (tag, runs[tag])))

    def lane(slot):
        return probe(slot, "submission-lane")

    def calls():
        observed = control("probe")
        assert observed["unexpected_calls"] == 0, observed
        return observed["calls_by_tag"]

    def accepted(tag):
        return {"accepted": True, "agent_evaluation_id": runs[tag]}

    def assert_owners(observations, slot, status):
        for row in observations.values():
            reservation, = row["reservations"]
            owner, expected = reservation["owner"], expected_owners[slot]
            assert owner == expected or owner.split(":", 1)[0] == expected
            assert reservation["status"] == row["run"]["status"] == row["case"]["status"] == status, row

    left, right = lane("a"), lane("b")
    for idle in (left, right):
        assert (idle["max_workers"], idle["max_queue_size"], idle["available_count"]) == (len(worker_tags), 12, 18)
        assert idle["active_count"] == idle["running_count"] == idle["queued_count"] == 0
    initial = read(*runs)
    for row in initial.values():
        assert row["run"]["status"] == row["case"]["status"] == "PENDING"
        assert row["run"]["progress"] == 0 and not row["reservations"]
    assert not calls()

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            holders = probe("a", "submission-dispatch", "workers", *(runs[tag] for tag in worker_tags))
            assert holders == [{"status": 202, "body": accepted(tag), "retry_after": None} for tag in worker_tags]
            held_calls = dict.fromkeys(worker_tags, 1)
            wait_for(lambda: calls() == held_calls, timeout, "The actual evaluation workers did not reach the model")
            running = read(*worker_tags)
            assert_owners(running, "a", "RUNNING")

            backlog = executor.submit(probe, "a", "submission-dispatch", "queue", runs[QUEUED_TAG])

            def saturated():
                if backlog.done():
                    raise AssertionError(f"The actual evaluation queue settled before saturation: {backlog.result()}")
                snapshot = lane("a")
                return snapshot if snapshot["available_count"] == 0 else None

            full = wait_for(saturated, min(timeout, 22), "The local evaluation queue did not reach its real capacity")
            assert full["running_count"] == len(worker_tags) and full["queued_count"] == full["max_queue_size"]
            assert full["rejected_count"] == left["rejected_count"]
            rejected, = probe("a", "submission-dispatch", "overflow", runs[OVERFLOW_TAG])
            assert rejected == {
                "status": 429, "retry_after": "1", "body": {
                    "code": "RUNTIME_CAPACITY_FULL", "message": "Runtime evaluation capacity is unavailable.",
                    "retryable": True,
                },
            }
            assert lane("a") == {**full, "rejected_count": full["rejected_count"] + 1}
            assert read(QUEUED_TAG, OVERFLOW_TAG) == {tag: initial[tag] for tag in (QUEUED_TAG, OVERFLOW_TAG)}
            assert calls() == held_calls and lane("b") == right

            retried, = probe("b", "submission-dispatch", "overflow", runs[OVERFLOW_TAG])
            assert retried == {"status": 202, "body": accepted(OVERFLOW_TAG), "retry_after": None}
            wait_for(lambda: calls() == {**held_calls, OVERFLOW_TAG: 1}, min(timeout, 15),
                     "The retried evaluation did not reach the peer model")
            assert_owners(read(OVERFLOW_TAG), "b", "RUNNING")
            assert read(*worker_tags) == running

            assert control("release") == {"released": True}
            wait_for(lambda: calls() == dict.fromkeys(runs, 1), timeout, "The queued evaluation did not start exactly once")
            results = backlog.result(timeout=timeout)
            queued = accepted(QUEUED_TAG)
            assert results.count({"status": 202, "body": queued, "retry_after": None}) == 1
            assert results.count({"status": 202, "body": {**queued, "already_running": True},
                                  "retry_after": None}) == full["max_queue_size"] - 1
            assert control(f"release/{QUEUED_TAG}") == {"released": True}

            def settled():
                observations = read(*runs)
                for row in observations.values():
                    assert row["run"]["status"] != "FAILED", row
                    if not row["reservations"] or row["reservations"][0]["status"] != "COMPLETED":
                        return None
                return observations

            finished = wait_for(settled, timeout, "The actual evaluations did not settle and release ownership")
            assert_owners({tag: finished[tag] for tag in (*worker_tags, QUEUED_TAG)}, "a", "COMPLETED")
            assert_owners({OVERFLOW_TAG: finished[OVERFLOW_TAG]}, "b", "COMPLETED")
            for tag, state in finished.items():
                assert state["run"]["progress"] == 1 and state["run"]["score"] == 1.0
                assert state["case"]["predict"] == {"answer": f"stream-tail:{tag}:结束🌊"}
            assert calls() == dict.fromkeys(runs, 1)
            for slot, idle in (("a", left), ("b", right)):
                assert lane(slot) == {**idle, "rejected_count": idle["rejected_count"] + (slot == "a")}
            return {"running_when_rejected": full["running_count"], "queued_when_rejected": full["queued_count"],
                    "submission_rejection": rejected["body"]["code"], "no_rejected_side_effects": True,
                    "retried_on_peer": True, "recovered_lane_capacity": True, "model_calls": calls()}
        finally:
            control("release")
