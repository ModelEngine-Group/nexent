# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployed API proof of typed reasoning using current operator-owned resources."""

import hashlib
import json
import os

import httpx
import pytest
from shared.case_evidence import write_case_evidence

CASE_ID = "AGENT-NATIVE-D2-002"


def definition_hash(client, config, headers, agent_id):
    response = client.post(config + "/agent/search_info", headers=headers, json={"agent_id": agent_id})
    assert response.status_code == 200
    return hashlib.sha256(json.dumps(response.json(), sort_keys=True).encode()).hexdigest()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
@pytest.mark.parametrize("model_index", [0, 1])
def test_reasoning_stream_and_unchanged_definition(model_index):
    config, runtime = os.environ["NEXENT_CONFIG_URL"], os.environ["NEXENT_RUNTIME_URL"]
    agent_id = int(os.environ["NEXENT_NATIVE_TEST_AGENT_ID"])
    model_id = json.loads(os.environ["NEXENT_NATIVE_REASONING_MODEL_IDS"])[model_index]
    with httpx.Client(timeout=180) as client:
        login = client.post(config + "/user/signin", json={
            "email": "admin@nexent.com", "password": os.environ["NEXENT_TEST_PASSWORD"],
        })
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["data"]["session"]["access_token"]}
        before = definition_hash(client, config, headers, agent_id)
        events = []
        with client.stream("POST", runtime + "/agent/run", headers=headers, json={
            "agent_id": agent_id, "model_id": model_id, "query": "Compute 17*19 and give a brief final answer.",
            "history": [], "is_debug": True,
        }) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            for line in response.iter_lines():
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    events.append(json.loads(line[5:].strip()))
        assert not any(e.get("type") == "error" for e in events)
        reasoning = [e for e in events if e.get("type") == "model_output_deep_thinking"]
        assert reasoning
        assert all(e.get("attempt_id") and e.get("step_id") for e in reasoning)
        finals = [e for e in events if e.get("type") == "final_answer"
                  and e.get("answer_phase") == "complete" and not e.get("invocation_id")]
        assert len(finals) == 1
        token_events = [json.loads(e["content"]) for e in events if e.get("type") == "token_count"]
        assert token_events
        assert token_events[-1]["output_finish_reason"] in {"stop", "tool_calls"}
        answer = finals[0].get("content") or "".join(str(e.get("content", "")) for e in events
            if e.get("step_id") == finals[0].get("step_id") and e.get("type") == "model_output")
        assert "323" in answer
        after = definition_hash(client, config, headers, agent_id)
        assert after == before
        write_case_evidence("reasoning-model-" + str(model_index), {
            "model_id": model_id, "reasoning_event_count": len(reasoning),
            "completed_answers": len(finals), "definition_sha256_before": before,
            "definition_sha256_after": after, "observed_result": 323,
        })
