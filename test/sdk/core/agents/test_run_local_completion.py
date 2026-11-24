# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual sender pairing and independent, run-local CM replacement boundaries."""

import asyncio
import json
from concurrent.futures import Future
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing
from test_jiuwen_context import make_bridge
from test_jiuwen_model_service import saved_profile as saved_profile

from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.agents.cores.jiuwen.context import SummaryModel
from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.concurrency import RunCancellationScope
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse
from nexent.core.model_service.service import ModelService
from nexent.core.model_service.sse import SSEEvent


class Sender:
    def __init__(self, counts, retry=False):
        self.counts, self.retry = counts, retry
        self.bodies = []
        self.summary_count = 0
        self.first_tool_call = False

    def freeze_credentials(self, _request):
        return self

    def invoke(self, request, **kwargs):
        body = json.loads(request.body_bytes)
        self.bodies.append(deepcopy(body))
        if self.retry:
            self.retry = False
            raise ModelTransportError("HTTP_TIMEOUT")
        summary = "Conversation content to summarize:" in json.dumps(body)
        if summary:
            self.summary_count += 1
        text = "LOCAL_COMPACT_VIEW" if summary else "VISIBLE_ACCEPTED_OUTPUT"
        usage = {"prompt_tokens": self.counts[0], "completion_tokens": self.counts[1],
                 "prompt_tokens_details": {"cached_tokens": 60}}
        usage = {key: value for key, value in usage.items() if value is not None}
        if body.get("stream"):
            return [SSEEvent(json.dumps({"choices": [{"index": 0, "delta": {"content": text, "reasoning_content": "PRIVATE_THOUGHT"},
                                                      "finish_reason": None}]})),
                    SSEEvent(json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                                         "usage": usage})), SSEEvent("[DONE]")]
        message = {"role": "assistant", "content": text, "reasoning_content": "PRIVATE_THOUGHT"}
        if self.first_tool_call and not summary:
            self.first_tool_call = False
            message["tool_calls"] = [{"id": "new-call", "type": "function", "function": {
                "name": "add", "arguments": '{"a":2,"b":3}'}}]
        return RawHttpResponse(200, {}, json.dumps({"choices": [{"index": 0,
            "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": usage}).encode())

    async def ainvoke(self, request, **kwargs):
        return self.invoke(request, **kwargs)

    @contextmanager
    def stream(self, request, **kwargs):
        yield iter(self.invoke(request, **kwargs))


def old_items():
    return [ContextItem.from_input(ContextItemInput(id="persisted:10", type="history_summary", content={
                "unit_id": 10, "summary": {"markdown": "PRIOR_PERSISTED_SUMMARY"},
                "covered_through_message_id": 2})),
            ContextItem.from_input(ContextItemInput(id="old-turn", type="conversation_turn", content={
                "user_message": "OLD_HISTORY_TASK " * 100, "assistant_final_answer": "OLD_HISTORY_ANSWER",
                "user_message_id": 3, "assistant_message_id": 4}))]


def submit(_lane, _spec, work, *args):
    future = Future()
    try:
        future.set_result(work(*args))
    except BaseException as error:
        future.set_exception(error)
    return SimpleNamespace(future=future)


def setup_core(core, profile, counts, *, retry=False, history=True):
    sender = Sender(counts, retry)
    policy = SimpleNamespace(max_attempts=2, calculate_backoff=lambda _attempt: 0)
    service = ModelService(lambda _profile: sender, retry_policy=policy)
    items = old_items() if history else []
    if core == "jiuwen":
        bridge, info = make_bridge("adaptive_compact", items)
        info.query = "CURRENT_TASK " + "x" * 3000
        bridge.manager.submit.side_effect = submit
        def accept(event):
            model.observed_input = event.message._agent_input
            bridge.accepted_response(event.message, model.last_native_message)
        model = JiuwenServiceModel(service, profile, bridge.scope, prepare_messages=bridge.prepare_messages,
            on_event=accept)
        bridge.summary_model = SummaryModel(model)
        bridge.context_manager._request_token_estimator = bridge._estimate_wire
        bridge.context_manager.config.effective_input_limit_tokens = 1000
        bridge.context_manager.config.compaction_trigger_threshold_tokens = 100
        bridge.context_manager.config.compaction_target_tokens = 1000
        return sender, bridge, model, info
    config = ContextManagerConfig(context_window_tokens=1000, effective_input_limit_tokens=1000,
        compaction_trigger_threshold_tokens=100, compaction_target_tokens=500,
        policy_layers={"agent": {"processing_mode": "adaptive_compact"}})
    managed = ManagedContextRuntime(ContextManager(config), items)
    model = LegacyChatModel(profile, service, cancellation_scope=RunCancellationScope())
    memory = SimpleNamespace(steps=[TaskStep(task="CURRENT_TASK " + "x" * 3000)])
    managed.prepare_run(memory=memory, fallback_system_prompt="FIXED_POLICY")
    return sender, managed, model, memory


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
@pytest.mark.parametrize("retry", [False, True])
async def test_actual_attempt_material_and_next_send_keep_uncovered_tail(saved_profile, core, retry):
    sender, runtime, model, state = setup_core(core, saved_profile, (70, 30), retry=retry)
    sink = []
    runtime.context_manager.config.history_summary_sink = sink.append
    if core == "jiuwen":
        messages = [{"role": "system", "content": "FIXED_POLICY"}, {"role": "user", "content": state.query}]
        await model.invoke(messages)
        await asyncio.wrap_future(runtime._maintenance_execution.future)
        response = model.last_message
        snapshot = model.observed_input
    else:
        prepared = runtime.prepare_step(model=model, memory=state, current_run_start_idx=0)
        response = model(prepared.messages)
        snapshot = response.raw._agent_input
        response.nexent_context_accepted = True
        state.steps.append(ActionStep(step_number=1, model_output=response.content,
            observations="LATER_TOOL_RESULT", timing=Timing(start_time=0)))
        runtime.complete_step(model=model, memory=state, current_run_start_idx=0, response=response)
        response = response.raw
    assert response._agent_input is None
    assert snapshot.attempt == (2 if retry else 1)
    assert snapshot is not None and "_agent_input" not in response.model_dump_json()
    assert sender.summary_count == 1 and sink == []
    summary_body = sender.bodies[-1]
    summary_text = "\n".join(m["content"] if isinstance(m["content"], str) else
                             "".join(p.get("text", "") for p in m["content"] or [])
                             for m in summary_body["messages"])
    material = summary_text.split("Conversation content to summarize:\n", 1)[1]
    material = json.loads(material)
    actual = sender.bodies[1 if retry else 0]
    assert material["input"] == {key: actual[key] for key in ("messages", "tools") if key in actual}
    assert material["output"]["content"] == response.content_parts
    assert material["output"]["finish_reason"] == response.finish_reason
    assert "LATER_TOOL_RESULT" not in json.dumps(material) and "PRIVATE_THOUGHT" not in json.dumps(material)
    assert json.dumps(material).count("PRIOR_PERSISTED_SUMMARY") == 1
    assert runtime.context_manager.consume_history_summary_event() is None
    if core == "jiuwen":
        await model.invoke([*messages, {"role": "assistant", "content": "VISIBLE_ACCEPTED_OUTPUT"},
                            {"role": "user", "content": "LATER_TOOL_RESULT"}])
    else:
        prepared = runtime.prepare_step(model=model, memory=state, current_run_start_idx=0)
        model(prepared.messages)
    next_main = next(body for body in reversed(sender.bodies)
                     if "Conversation content to summarize:" not in json.dumps(body))
    rendered = json.dumps(next_main)
    assert "LOCAL_COMPACT_VIEW" in rendered and "LATER_TOOL_RESULT" in rendered and "CURRENT_TASK" in rendered
    assert "FIXED_POLICY" in rendered and "OLD_HISTORY_TASK" not in rendered
    assert "PRIOR_PERSISTED_SUMMARY" not in rendered and sink == []
    fresh = ContextManager().prepare_items_context("", items=old_items())
    assert "PRIOR_PERSISTED_SUMMARY" in str(fresh.items) and "LOCAL_COMPACT_VIEW" not in str(fresh.items)


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
@pytest.mark.parametrize("counts,history", [((70, 29), True), ((70, None), True), ((None, 30), True), ((100, 0), False)])
async def test_no_estimate_or_missing_usage_can_force_or_forge_a_summary(saved_profile, core, counts, history):
    sender, runtime, model, state = setup_core(core, saved_profile, counts, history=history)
    runtime.context_manager._message_tokens = lambda _messages: 100000
    if core == "jiuwen":
        await model.invoke([{"role": "user", "content": state.query}])
        await asyncio.wrap_future(runtime._maintenance_execution.future)
    else:
        prepared = runtime.prepare_step(model=model, memory=state, current_run_start_idx=0)
        response = model(prepared.messages)
        response.nexent_context_accepted = True
        runtime.complete_step(model=model, memory=state, current_run_start_idx=0, response=response)
    assert sender.summary_count == 0 and runtime.context_manager._agent_history is None


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
@pytest.mark.parametrize("ending", ["empty", "cancelled", "rejected", "duplicate", "fork"])
async def test_acceptance_cancellation_and_empty_results_never_leak_to_checkpoints(saved_profile, core, ending):
    from nexent.core.agents.context.llm_summary import SummaryResult

    sender, runtime, model, state = setup_core(core, saved_profile, (70, 30))
    if core == "jiuwen":
        accepted = []
        model.on_event = lambda event: accepted.append(event.message)
        await model.invoke([{"role": "user", "content": state.query}])
        response = accepted[-1]
    else:
        prepared = runtime.prepare_step(model=model, memory=state, current_run_start_idx=0)
        response = model(prepared.messages)
        response.nexent_context_accepted = ending != "rejected"
    sink = []
    runtime.context_manager.config.history_summary_sink = sink.append
    calls = []

    def summarize(material, _model, **kwargs):
        calls.append((material, kwargs))
        if ending == "cancelled":
            model.scope.cancel() if core == "jiuwen" else model.cancellation_scope.cancel()
        if ending == "fork":
            fresh = runtime.context_manager.prepare_items_context("", items=old_items())
            runtime.context_manager.assemble_context_items(model=None, run_context=fresh)
        return SummaryResult(summary_text="" if ending == "empty" else "LOCAL_ONLY")

    runtime.context_manager._llm.generate_summary = summarize
    if core == "jiuwen":
        if ending != "rejected":
            runtime.accepted_response(response, model.last_native_message)
            await asyncio.wrap_future(runtime._maintenance_execution.future)
    else:
        runtime.complete_step(model=model, memory=state, current_run_start_idx=0, response=response)
    assert sink == [] and runtime.context_manager.consume_history_summary_event() is None
    assert (runtime.context_manager._agent_history is not None) == (ending == "duplicate")
    if ending == "duplicate":
        if core == "jiuwen":
            runtime.accepted_response(response, model.last_native_message)
            await asyncio.wrap_future(runtime._maintenance_execution.future)
        else:
            runtime.complete_step(model=model, memory=state, current_run_start_idx=0, response=response)
        assert len(calls) == 1
    elif ending == "rejected":
        assert calls == []
    if calls:
        assert calls[0][1]["retry_context_error"] is False


@pytest.mark.asyncio
async def test_native_transaction_closes_before_summary_and_later_result_stays_out_of_material(saved_profile):
    from test_jiuwen_model_service import TOOLS

    sender, runtime, model, state = setup_core("jiuwen", saved_profile, (70, 30))
    sender.first_tool_call = True
    messages = [{"role": "user", "content": state.query}]
    native = await model.invoke(messages, tools=TOOLS)
    assert native.tool_calls[0].id == "new-call"
    assert runtime._maintenance_execution is None and sender.summary_count == 0
    runtime.completed_tool("add", "AFTER_ACCEPTED_TOOL", "local", provider_call_id="new-call")
    await asyncio.wrap_future(runtime._maintenance_execution.future)
    assert sender.summary_count == 1
    summary = sender.bodies[-1]
    source = json.dumps(summary)
    assert "new-call" in source and "AFTER_ACCEPTED_TOOL" not in source
    assert "tools" in json.loads(model.observed_input.semantic_json)
    await model.invoke([*messages, {"role": "assistant", "content": "VISIBLE_ACCEPTED_OUTPUT", "tool_calls": [
        {"id": "new-call", "type": "function", "function": {"name": "add", "arguments": '{"a":2,"b":3}'}}]},
        {"role": "tool", "tool_call_id": "new-call", "content": "AFTER_ACCEPTED_TOOL"}], tools=TOOLS)
    body = next(body for body in reversed(sender.bodies)
                if "Conversation content to summarize:" not in json.dumps(body))
    assert [m["tool_call_id"] for m in body["messages"] if m.get("role") == "tool"] == ["new-call"]
    assert [m["tool_calls"][0]["id"] for m in body["messages"] if m.get("tool_calls")] == ["new-call"]
    assert "AFTER_ACCEPTED_TOOL" in json.dumps(body) and "LOCAL_COMPACT_VIEW" in json.dumps(body)


def test_run_local_summary_disables_lossy_context_error_retry():
    from unittest.mock import Mock

    from nexent.core.agents.context.llm_summary import LLMSummary
    from nexent.core.agents.context.step_renderer import StepRenderer

    config = ContextManagerConfig()
    model = Mock(spec=["__call__"], side_effect=ValueError("context length exceeded"))
    result = LLMSummary(config, StepRenderer(config)).generate_summary(
        "COMPLETE_MATERIAL " * 100, model, retry_context_error=False)
    assert result.summary_text is None and model.call_count == 1


def test_optional_execution_view_failure_does_not_block_run_local_history(saved_profile, mocker, caplog):
    sender, runtime, model, memory = setup_core("smolagents", saved_profile, (70, 30))
    prepared = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    response = model(prepared.messages)
    response.nexent_context_accepted = True
    mocker.patch.object(runtime, "_complete_sent_execution_views", side_effect=RuntimeError("view failed"))
    runtime.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
    assert runtime.context_manager._agent_history is not None
    assert sender.summary_count == 1 and "event=context_execution_view_failed" in caplog.text
    assert response.raw._agent_input is None
