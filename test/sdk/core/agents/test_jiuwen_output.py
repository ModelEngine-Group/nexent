# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public output ordering, explicit finality, call correlation and error contracts."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from nexent.core.agents.contracts.output import RunResult, StepObservation
from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
from nexent.core.model_service.contracts import AssistantMessage, TokenUsage, ToolCall
from nexent.core.utils.observer import MessageObserver


def make():
    observer=MessageObserver()
    return JiuwenEventAdapter(observer,"agent","turn"),observer


def event(kind,**kwargs):
    return SimpleNamespace(type=kind,**kwargs)


def output(observer):
    return [json.loads(value) for value in observer.get_cached_message()]


def test_ordered_content_and_reasoning_are_not_reclassified_or_duplicated():
    bridge,observer=make()
    bridge.begin_step(None)
    bridge.model_event(event("text_delta",delta="First "))
    bridge.model_event(event("reasoning_delta",delta="Explicit reasoning"))
    bridge.model_event(event("text_delta",delta="body"))
    bridge.model_event(event("message_completed",message=AssistantMessage(
        content_parts=[{"type":"text","text":"First body"}],
        reasoning_parts=[{"type":"text","text":"Explicit reasoning"}],finish_reason="stop")))
    bridge.emit({"type":"answer","payload":{"output":"First body"}})
    result=bridge.finish()
    events=output(observer)
    native=[e for e in events if "sequence" in e]
    assert [e["type"] for e in native]==["step_count","model_output","model_output_deep_thinking","model_output","step_observation","run_terminal"]
    assert [e["sequence"] for e in native]==list(range(1,7))
    assert result.status=="completed" and result.final_block_ids==[native[1]["block_id"]]
    assert sum(e["type"]=="final_answer" for e in events)==1
    assert native[-2]["usage"]["origin"]=="unknown" and native[-2]["usage"]["input_tokens"] is None
    assert bridge.finish() is result
    with pytest.raises(RuntimeError,match="after terminal"):
        bridge.output(type("Kind",(),{"value":"model_output"})(),"late")


def test_tool_pair_preserves_full_provider_id_and_invocation_identity():
    bridge,observer=make()
    provider_id="provider-"+"a"*300
    bridge.calls=[ToolCall(provider_call_id=provider_id,index=0,name="tool",raw_arguments='{"a":1}',parsed_arguments={"a":1})]
    with observer.tool_call_context("local"):
        found=bridge.tool_call("tool",{"a":1},"local")
        bridge.tool_result("local",found,"Exact error",True)
    call,result=output(observer)
    assert call["provider_call_id"]==result["provider_call_id"]==provider_id
    assert call["local_call_id"]==result["local_call_id"]=="local"
    assert result["result"]=="Exact error" and result["is_error"]


@pytest.mark.parametrize("status",["failed","stopped"])
def test_unsuccessful_results_cannot_confirm_content(status):
    with pytest.raises(ValidationError):RunResult(turn_id="turn",status=status,end_reason="error",final_content="False success")
    bridge,observer=make()
    bridge.begin_step(None)
    bridge.model_event(event("text_delta",delta="Visible partial"))
    result=bridge.finish(status)
    assert result.status==status and result.final_content=="" and not result.final_block_ids
    events=output(observer)
    assert events[1]["content"]=="Visible partial" and events[-1]["type"]=="run_terminal"
    assert not any(e["type"]=="final_answer" for e in events)


def test_missing_and_duplicate_runner_terminal_are_contract_errors():
    bridge,observer=make()
    assert bridge.finish().end_reason=="JIUWEN_TERMINAL_MISSING"
    bridge,observer=make()
    bridge.emit({"type":"answer","payload":{"output":"Final"}})
    with pytest.raises(RuntimeError,match="multiple terminal"):
        bridge.emit({"type":"answer","payload":{"output":"Later"}})
    assert bridge.finish().status=="failed"
    assert not any(e["type"]=="final_answer" for e in output(observer))


def test_native_llm_output_does_not_duplicate_canonical_model_events():
    bridge,observer=make()
    bridge.emit({"type":"llm_output","payload":{"content":"Duplicate","reasoning_content":"Duplicate"}})
    assert output(observer)==[]
    observation=StepObservation(turn_id="turn",block_id="block",step_number=1,duration=0,usage=TokenUsage())
    assert observation.usage.total_tokens is None


@pytest.mark.parametrize("result", [{"success":False,"data":{"result":"MCP error"}},
                                   '{"status":"error","message":"Skill error"}'])
def test_explicit_resource_failure_status_survives_later_text(result):
    from threading import Event
    from nexent.core.agents.contracts.config import AgentConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

    observer=MessageObserver()
    info=AgentRunInfo(query="Current",observer=observer,stop_event=Event(),model_config_list=[],
                     agent_config=AgentConfig(name="agent",description="Fixture",model_name="fixture",tools=[]))
    adapter=JiuwenAdapter(info)
    with adapter._observe_tool("tool",{}):adapter._resource_result(result)
    events=output(observer)
    saved=next(e for e in events if e["type"]=="tool_result")
    assert saved["is_error"] is True
    assert "error" in saved["result"]
    adapter.events.emit({"type":"answer","payload":{"output":"Continued"}})
    assert adapter.events.finish().status=="completed"
    assert saved["is_error"] is True



def test_reused_run_info_does_not_keep_old_core_terminal(mocker):
    from threading import Event
    from nexent.core.agents.contracts.config import AgentConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.orchestration.entry import _agent_run_thread

    info=AgentRunInfo(query="New task",observer=MessageObserver(),stop_event=Event(),model_config_list=[],
                     agent_config=AgentConfig(name="agent",description="Fixture",model_name="fixture",tools=[]))
    info.run_result=RunResult(turn_id="old",status="completed",end_reason="runner_answer",final_content="Old")
    info.stop_event.set()
    mocker.patch("nexent.core.agents.factory.AgentCoreFactory.create")
    _agent_run_thread(info)
    assert info.run_result is None and info.attempt_outcome=="stopped"
