# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify final-answer compatibility through the deployed Northbound SSE API."""

import json
from uuid import uuid4

import pytest

from d3.assets import get_test_asset, model_id
from shared.asset_registry import mark_asset_state, register_asset
from shared.factories.conversation import delete_owned_conversation
from shared.final_answers import final_answer_text
from shared.http import MODEL_TIMEOUT, assert_status, client


CASE_ID = "NB-CHAT-FINAL-ANSWER-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D2"), pytest.mark.asyncio]


async def collect_events(response):
    """Parse SSE frames independently of HTTP packet or UTF-8 token boundaries."""
    events, data = [], []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            value = json.loads("\n".join(data))
            if isinstance(value, dict):
                events.append(value)
            data.clear()
    assert not data, "The SSE response ended with an incomplete event"
    return events


@pytest.mark.parametrize("mode", [None, "complete", "delta"], ids=["default", "complete", "delta"])
async def test_northbound_answer_modes_match_finalized_history(tenant_a_user, northbound_key, mode):
    marker = "NB_FINAL_" + uuid4().hex
    end = "END_" + marker
    request_id = uuid4().hex
    payload = {
        "agent_name": str(get_test_asset("agents", "basic_name")),
        "model_id": await model_id("llm", tenant_a_user),
        "query": f"Reply exactly with this text, without quotation marks:\n{marker} "
                 f"Alpha beta gamma. Delta epsilon zeta. Eta theta iota. {end}",
    }
    if mode is not None:
        payload["final_answer_mode"] = mode
    conversation_id = None
    primary_error = None
    try:
        async with client("northbound", api_key=northbound_key, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/nb/v1/chat/run", json=payload,
                                  headers={"X-Request-Id": request_id}) as response:
                assert_status(response, 200)
                conversation_id = int(response.headers["conversation_id"])
                register_asset(
                    "owned_conversations", str(conversation_id), conversation_id, owner_case_id=CASE_ID,
                    cleanup={"service": "runtime", "identity": tenant_a_user.id, "method": "DELETE",
                             "path": f"/conversation/{conversation_id}", "allowed_statuses": [200, 404]},
                )
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["X-Request-Id"] == request_id
                events = await collect_events(response)
            history = await api.get(f"/nb/v1/conversations/{conversation_id}")
            assert_status(history, 200)
        assert not any(event.get("type") == "error" for event in events)
        persisted = [message["content"] for message in history.json()["data"]["history"]
                     if message["role"] == "assistant"]
        assert len(persisted) == 1
        final_events = [event for event in events if event.get("type") == "final_answer"]
        if mode != "delta":
            assert len(final_events) == 1, "A first-answer consumer must receive exactly one complete answer"
            assert not final_events[0].get("invocation_id")
            assert final_events[0].get("answer_phase") == "complete"
            assert final_events[0]["content"] == persisted[0]
            assert marker in final_events[0]["content"] and end in final_events[0]["content"]
        else:
            root = [event for event in final_events if not event.get("invocation_id")]
            assert any(event.get("answer_phase") == "delta" for event in root)
            assert root[-1].get("answer_phase") == "complete"
            assert final_answer_text(events) == persisted[0]
            assert marker in persisted[0] and end in persisted[0]
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if conversation_id is not None:
            try:
                await delete_owned_conversation(tenant_a_user, conversation_id)
                mark_asset_state("owned_conversations", str(conversation_id), "DELETED")
            except Exception:
                mark_asset_state("owned_conversations", str(conversation_id), "ORPHANED",
                                 detail="final-answer compatibility cleanup failed")
                if primary_error is None:
                    raise
                primary_error.add_note("Conversation cleanup also failed; inspect the asset journal.")


@pytest.mark.parametrize("mode", ["unknown", "", True])
async def test_northbound_rejects_invalid_modes_without_creating_conversations(northbound_key, mode):
    async with client("northbound", api_key=northbound_key) as api:
        before = await api.get("/nb/v1/conversations")
        assert_status(before, 200)
        rejected = await api.post("/nb/v1/chat/run", json={
            "agent_name": "unused-for-rejected-request", "query": "invalid mode",
            "final_answer_mode": mode,
        })
        assert_status(rejected, 422)
        assert any(item["loc"] == ["body", "final_answer_mode"] for item in rejected.json()["detail"])
        after = await api.get("/nb/v1/conversations")
        assert_status(after, 200)
    assert after.json()["data"] == before.json()["data"], "Invalid requests must not create a conversation"
