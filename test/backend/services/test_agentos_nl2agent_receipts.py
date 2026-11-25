# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local creator tools retain their trusted receipts across signed callbacks."""

import json
from threading import Event

import pytest

from contracts.agentos import PreparedAgentCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.nl2agent_tool_config import NL2AGENT_RECEIPT_KEY
from runtime.agentos import prepared_agent_creator as runtime


def test_callback_catalog_preserves_all_local_tools_and_receipts(mocker):
    payload = PreparedAgentCreatorRun.model_validate({
        "mode": "nl2agent", "agent_id": 7, "run_id": "a" * 32, "conversation_id": 9,
        "input": {"query": "Create an Agent"}, "bound_resources": "Verified state",
        "model": {"model_id": 5, "alias": "model", "revision": "v1"},
        "input_budget": 8192, "context_window_tokens": 8192,
    })
    actor = ServicePrincipal("owner", "tenant")
    observer = runtime._Nl2AgentBoundaryObserver(
        lang="en", stop_event=Event(), agent_id=7, run_id=payload.run_id, conversation_id="9",
    )
    invoke = mocker.patch.object(runtime, "_invoke_tool", return_value={
        "agentos_tool_result": True, "content": [{"type": "text", "text": "visible"}],
        "meta": {NL2AGENT_RECEIPT_KEY: {
            "event_id": "receipt", "run_id": payload.run_id, "conversation_id": "9",
            "payload": {"subtype": "requirement_clarification", "agent_id": 7, "questions": []},
        }},
    })
    tools = {config.name: config.metadata for config in runtime._callback_tools(payload, actor, observer)}
    assert set(tools) == {config.name for config in runtime.create_nl2agent_mcp_tool_configs()}
    assert tools["nl2a_wrapper"].invoke({"subtype": "requirement_clarification"}) == "visible"
    assert invoke.call_args.args == (payload.run_id, actor, "wrapper", 7)
    assert observer.turn_complete
    messages = [json.loads(item) for item in observer.get_cached_message()]
    assert [item["type"] for item in messages] == ["nl2a"]
    assert tools["nl2a_read_generation_context"].invoke({"agent_id": 8})["code"] == "agent_context_mismatch"
    assert invoke.call_count == 1


@pytest.mark.asyncio
async def test_signed_resource_tool_uses_persisted_conversation_scope(mocker):
    from contracts.agentos import NL2AgentToolCall
    from fastmcp.tools.tool import ToolResult
    from management.services.agent import nl2agent_callback as callback
    from management.services.agent import nl2agent_tools as tools
    from tool_collection.mcp import nl2agent_resource_tools as resources

    scope = tools.NL2AgentToolScope(7, "owner", "tenant", False, "a" * 32, "9")
    mocker.patch.object(callback, "_load_grant", return_value=scope)

    async def inline(_name, func, *args, **kwargs):
        return func(*args)

    async def show():
        assert resources.tool_headers()[tools.NL2AGENT_CONVERSATION_ID_HEADER] == "9"
        assert resources._tool_actor() == ("owner", "tenant")
        return ToolResult(content="visible", meta={"trusted": "receipt"})

    mocker.patch.object(callback, "run_blocking", side_effect=inline)
    mocker.patch.object(resources, "show_resource_card", side_effect=show)
    mocker.patch.object(tools, "get_http_request", side_effect=AssertionError("No public token required"))
    call = NL2AgentToolCall(run_id=scope.run_id, agent_id=7, tool="show_resource_card", arguments={})
    result = await callback.execute_nl2agent_tool(call, ServicePrincipal("owner", "tenant"))
    assert result["meta"] == {"trusted": "receipt"}
    assert result["content"][0]["text"] == "visible"
    assert tools._tool_scope.get() is None
