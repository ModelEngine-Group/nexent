# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prove that a non-owner Runtime restart does not interrupt a live owner."""

from datetime import datetime
from hashlib import sha256

from shared.runtime_scaling_admission import new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in, upload_attachment
from shared.runtime_scaling_owner_loss import stream_payload
from shared.runtime_scaling_public_admission import stream_completion, stream_prefix
from shared.runtime_scaling_scheduler import active_automation, check_settled_schedule
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, check_stream


ATTACHMENT = "peer-restart-input.txt"
EVALUATION_SCORE = "Restart fixture exact match"
TAGS = {"pending": 1, "restart-chat": 1, "restart-eval": 1}


def exercise_peer_restart(stable, identity, agent, token, *, client_for, schedule, probe, snapshot,
                          slot_for_owner, restart_peer, control, wait_seconds):
    auth = sign_in(stable, identity)
    auto_id, chat_id = new_conversations(stable, auth, 2)
    seed = schedule("seed", auto_id, "pending", agent["agent_id"], agent["model_id"])
    assert seed["fixture_lock"] and schedule("unblock", auto_id)["unblocked"] is True

    def wait_for_tag(tag):
        wait_for(lambda: control("probe")["calls_by_tag"].get(tag) == 1, wait_seconds,
                 f"The real Runtime did not dispatch {tag}")

    def auto_snapshot():
        return schedule("snapshot", auto_id)

    try:
        wait_for_tag("pending")
        task, _, reservation = active_automation(auto_snapshot(), seed)
        owner, peer = slot_for_owner(task["lock_owner"])
        instance = reservation["owner_instance_id"]
        evaluation_id = probe(owner, "seed-evaluation", agent["agent_id"], agent["model_id"])
        content = f"runtime-peer-restart:{token}\n".encode()

        def evaluation_snapshot():
            return probe(owner, "read-evaluation", evaluation_id)

        def chat_snapshot():
            record = dict(snapshot(owner, chat_id)["runs"][str(chat_id)])
            assert record.pop("state_pttl") > 0
            return record

        with client_for(owner) as client:
            object_name = upload_attachment(client, auth, identity["user_id"], ATTACHMENT, content)
            payload = {**stream_payload(agent, token, chat_id, "restart-chat"),
                       "minio_files": [{"object_name": object_name, "name": ATTACHMENT}]}
            with client.stream("POST", RUN_PATH, headers=auth, json=payload) as stream:
                frames = check_stream(stream, chat_id)
                cursor = stream_prefix(frames, "restart-chat")
                dispatched = probe(owner, "dispatch-evaluation", evaluation_id)
                assert dispatched == {"accepted": True, "agent_evaluation_id": evaluation_id}
                wait_for_tag("restart-eval")

                evaluation = evaluation_snapshot()
                evaluation_reservation, = evaluation["reservations"]
                assert evaluation["run"]["status"] == evaluation["case"]["status"] == "RUNNING"
                assert evaluation["run"]["progress"] == 0 and evaluation["case"]["predict"] is None
                assert evaluation_reservation["owner"] == instance and evaluation_reservation["status"] == "RUNNING"
                chat = chat_snapshot()
                chat_reservation, = chat["reservations"]
                chat_assistant, = chat["assistants"]
                assert chat_reservation["owner"] == instance and chat_reservation["status"] == "RUNNING"
                assert cursor == f"execution:{chat_reservation['id']}" and chat["state"]["generation"] == cursor
                assert chat["users"] == [payload["query"]] and chat_assistant["status"] == "streaming"
                assert evaluation_reservation["epoch"] == chat_reservation["epoch"] == reservation["maintenance_epoch"]

                file = probe(owner, "workspace")
                assert file and file["sha256"] == sha256(content).hexdigest() and probe(peer, "workspace") == file
                auto = auto_snapshot()
                task, scheduled_run, auto_reservation = active_automation(auto, seed)
                lease_before = datetime.fromisoformat(task["lock_until"])
                assert auto_reservation == reservation and auto["messages"]

                replacement, restart_receipt = restart_peer(owner, peer)
                assert probe(replacement, "workspace") == file and probe(owner, "workspace") == file

                def checked_lease():
                    current = auto_snapshot()
                    current_task, current_run, current_reservation = active_automation(current, seed)
                    assert current_run == scheduled_run and current_reservation == reservation
                    assert current["messages"] == auto["messages"]
                    changing = {"lock_until", "update_time"}
                    assert {key: value for key, value in current_task.items() if key not in changing} == {
                        key: value for key, value in task.items() if key not in changing
                    }
                    assert chat_snapshot() == chat and evaluation_snapshot() == evaluation
                    model = control("probe")
                    assert model["calls_by_tag"] == TAGS and model["unexpected_calls"] == 0 and not model["released"]
                    lease = datetime.fromisoformat(current_task["lock_until"])
                    assert lease >= lease_before
                    return lease

                lease_after_restart = checked_lease()

                def renewed():
                    lease = checked_lease()
                    return lease if lease > lease_after_restart else None

                lease_after = wait_for(renewed, wait_seconds, "The original scheduler owner did not renew after peer readiness")
                for tag in TAGS:
                    assert control(f"release/{tag}")["released"] is True
                stream_completion(frames, cursor, "restart-chat")

        def done(snapshot_fn, select_state, expected, failure):
            def settled():
                current = snapshot_fn()
                return current if select_state(current) == expected else None

            return wait_for(settled, wait_seconds, failure)

        finished_chat = done(chat_snapshot, lambda value: value["reservations"][0]["status"], "COMPLETED",
                             "The original chat reservation did not settle")
        assert finished_chat["reservations"] == [{**chat_reservation, "status": "COMPLETED", "finished": True}]
        assert finished_chat["users"] == chat["users"]
        assert finished_chat["assistants"] == [{**chat_assistant, "status": "completed"}]
        assert_persisted_answer(stable, auth, chat_id, chat_assistant["id"], "restart-chat")
        wait_for(lambda: probe(owner, "workspace") is None and probe(replacement, "workspace") is None, wait_seconds,
                 "The completed run did not clean its own attachment workspace")

        finished_eval = done(evaluation_snapshot, lambda value: value["reservations"][0]["status"], "COMPLETED",
                             "The original evaluation worker did not settle")
        assert finished_eval["reservations"] == [{**evaluation_reservation, "status": "COMPLETED"}]
        assert finished_eval["run"] == {**evaluation["run"], "status": "COMPLETED", "progress": 1, "score": 1.0}
        assert finished_eval["case"] == {**evaluation["case"], "status": "COMPLETED", "score": {EVALUATION_SCORE: 1.0},
                                         "predict": {"answer": "stream-tail:restart-eval:结束🌊"}}

        finished_auto = done(auto_snapshot, lambda value: value["reservations"][0]["status"], "COMPLETED",
                             "The original scheduled execution did not settle")
        completed_run = check_settled_schedule(finished_auto, seed, "SUCCEEDED")
        assert completed_run["run_id"] == scheduled_run["run_id"]
        assert_persisted_answer(stable, auth, auto_id, completed_run["assistant_message_id"], "pending")
        model = control("probe")
        assert model["calls_by_tag"] == TAGS and model["unexpected_calls"] == 0
        for identifier in (auto_id, chat_id):
            path = f"/api/conversation/{identifier}"
            require_status(stable.delete(path, headers=auth), 200, "Delete the owned conversation")
            assert stable.get(path, headers=auth).json()["data"] == []
        return {**restart_receipt, "owner": instance, "chat_execution": chat_reservation["id"],
                "evaluation_id": evaluation_id, "evaluation_execution": evaluation_reservation["id"],
                "scheduled_run": scheduled_run["run_id"], "lease_renewal_seconds": (lease_after - lease_before).total_seconds(),
                "workspace_sha256": file["sha256"], "workspace_cleaned_after_completion": True, "model_calls": model["calls_by_tag"]}
    finally:
        control("release")
