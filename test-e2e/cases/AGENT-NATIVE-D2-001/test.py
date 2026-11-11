# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing HTTP/SSE contracts against an independently deployed native runtime."""

import hashlib
import json
import os

import httpx
import pytest
from shared.case_evidence import write_case_evidence

CASE_ID = "AGENT-NATIVE-D2-001"


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
@pytest.mark.parametrize("scenario", ["plain", "python", "fallback_plain", "fallback_python"])
def test_existing_definition_stream_and_immutability(scenario):
    config = os.environ["NEXENT_CONFIG_URL"]
    runtime = os.environ["NEXENT_RUNTIME_URL"]
    agent_id = int(os.environ["NEXENT_NATIVE_TEST_AGENT_ID"])
    is_fallback = scenario.startswith("fallback_")
    model_id = int(os.environ["NEXENT_NATIVE_TEST_FALLBACK_MODEL_ID" if is_fallback else "NEXENT_NATIVE_TEST_MODEL_ID"])
    with httpx.Client(timeout=180) as client:
        login = client.post(
            config + "/user/signin",
            json={
                "email": "admin@nexent.com",
                "password": os.environ["NEXENT_TEST_PASSWORD"],
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": "Bearer " + login.json()["data"]["session"]["access_token"]
        }

        def definition_hash():
            response = client.post(
                config + "/agent/search_info",
                json={"agent_id": agent_id},
                headers=headers,
            )
            assert response.status_code == 200
            return hashlib.sha256(
                json.dumps(response.json(), sort_keys=True).encode()
            ).hexdigest()

        before = definition_hash()
        query = (
            "Reply with exactly NATIVE_RUNTIME_OK."
            if scenario.endswith("plain")
            else (
                ("Use Python code to compute 17*19 and print it. Return the observed result." if is_fallback else
                 "Use code_execution to compute 17*19 in Python and print it. Return the observed result.")
            )
        )
        events = []
        with client.stream(
            "POST",
            runtime + "/agent/run",
            headers=headers,
            json={
                "agent_id": agent_id,
                "model_id": model_id,
                "query": query,
                "history": [],
                "is_debug": True,
            },
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            for line in response.iter_lines():
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    events.append(json.loads(line[5:].strip()))
        assert not any(event.get("type") == "error" for event in events)
        completions = [event for event in events if event.get("type") == "final_answer"
                       and event.get("answer_phase") == "complete" and not event.get("invocation_id")]
        assert len(completions) == 1
        completion = completions[0]
        text = completion.get("content") or "".join(
            str(event.get("content", "")) for event in events
            if event.get("step_id") == completion.get("step_id") and not event.get("invocation_id")
            and event.get("type") in {"model_output", "model_output_thinking", "final_answer"}
        )
        expected = "NATIVE_RUNTIME_OK" if scenario.endswith("plain") else "323"
        assert expected in text
        assert any(event.get("type") == "final_answer" for event in events)
        if scenario.endswith("python"):
            logs = [
                str(event.get("content", ""))
                for event in events
                if event.get("type") == "execution_logs"
            ]
            assert any(
                "323" in log
                and "failed" not in log.lower()
                and "error" not in log.lower()
                for log in logs
            )
        after = definition_hash()
        assert before == after
        write_case_evidence(
            "api-" + scenario,
            {
                "scenario": scenario,
                "agent_id": agent_id,
                "model_id": model_id,
                "definition_sha256_before": before,
                "definition_sha256_after": after,
                "event_types": sorted({event.get("type", "") for event in events}),
                "actual_python_observation": scenario.endswith("python"),
                "capability_fallback": is_fallback,
                "expected_marker": expected,
            },
        )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
def test_unauthenticated_run_is_denied_before_stream_execution():
    response = httpx.post(
        os.environ["NEXENT_RUNTIME_URL"] + "/agent/run",
        json={
            "agent_id": int(os.environ["NEXENT_NATIVE_TEST_AGENT_ID"]),
            "query": "Unauthorized probe",
        },
        timeout=30,
    )
    assert response.status_code >= 400
    assert "text/event-stream" not in response.headers.get("content-type", "")
    write_case_evidence(
        "api-unauthenticated",
        {"status_code": response.status_code, "denied_before_stream": True},
    )
