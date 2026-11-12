# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator card carriers and the terminal interaction boundary."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from concurrent.futures import Future

import pytest

from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from services.nl2agent_service import _Nl2AgentBoundaryObserver


CARD = '<nl2a>\n{"subtype":"requirement_clarification","agent_id":42,"questions":[]}\n</nl2a>'
STATE = '<nl2a_state>{"event":"agent_draft_fields_saved","agent_id":42,"updated_fields":["name"]}</nl2a_state>'


def setup_adapter(mode="python_workflow"):
    stop = threading.Event()
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop)
    adapter = JiuwenAdapter(SimpleNamespace(
        agent_config=AgentConfig(name="creator", description="creator", model_name="model", tools=[], response_mode=mode),
        observer=observer, query="create", stop_event=stop,
    ))
    return adapter, observer, stop


def drain(observer):
    return [json.loads(item) for item in observer.get_cached_message()]


@pytest.mark.parametrize("carrier", [
    lambda text: {"result": text},
    lambda text: json.dumps({"result": text}),
    lambda text: {"logs": text, "output": "None"},
    lambda text: {"content": [{"type": "text", "text": text}]},
    lambda text: text,
])
def test_successful_workflow_carriers_publish_the_same_card(carrier):
    adapter, observer, stop = setup_adapter()
    adapter._resource_result(carrier(CARD))
    cards = [event for event in drain(observer) if event["type"] == "nl2a"]
    assert len(cards) == 1 and json.loads(cards[0]["content"])["agent_id"] == 42
    assert observer.boundary_reached and stop.is_set()


def test_native_mcp_draft_state_is_published_without_ending_the_turn():
    adapter, observer, stop = setup_adapter()
    adapter._resource_result({"result": STATE})
    states = [event for event in drain(observer) if event["type"] == "nl2a_state"]
    assert len(states) == 1 and json.loads(states[0]["content"])["updated_fields"] == ["name"]
    assert not observer.boundary_reached and not stop.is_set()


@pytest.mark.parametrize("result", [
    {"success": False, "result": CARD},
    {"isError": True, "result": CARD},
    {"result": '<nl2a>{invalid}</nl2a>'},
    {"result": {"untrusted": CARD}},
    {"result": "ordinary tool output"},
])
def test_failed_or_non_card_result_does_not_stop_or_publish_a_card(result):
    adapter, observer, stop = setup_adapter()
    adapter._resource_result(result)
    assert not any(event["type"] == "nl2a" for event in drain(observer))
    assert not observer.boundary_reached and not stop.is_set()


def test_plain_chat_keeps_native_mcp_result_as_data():
    adapter, observer, stop = setup_adapter("chat")
    adapter._resource_result({"result": CARD})
    assert not any(event["type"] == "nl2a" for event in drain(observer))
    assert not observer.boundary_reached and not stop.is_set()


@pytest.mark.asyncio
async def test_card_blocks_next_model_prepare_and_tool_dispatch():
    adapter, observer, _stop = setup_adapter()
    from nexent.core.utils.observer import ProcessType
    observer.add_message("creator", ProcessType.EXECUTION_LOGS, CARD)
    assert observer.boundary_reached
    adapter.mcp = None
    adapter.context_bridge = SimpleNamespace(prepare_messages=AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        await adapter._prepare_model_messages([], [])
    adapter.context_bridge.prepare_messages.assert_not_awaited()
    effects = []
    with pytest.raises(asyncio.CancelledError):
        with adapter._observe_tool("later_tool", {}):
            effects.append("must not run")
    assert effects == []
    assert not any(event["type"] in {"tool", "tool-call", "error"} for event in drain(observer))


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["run_terminal", "error"])
async def test_creator_stream_preserves_terminal_or_real_failure_after_card(monkeypatch, ending):
    from contracts.agent import NL2AgentRunRequest
    from contracts.authentication import AuthenticatedIdentity
    from services import nl2agent_service as service

    adapter, _observer, _stop = setup_adapter()
    adapter.run_info.agent_config.agent_id = None
    monkeypatch.setattr(service, "build_nl2agent_run_info", AsyncMock(return_value=adapter.run_info))
    events = [{"type": "nl2a", "content": "card"}, {"type": "execution_logs", "content": "hidden"},
              {"type": "tool_result", "content": "already admitted call finished"},
              {"type": "execution_logs", "content": "still hidden after the result"},
              {"type": "nl2a", "content": "duplicate card must stay hidden"},
              {"type": ending, "content": "actual outcome"}, {"type": "done", "content": ""}]

    async def run(*args, **kwargs):
        for event in events:
            yield json.dumps(event)

    monkeypatch.setattr(service, "agent_run", run)
    stream = await service.create_nl2agent_stream(
        NL2AgentRunRequest(query="create", agent_id=42), "tenant", "en",
        identity=AuthenticatedIdentity("owner", "tenant"))
    output = [json.loads(item.removeprefix("data: ")) async for item in stream]
    assert [item["type"] for item in output] == ["nl2a", "tool_result", ending, "done"]


@pytest.mark.asyncio
async def test_creator_persistence_keeps_native_terminal_envelope(monkeypatch):
    from management.services.conversation import creation_history as service

    event = {"type": "run_terminal", "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
             "turn_id": "turn", "status": "completed", "end_reason": "awaiting_input", "final_content": "",
             "final_block_ids": [], "error": None, "content": "serialized result"}
    saved = Mock(return_value=10)
    unit = Mock()
    monkeypatch.setattr(service, "save_message", saved)
    monkeypatch.setattr(service, "save_message_unit", unit)

    async def stream():
        yield "data: " + json.dumps(event) + "\n\n"

    result = [item async for item in service.persist_creation_stream(
        stream(), conversation_id=1, assistant_index=1, user_id="owner", tenant_id="tenant")]
    assert result == ["data: " + json.dumps(event) + "\n\n"]
    assert json.loads(unit.call_args.kwargs["unit_content"]) == event
    assert saved.call_args.kwargs["status"] == "completed"


def test_public_history_projects_native_tool_identity_without_changing_stored_event(monkeypatch):
    from management.services.conversation import service

    event = {"type": "tool", "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
             "turn_id": "turn", "sequence": 1, "content": "", "tool_call_id": "call", "local_call_id": "call",
             "tool_name": "nl2a_wrapper", "tool_arguments": {"agent_id": 42}}
    history = {"conversation_id": 1, "create_time": 0, "search_records": [], "image_records": [],
               "message_records": [{"message_id": 2, "role": "assistant", "message_content": "", "status": "completed",
                                    "opinion_flag": None, "units": [{"unit_type": "tool", "unit_content": json.dumps(event)}]}]}
    monkeypatch.setattr(service, "get_conversation_history", lambda *_: history)
    message = service.get_conversation_history_service(1, "owner")[0]["message"][0]
    part = next(p for p in message["message"] if p["type"] == "tool")
    assert part["content"] == ""
    assert part["tool_name"] == "nl2a_wrapper"
    assert part["tool_arguments"] == {"agent_id": 42}
    assert json.loads(part["tool_call_id"]) == ["turn", "", "call"]
    assert not {"runtime_mode", "schema_version", "agent_core"} & part.keys()
    assert json.loads(history["message_records"][0]["units"][0]["unit_content"]) == event


@pytest.mark.asyncio
@pytest.mark.parametrize("interactive", [True, False])
async def test_waiting_card_drains_worker_cleanup_while_real_stop_still_cancels(interactive):
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.orchestration.entry import agent_run
    from nexent.core.utils.observer import ProcessType

    adapter, observer, stop = setup_adapter()
    if interactive:
        observer.add_message("creator", ProcessType.EXECUTION_LOGS, CARD)
    else:
        stop.set()
    future = Future()
    manager = Mock()
    manager.submit.return_value = SimpleNamespace(future=future, execution_id="owned")
    info = AgentRunInfo(query="create", agent_config=adapter.run_info.agent_config,
                        model_config_list=[], observer=observer, stop_event=stop)

    async def complete():
        await asyncio.sleep(.15)
        observer.add_message("creator", ProcessType.OTHER, "worker cleanup completed")
        future.set_result(None)

    task = asyncio.create_task(complete())
    try:
        if interactive:
            output = [json.loads(item) async for item in agent_run(info, thread_manager=manager)]
            assert sum(item["type"] == "nl2a" for item in output) == 1
            assert any(item.get("content") == "worker cleanup completed" for item in output)
            manager.cancel.assert_not_called()
        else:
            with pytest.raises(asyncio.CancelledError):
                _ = [item async for item in agent_run(info, thread_manager=manager)]
            manager.cancel.assert_called_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
