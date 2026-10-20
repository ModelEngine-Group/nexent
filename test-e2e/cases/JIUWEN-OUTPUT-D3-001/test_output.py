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
