# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'sdk'),str(ROOT/'backend'),str(ROOT/'test-e2e/infra/automation')]
from jiuwen_output_runtime import context_database,persist_output
from jiuwen_resource_runtime import resource_provider,run_resources
from jiuwen_collaboration_runtime import run_collaboration
from jiuwen_bridge_runtime import run_worker,stop_infrastructure

@pytest.fixture(scope="module",autouse=True)
def cleanup():
    yield
    stop_infrastructure()


pytestmark=[pytest.mark.case_id("JIUWEN-OUTPUT-D3-001"),pytest.mark.stage("D3")]

@pytest.mark.parametrize("protocol",["native","text"])
@pytest.mark.parametrize("resource",["chain","jiuwen","smolagents","a2a","echo"])
def test_runtime_output_roundtrip(monkeypatch,tmp_path,protocol,resource):
    with context_database(monkeypatch):
        if resource=="chain":
            with resource_provider(tmp_path) as url:
                info,state,output,calls,effects,_=asyncio.run(run_resources(monkeypatch,tmp_path,url,protocol))
            assert calls==[(2,3)] and state["mcp_calls"]==1 and effects=="x"
            assert state["saw_skill"]
        elif resource == "echo":
            info,state,output=asyncio.run(run_worker(monkeypatch,protocol,"echo_history"))
            assert state["tool_calls"] == [(2,3)]
            assert len(state["requests"]) == 2
            assert info.run_result.final_content == "SPIKE_FINAL_RESULT_5"
            assert "MODEL_PRIVATE_HISTORY" not in json.dumps(output)
            assert "<final_answer>" not in json.dumps(output)
        else:
            info,state,output,_=asyncio.run(run_collaboration(monkeypatch,"jiuwen",resource,protocol,"JSONRPC"))
            assert state["auth_ok"] and all(state["auth_ok"])
        assert info.attempt_outcome=="completed",output[-2:]
        root=[e for e in output if e.get("runtime_mode")=="native_agent" and not e.get("invocation_id")]
        assert sum(e["type"]=="run_terminal" for e in root)==1
        assert not any(e["type"]=="model_output_thinking" for e in root)
        assert any(e["type"]=="step_observation" for e in root)
        from nexent.core.agents.context import ContextManagerConfig
        from nexent.core.agents.context.policy import resolve_policy
        cfg = info.agent_config.context_manager_config or ContextManagerConfig()
        expected_capacity = {"context_window_tokens": cfg.context_window_tokens or None,
            "token_threshold": cfg.token_threshold or None,
            "effective_input_limit_tokens": cfg.effective_input_limit_tokens or None,
            "context_processing_mode": resolve_policy(cfg.policy_layers).processing_mode.value}
        assert all(e["context_capacity"] == expected_capacity for e in root if e["type"] == "step_observation")
        assert [e["sequence"] for e in root]==sorted(set(e["sequence"] for e in root))
        tools=[e for e in output if e.get("runtime_mode")=="native_agent" and e["type"]=="tool"]
        results=[e for e in output if e.get("runtime_mode")=="native_agent" and e["type"]=="tool_result"]
        assert tools and results
        for call in tools:
            result=next(r for r in results if r["local_call_id"]==call["local_call_id"])
            assert result.get("invocation_id")==call.get("invocation_id")
            assert result["provider_call_id"]==call["provider_call_id"]
            assert result["result"]
        if protocol=="native":assert any(e["provider_call_id"] for e in tools)
        assistant,saved,wire=asyncio.run(persist_output(monkeypatch,info,output))
        public = [json.loads(line[5:]) for frame in wire for line in frame.splitlines()
                  if line.startswith("data:")]
        forbidden = {"model_output", "tool_result", "step_observation", "run_terminal"}
        assert not any(e.get("type") in forbidden for e in public)
        assert not any(e.get("runtime_mode") == "native_agent" for e in public)
        assert any(e.get("type") == "token_count" for e in public)
        assert sum(e.get("type") == "final_answer" and not e.get("invocation_id") for e in public) == 1
        public_tools = {e["tool_call_id"] for e in public if e.get("type") == "tool"}
        assert all(e["tool_call_id"] in public_tools for e in public if e.get("type") == "execution_logs" and e.get("local_call_id"))
        from management.services.conversation.service import get_conversation_history_service
        history = get_conversation_history_service(info.conversation_id, "owner")[0]
        public_history = next(m for m in history["message"] if m["role"] == "assistant")["message"]
        assert not any(e.get("type") in forbidden for e in public_history)
        assert sum(e.get("type") == "final_answer" and not e.get("invocation_id") for e in public_history) == 1
        for restored in saved:
            if restored["type"] not in {
                "step_count", "tool", "tool_result", "step_observation", "run_terminal"
            }:
                continue
            live = next(e for e in output if (e.get("turn_id"), e.get("sequence"))
                        == (restored.get("turn_id"), restored.get("sequence")))
            assert restored["content"] == live["content"], "Saved event content acquired an extra envelope"
        meaningful = {(e.get("turn_id"), e.get("step_id")) for e in output
                      if e.get("runtime_mode") == "native_agent" and e["type"] in {"tool", "model_output_deep_thinking"}}
        for live in output:
            if live["type"] == "step_count" and (live.get("turn_id"), live.get("step_id")) in meaningful:
                assert any((e.get("turn_id"), e.get("sequence")) == (live.get("turn_id"), live.get("sequence"))
                           for e in saved), "Meaningful reasoning/action step label was lost"
        live_capacity = {(e["turn_id"], e["sequence"]): e["context_capacity"]
                         for e in root if e["type"] == "step_observation"}
        saved_capacity = {(e["turn_id"], e["sequence"]): e["context_capacity"]
                          for e in saved if e["type"] == "step_observation" and not e.get("invocation_id")}
        assert saved_capacity == live_capacity
        assert assistant["status"]=="completed"
        assert assistant["message_content"]==info.run_result.final_content
        assert sum(e["type"]=="run_terminal" and not e.get("invocation_id") for e in saved)==1
        assert {e["local_call_id"] for e in results}=={e["local_call_id"] for e in saved if e["type"]=="tool_result"}
        for call in results:
            assert next(e for e in saved if e["type"]=="tool_result" and e["local_call_id"]==call["local_call_id"])["result"]==call["result"]
        terminal=next(e for e in saved if e["type"]=="run_terminal" and not e.get("invocation_id"))
        assert terminal["final_block_ids"]
        assert "fixture-only" not in json.dumps(saved)
        assert "MODEL_PRIVATE_HISTORY" not in json.dumps(saved)
        assert "<completed_action_history" not in assistant["message_content"]
        assert "<final_answer>" not in assistant["message_content"]


@pytest.mark.parametrize("protocol", ["native", "text"])
def test_clarification_terminal_history_before_and_after_submission(monkeypatch, protocol):
    from management.db.client import get_db_session
    from management.db.models import ConversationMessage, ConversationMessageUnit
    from management.db.conversation.repository import create_conversation_message, get_conversation_history
    from management.services.conversation.service import get_conversation_history_service

    with context_database(monkeypatch):
        info, state, output = asyncio.run(run_worker(monkeypatch, protocol, "clarify"))
        assert info.run_result.status == "completed" and info.run_result.end_reason == "awaiting_input"
        assert len(state["requests"]) == 1 and not state["tool_calls"]
        assistant, saved, _ = asyncio.run(persist_output(monkeypatch, info, output))

        def check_waiting(record):
            assert record["status"] == "completed" and record["message_content"] == ""
            terminal = next(json.loads(u["unit_content"]) for u in record["units"]
                            if u["unit_type"] == "run_terminal")
            assert terminal["status"] == "completed" and terminal["end_reason"] == "awaiting_input"
            assert terminal["final_content"] == "" and terminal["final_block_ids"] == []
            assert terminal["error"] is None
            assert json.loads(terminal["content"])["end_reason"] == "awaiting_input"
            assert "JIUWEN_FINAL_OUTPUT_INVALID" not in json.dumps(record)

        check_waiting(assistant)

        def check_public_history():
            public = get_conversation_history_service(info.conversation_id, "owner")[0]
            restored = next(r for r in public["message"] if r["role"] == "assistant")
            assert restored["status"] == "completed"
            assert any(u["type"] == "human_interaction" for u in restored["message"])
            assert not any(u["type"] in {"run_terminal", "model_output", "tool_result", "step_observation"}
                           for u in restored["message"])
            assert not any(u["type"] == "final_answer" and u["content"] for u in restored["message"])
            assert "JIUWEN_FINAL_OUTPUT_INVALID" not in json.dumps(public)


        check_public_history()
        card = next(u for u in assistant["units"] if u["unit_type"] == "human_interaction")
        form = json.loads(json.loads(card["unit_content"])["content"])
        create_conversation_message({"conversation_id": info.conversation_id, "message_idx": 2, "role": "user",
            "content": "Birth date supplied", "clarification_response": {
                "schema_version": 1, "form": form,
                "unit_index": card["unit_index"],
                "answers": [{"questionId": "birth", "value": "1998-06-15", "otherText": None}]}}, "owner")

        def records():
            with get_db_session() as session:
                return {model.__name__: [{c.name: getattr(row, c.name) for c in model.__table__.columns}
                    for row in session.query(model).filter_by(conversation_id=info.conversation_id)
                    .order_by(*model.__table__.primary_key.columns)]
                    for model in (ConversationMessage, ConversationMessageUnit)}

        before = records()
        restored = get_conversation_history(info.conversation_id, "owner")["message_records"]
        check_waiting(next(r for r in restored if r["role"] == "assistant"))
        response = next(json.loads(u["unit_content"]) for r in restored for u in r["units"] or []
                        if u["unit_type"] == "clarification_response")
        assert response["source_message_id"] == assistant["message_id"]
        assert response["unit_index"] == card["unit_index"]
        check_public_history()
        assert records() == before
