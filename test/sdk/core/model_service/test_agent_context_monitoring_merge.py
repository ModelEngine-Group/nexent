# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private CM snapshots and develop's physical monitoring coexist across retries."""

import json

import pytest
from test_model_service import Sender, frame
from test_model_service import setup as setup

from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse
from nexent.core.model_service.sse import SSEEvent
from nexent.monitor.facts import get_fact_sink, set_fact_sink


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_private_pairing_and_attempt_facts_share_the_successful_physical_attempt(setup, asynchronous, streaming):
    profile, request, limiter, factory = setup
    usage = {"prompt_tokens": 70, "completion_tokens": 30}
    outcome = ([frame({"content": "accepted"}), frame(finish="stop"),
                SSEEvent(json.dumps({"choices": [], "usage": usage})), SSEEvent("[DONE]")] if streaming else
               RawHttpResponse(200, {}, json.dumps({"choices": [{"index": 0, "message": {
                   "role": "assistant", "content": "accepted"}, "finish_reason": "stop"}], "usage": usage}).encode()))

    class DispatchedSender(Sender):
        def invoke(self, prepared, **kwargs):
            prepared.on_dispatch()
            return super().invoke(prepared, **kwargs)

    sender = DispatchedSender([ModelTransportError("HTTP_NETWORK_ERROR"), outcome])
    service = factory(sender)
    boundary, facts = object(), []
    previous = get_fact_sink()
    set_fact_sink(facts.append)
    request = request.model_copy(update={"stream": streaming})
    try:
        if streaming and asynchronous:
            async with service.astream(request, profile, agent_context=boundary) as events:
                response = [event async for event in events][-1].message
        elif streaming:
            with service.stream(request, profile, agent_context=boundary) as events:
                response = list(events)[-1].message
        elif asynchronous:
            response = await service.ainvoke(request, profile, agent_context=boundary)
        else:
            response = service.invoke(request, profile, agent_context=boundary)
    finally:
        set_fact_sink(previous)

    snapshot = response._agent_input
    assert snapshot.binding is boundary and snapshot.attempt == 2
    assert json.loads(snapshot.semantic_json) == {"messages": json.loads(sender.calls[-1].body_bytes)["messages"]}
    assert [fact["outcome"] for fact in facts] == ["started", "failed", "started", "succeeded"]
    assert facts[2]["fact_id"] == facts[3]["fact_id"] != facts[0]["fact_id"]
    assert facts[-1]["call_context_id"] == snapshot.request_id
    assert facts[-1]["input_tokens"] == response.usage.input_tokens == 70
    assert facts[-1]["output_tokens"] == response.usage.output_tokens == 30
    assert "_agent_input" not in response.model_dump_json()
    assert not any("messages" in fact or "agent_context" in fact for fact in facts)
    assert len(sender.calls) == 2 and not limiter._entries
