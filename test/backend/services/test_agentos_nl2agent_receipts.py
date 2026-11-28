# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local creator tools retain their trusted receipts across signed callbacks."""

import json
from threading import Event
from types import SimpleNamespace

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


def test_creator_tracks_pending_verification_across_callback_results(mocker):
    payload = SimpleNamespace(agent_id=7, run_id="a" * 32)
    actor = ServicePrincipal("owner", "tenant")
    observer = runtime._Nl2AgentBoundaryObserver(
        lang="en", stop_event=Event(), agent_id=7, run_id=payload.run_id, conversation_id="9",
    )

    def wrapped(result):
        return {"agentos_tool_result": True, "content": [{"text": json.dumps(result)}], "meta": None}

    first = {"status": "success", "verification_batch_id": "first"}
    next_batch = {"status": "success", "verification_batch_id": "second"}
    premature_card = {"status": "error", "code": "verification_incomplete", "verification_batch_id": "second"}
    mocker.patch.object(runtime, "_invoke_tool", side_effect=[
        first, wrapped(next_batch), wrapped(premature_card), wrapped({"status": "success", "card_required": False}),
    ])
    tools = {config.name: config.metadata for config in runtime._callback_tools(payload, actor, observer)}
    assert not observer.has_pending_nl2agent_verification()
    assert tools["nl2a_discover_requirements"].invoke({}) == first
    assert observer.has_pending_nl2agent_verification()
    verify = tools["nl2a_verify_requirements"]
    assert json.loads(verify.invoke({"verification_batch_id": "first", "checks": []})) == next_batch
    assert observer.has_pending_nl2agent_verification()
    assert json.loads(tools["nl2a_show_resource_card"].invoke({})) == premature_card
    assert observer.has_pending_nl2agent_verification()
    verify.invoke({"verification_batch_id": "second", "checks": []})
    assert not observer.has_pending_nl2agent_verification()


def test_full_generation_advances_only_on_trusted_receipts():
    observer = runtime._Nl2AgentBoundaryObserver(
        lang="en", stop_event=Event(), agent_id=7, run_id="run", conversation_id="9",
        generation_stage="prepare",
    )

    def send(tool, payload, event_id, run_id="run"):
        observer.on_mcp_tool_result(tool, {NL2AGENT_RECEIPT_KEY: {
            "event_id": event_id, "run_id": run_id, "conversation_id": "9",
            "payload": {"agent_id": 7, **payload},
        }})

    assert observer.pending_full_generation_action() == "prepare"
    send("nl2a_save_agent_draft_fields", {"event": "agent_draft_fields_saved", "updated_fields": ["name"]}, "name")
    assert observer.pending_full_generation_action() == "save_description"
    send("nl2a_save_agent_draft_fields", {"event": "agent_draft_fields_saved",
                                       "updated_fields": ["description"]}, "description")
    assert observer.pending_full_generation_action() == "discover_resources"
    send("nl2a_validate_agent_generation_complete", {"event": "agent_generation_completed"}, "early")
    assert observer.pending_full_generation_action() == "discover_resources"
    observer.record_verification_result("discover_requirements", {"status": "success", "next_step": "prepare_search_queries"})
    assert observer.pending_full_generation_action() == "prepare_search_queries"
    observer.record_verification_result("discover_requirements", {"status": "success", "verification_batch_id": "batch"})
    assert observer.pending_full_generation_action() == "verify_resources"
    assert observer.has_pending_nl2agent_verification()
    observer.record_verification_result("show_resource_card", "not a JSON observation")
    observer.record_verification_result("verify_requirements", "[]")
    observer.record_verification_result("verify_requirements", {"status": "error", "code": "verification_assessments_incomplete"})
    assert observer.pending_full_generation_action() == "verify_resources"
    observer.record_verification_result("verify_requirements", {"status": "success", "verification_batch_id": None})
    assert observer.pending_full_generation_action() == "show_resource_card"
    assert not observer.has_pending_nl2agent_verification()
    observer.record_verification_result("show_resource_card", {"status": "success", "card_required": False})
    assert observer.pending_full_generation_action() == "generate_prompt"
    send("nl2a_save_agent_draft_fields", {"event": "agent_draft_fields_saved", "updated_fields": ["prompt"]}, "prompt")
    assert observer.pending_full_generation_action() == "finalize"
    send("nl2a_validate_agent_generation_complete", {"event": "agent_generation_completed"}, "foreign", "other")
    assert observer.pending_full_generation_action() == "finalize"
    send("nl2a_save_agent_draft_fields", {"event": "agent_draft_fields_saved", "updated_fields": ["greeting_message"]},
         "greeting")
    assert observer.pending_full_generation_action() == "finalize"
    send("nl2a_save_agent_draft_fields", {"event": "agent_draft_fields_saved", "updated_fields": ["example_questions"]},
         "questions")
    assert observer.pending_full_generation_action() == "validate"
    send("nl2a_validate_agent_generation_complete", {"event": "agent_generation_completed"}, "validated")
    assert observer.pending_full_generation_action() is None


def test_authorized_resource_card_pauses_full_generation_and_clears_pending_actions():
    observer = runtime._Nl2AgentBoundaryObserver(
        lang="en", stop_event=Event(), agent_id=7, run_id="run", conversation_id="9", generation_stage="prepare",
    )
    observer.record_verification_result("show_resource_card", {"status": "error", "code": "verification_incomplete"})
    assert observer.has_pending_nl2agent_verification()
    observer.on_mcp_tool_result("nl2a_show_resource_card", {NL2AGENT_RECEIPT_KEY: {
        "event_id": "resource-card", "run_id": "run", "conversation_id": "9",
        "payload": {"agent_id": 7, "subtype": "requirement_resources", "protocol_version": 2,
                    "run_id": "run", "conversation_id": "9", "card_id": "card", "state_version": 2},
    }})
    assert observer.turn_complete
    assert observer.pending_full_generation_action() is None
    assert not observer.has_pending_nl2agent_verification()
    assert [json.loads(item)["type"] for item in observer.get_cached_message()] == ["nl2a"]


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
