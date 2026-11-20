# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep recorded execution facts inside the signed journal and durable projection."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agentos import AgentRunReference
from contracts.conversation import MessageSource
from management.services.agent import prepared_projection, prepared_turn
from runtime.agentos import prepared_run
from ..app.test_agentos_prepared_run import ACTOR, payload, runtime
from .test_agentos_conversation_projection import response


@pytest.fixture
def capture(runtime, payload, mocker):
    frames = []
    journal = runtime.journal.return_value
    journal.append.side_effect = lambda index, chunk: frames.append(f"id: {payload.run_id}:{index}\n".encode() + chunk.encode())

    def terminal(status):
        frames.append(
            f'id: {payload.run_id}:{len(frames) + 1}\nevent: agentos_terminal\ndata: {json.dumps({"status": status})}\n\n'.encode(),
        )

    journal.repair_terminal.side_effect = terminal
    persist = Mock(return_value=4242)

    async def run_blocking(_name, call, **kwargs):
        assert call is prepared_projection.persist_prepared_assistant_projection
        return persist(**{k: v for k, v in kwargs.items() if k not in {"lane", "owner"}})

    mocker.patch.object(prepared_projection, "run_blocking", side_effect=run_blocking)

    async def run(source, *, public=True):
        mocker.patch.object(prepared_run, "agent_run", new=source)
        reference = await prepared_run.start_prepared_run(payload, ACTOR)
        await asyncio.wait_for(asyncio.gather(*list(runtime.tasks)), timeout=2)
        client = SimpleNamespace(resume=AsyncMock(side_effect=lambda *_args: response(*frames)))
        turn = SimpleNamespace(reference=reference, user_id=ACTOR.user_id, tenant_id=ACTOR.tenant_id, message_index=9)

        async def finish(_turn, _client):
            return await prepared_projection.resume_assistant_projection(
                client.resume, reference, ACTOR.user_id, ACTOR.tenant_id, message_index=9,
                message_source=MessageSource.CHAT, assistant_message_id=4242,
            )

        if not public:
            return await finish(turn, client)
        mocker.patch.object(prepared_turn, "_finish_projection", side_effect=finish)
        output = await prepared_turn._stream_turn(turn, client)
        return b"".join([chunk async for chunk in output.body_iterator])

    return SimpleNamespace(frames=frames, persist=persist, run=run)


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", [None, "child-invocation"])
async def test_execution_fact_gets_real_unit_index_and_commits_without_public_sse(capture, invocation):
    observed = {}

    async def source(info, **_kwargs):
        history = info.observer.execution_history
        key = history.register("actual-agent-owner", {"OUTPUT": "masked *** result"})
        record = history.get(key)
        observed.update(history=history, key=key, record=record)
        yield json.dumps({
            "type": "execution_result", "content": json.dumps({"execution_key": key}),
            "invocation_id": invocation, "tool_call_id": "actual-call",
        })
        record.summary = "safe summary"
        yield json.dumps({"type": "final_answer", "content": "done"})

    public = await capture.run(source)

    units = capture.persist.call_args.kwargs["message_units"]
    assert capture.persist.call_args.kwargs["assistant_message_id"] == 4242
    assert [unit["type"] for unit in units] == ["execution_result", "final_answer"]
    fact = units[0]
    assert (fact["unit_index"], fact["invocation_id"], fact["tool_call_id"]) == (0, invocation, "actual-call")
    assert json.loads(fact["unit_content"]) == {"content": "<OUTPUT>masked *** result</OUTPUT>", "summary": "safe summary"}
    assert "_execution_key" not in fact
    assert observed["key"].encode() not in b"".join(capture.frames)
    assert b"agentos_execution_fact" in b"".join(capture.frames)
    assert b"agentos_execution" not in public and b"masked *** result" not in public
    assert b'"content":"done"' in public
    record = observed["record"]
    assert record.reference.endswith("/execution:1")
    assert json.loads(observed["history"].read("actual-agent-owner", record.reference))["text"] == record.text


@pytest.mark.asyncio
async def test_unregistered_or_repeated_execution_key_cannot_create_public_facts(capture):
    async def source(info, **_kwargs):
        key = info.observer.execution_history.register("owner", {"OUTPUT": "only once"})
        for item in ("unknown-key", key, key, [], "another-unregistered-key"):
            yield json.dumps({"type": "execution_result", "content": {"execution_key": item}})
        yield json.dumps({"type": "final_answer", "content": "done"})

    public = await capture.run(source)

    assert [unit["type"] for unit in capture.persist.call_args.kwargs["message_units"]] == ["execution_result", "final_answer"]
    assert b"unknown-key" not in b"".join(capture.frames)
    assert b"only once" not in public


@pytest.mark.asyncio
async def test_rollback_leaves_original_result_in_owned_buffer_and_journal(capture, payload):
    observed = {}
    capture.persist.side_effect = RuntimeError("database offline")

    async def source(info, **_kwargs):
        history = info.observer.execution_history
        key = history.register("owner", {"OUTPUT": "preserved buffer"})
        observed.update(history=history, record=history.get(key))
        yield json.dumps({"type": "execution_result", "content": {"execution_key": key}})
        yield json.dumps({"type": "final_answer", "content": "done"})

    public = await capture.run(source)

    record = observed["record"]
    assert record.persisted is False
    assert json.loads(observed["history"].read("owner", record.reference))["text"] == record.text
    with pytest.raises(PermissionError):
        observed["history"].read("another-agent", record.reference)
    assert b"preserved buffer" not in public
    assert b"preserved buffer" in b"".join(capture.frames)
    assert capture.persist.call_count == 1
    reference = AgentRunReference(conversation_id=payload.conversation_id, run_id=payload.run_id)
    capture.persist.side_effect = None
    replay = await prepared_projection.resume_assistant_projection(
        AsyncMock(return_value=response(*capture.frames)), reference, ACTOR.user_id, ACTOR.tenant_id,
        message_index=9, message_source=MessageSource.CHAT, assistant_message_id=4242,
    )
    assert replay.assistant_message_id == 4242
    assert capture.persist.call_count == 2
    assert capture.persist.call_args_list[0] == capture.persist.call_args_list[1]
