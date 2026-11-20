# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify that the real Web and Northbound front doors can control a peer-owned stream."""

from contextlib import ExitStack

import httpx

from shared.runtime_scaling_admission import new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in
from shared.runtime_scaling_public_admission import FIXTURE_AGENT_NAME, NORTHBOUND_RUN
from shared.runtime_scaling_stream import RUN_PATH, assert_persisted_answer, check_replayed_tail, check_stream, read_prefix


def exercise_public_stream_control(web_url, gateway_url, identity, api_key, agent, token, *,
                                   control, transport, stream_probe, snapshot, origins, wait_seconds, producer_host=None):
    assert set(origins) == {"producer", "peer"} and len(set(origins.values())) == 2
    with ExitStack() as stack:
        web, gateway = [stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds, trust_env=False))
                        for url in (web_url, gateway_url)]
        web_auth = sign_in(gateway, identity)
        northbound_auth = {"Authorization": f"Bearer {api_key}"}
        identifiers = new_conversations(web, web_auth, 2)
        evidence, model_calls, route_receipts = {}, {}, {}

        def receipt(operation, target):
            return {"operation": operation, "target": target, "status": 200, "origin": origins[target]}

        for entrance, client, auth, run_path, identifier in zip(
            ("web", "northbound"), (web, gateway), (web_auth, northbound_auth), (RUN_PATH, NORTHBOUND_RUN),
            identifiers, strict=True,
        ):
            northbound = entrance == "northbound"
            run_selector = {"agent_name": FIXTURE_AGENT_NAME} if northbound else {"agent_id": agent["agent_id"], "history": []}

            def state():
                return snapshot(identifier)["runs"][str(identifier)]

            def start(tag):
                payload = {**run_selector, "conversation_id": identifier, "model_id": agent["model_id"],
                           "stream_cursor": True, "query": f"runtime-stream:{token}:{tag}"}
                cursor, generation = read_prefix(client, auth, payload, tag, path=run_path)
                current = state()
                row = current["reservations"][-1]
                message = current["assistants"][-1]
                assert generation == f"execution:{row['id']}" and current["state"]["generation"] == generation
                assert row["status"] == "RUNNING" and not row["finished"] and message["status"] == "streaming"
                assert current["users"][-1] == payload["query"]
                if producer_host is not None:
                    assert row["owner"].split(":", 1)[0] == producer_host
                model_calls[tag] = 1
                assert control("probe")["calls_by_tag"] == model_calls
                return payload, cursor, generation, row, message

            resume_tag = f"public-{entrance}-resume"
            original, cursor, generation, producer, message = start(resume_tag)
            resume = {**original, "replay_cursor": cursor}
            replay_params = None
            if not northbound:
                resume["resume_message_id"] = message["id"]
                replay_params = {"resume": "true"}
            assert transport("probe")[resume_tag] == [receipt("start", "producer")]

            with client.stream("POST", run_path, headers=auth, params=replay_params, json=resume) as response:
                frames = check_stream(response, identifier, resumed=True)
                if northbound:
                    assert response.headers["X-Request-Id"]
                event, _, status = next(frames)
                assert (event, status["status"]) == ("stream_status", "resumed")
                assert transport("probe")[resume_tag] == [receipt("start", "producer"), receipt("replay", "peer")]
                assert control("probe")["calls_by_tag"] == model_calls
                assert control(f"release/{resume_tag}")["released"] is True
                wait_for(lambda: stream_probe("settled", identifier, generation)["terminal_committed"], wait_seconds,
                         "The original producer did not commit the unread replay tail")
                replay = check_replayed_tail(list(frames), resume_tag, generation)

            with client.stream("POST", run_path, headers=auth, params=replay_params, json=resume) as response:
                repeated = check_replayed_tail(list(check_stream(response, identifier, resumed=True)), resume_tag, generation)
            assert replay == repeated, "Reusing the last applied cursor changed the delivered events"
            assert_persisted_answer(web, web_auth, identifier, message["id"], resume_tag)
            finished = state()
            assert finished["reservations"] == [{**producer, "status": "COMPLETED", "finished": True}]
            assert finished["users"] == [original["query"]]
            route_receipts[resume_tag] = [receipt("start", "producer"), receipt("replay", "peer"), receipt("replay", "peer")]

            stop_tag = f"public-{entrance}-stop"
            fresh, _, stop_generation, running, current_message = start(stop_tag)
            assert running["owner"] == producer["owner"] and stop_generation != generation
            stop_path = f"/nb/v1/chat/stop/{identifier}" if northbound else f"/api/agent/stop/{identifier}"
            stopped = client.get(stop_path, headers=auth, params=None if northbound else {"generation": stop_generation})
            require_status(stopped, 200, "Stop the producer through the peer Runtime")
            reply = stopped.json()
            if northbound:
                assert reply["requestId"] and reply["data"] == identifier
                assert reply["message"].startswith("successfully stopped agent run")
            else:
                assert reply["status"] == "success" and reply.get("already_stopped") is not True
            route_receipts[stop_tag] = [receipt("start", "producer"), receipt("stop", "peer")]
            assert transport("probe")[stop_tag] == route_receipts[stop_tag]

            def stopped_message():
                current = state()
                assistant = current["assistants"][-1]
                assert assistant["id"] == current_message["id"]
                return assistant["status"] == "stopped"

            wait_for(stopped_message, wait_seconds, "The original producer did not persist the legal remote stop")
            assert control(f"release/{stop_tag}")["released"] is True
            wait_for(lambda: state()["reservations"][-1]["status"] == "STOPPED", wait_seconds,
                     "The original producer did not settle after receiving stop")
            terminal = state()
            assert terminal["reservations"] == [*finished["reservations"], {**running, "status": "STOPPED", "finished": True}]
            assert terminal["assistants"] == [*finished["assistants"], {**current_message, "status": "stopped"}]
            assert terminal["users"] == [original["query"], fresh["query"]]
            assert control("probe")["calls_by_tag"] == model_calls
            evidence[entrance] = {"replayed_generation": generation, "stopped_generation": stop_generation,
                                  "producer_owner": producer["owner"], "replayed_events": len(replay)}

        assert transport("probe") == route_receipts
        model = control("probe")
        assert model["calls_by_tag"] == model_calls and model["unexpected_calls"] == 0
        for identifier in identifiers:
            path = f"/api/conversation/{identifier}"
            require_status(web.delete(path, headers=web_auth), 200, "Delete the owned conversation")
            assert web.get(path, headers=web_auth).json()["data"] == []
        return {"entrances": evidence, "upstream_receipts": route_receipts, "model_calls": model_calls,
                "owned_conversations_deleted": True}
