# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise Management's request-owned NL2Agent stream and grant lifetime."""

import asyncio
import json

import pytest
from starlette.responses import StreamingResponse

from contracts.agent import NL2AgentRunRequest
from contracts.agentos import PreparedAgentCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import creator_run
from management.services.agent.nl2agent import Nl2AgentDraftSaveError

_ACTOR = ServicePrincipal("owner", "tenant")
_PAYLOAD = PreparedAgentCreatorRun.model_validate({
    "mode": "nl2agent", "agent_id": 7, "run_id": "a" * 32,
    "input": {"query": "Create an Agent"}, "bound_resources": "Verified state",
    "model": {"model_id": 5, "alias": "model", "revision": "v1"},
    "input_budget": 8192, "context_window_tokens": 8192,
})


@pytest.fixture
def grant(mocker):
    async def inline(_name, func, *args, **kwargs):
        return func(*args)
    mocker.patch.object(creator_run, "run_blocking", side_effect=inline)
    return (
        mocker.patch.object(creator_run, "open_nl2agent_tool_grant"),
        mocker.patch.object(creator_run, "close_nl2agent_tool_grant"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["complete", "error", "nl2a", "disconnect", "cancelled"])
async def test_creation_stream_preserves_events_and_releases_grant(mocker, grant, terminal):
    opened, closed = grant
    exited = False

    async def events():
        nonlocal exited
        try:
            yield b'data: {"type":"progress","content":"started"}\n\n'
            if terminal == "complete":
                yield b'data: {"type":"final_answer","content":"done"}\n\n'
                yield b'event: agentos_execution_complete\ndata: {}\n\n'
            elif terminal == "error":
                yield b'event: agentos_execution_error\ndata: {"type":"error","content":"safe failure"}\n\n'
            elif terminal == "nl2a":
                yield b'data: {"type":"nl2a","content":"card"}\n\n'
                yield b'data: {"type":"final_answer","content":"must not leak"}\n\n'
            elif terminal == "cancelled":
                raise asyncio.CancelledError
        finally:
            exited = True

    remote = mocker.patch.object(creator_run, "forward_creator_run", return_value=StreamingResponse(events()))
    stream = creator_run.create_nl2agent_stream(_PAYLOAD, _ACTOR)
    remote.assert_not_awaited()
    assert json.loads((await anext(stream))[6:])["type"] == "progress"
    if terminal == "disconnect":
        await stream.aclose()
    elif terminal == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await anext(stream)
    else:
        output = [json.loads(frame[6:]) async for frame in stream]
        expected = {"complete": "final_answer", "error": "error", "nl2a": "nl2a"}
        assert [event["type"] for event in output] == [expected[terminal]]
    remote.assert_awaited_once_with(_PAYLOAD, _ACTOR.user_id, _ACTOR.tenant_id)
    opened.assert_called_once_with(_PAYLOAD.run_id, 7, _ACTOR, False)
    closed.assert_called_once_with(_PAYLOAD.run_id)
    assert exited


@pytest.mark.asyncio
async def test_card_target_mismatch_is_rejected_before_model_preflight(mocker):
    mocker.patch.object(creator_run, "_parse_nl2agent_card_action_agent_id", return_value=9)
    compile_model = mocker.patch.object(creator_run, "run_blocking")
    with pytest.raises(Nl2AgentDraftSaveError, match="agent_context_mismatch"):
        await creator_run.prepare_nl2agent_snapshot(NL2AgentRunRequest(query="Continue", agent_id=7), _ACTOR, "en")
    compile_model.assert_not_called()
