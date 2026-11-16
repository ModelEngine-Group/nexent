# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Provider output caps must be explicit rather than context-planning fallbacks."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from openai import BadRequestError

from nexent.core.models.capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    CapacityReservePolicy,
    ContextBudgetCalculator,
    ContextBudgetCapacityMismatch,
    RequestBudgetOverrides,
)
from nexent.core.models.capacity_resolver import resolve_capacity
from nexent.core.models.openai_llm import OpenAIModel


def contract(default=None, source="model_default"):
    overrides = {"context_window_tokens": 32768, "max_output_tokens": 16384}
    if default is not None:
        overrides["default_output_reserve_tokens"] = default
    capacity = resolve_capacity(model_id="test-model", provider="test", operator_overrides=overrides,
                                capability_profiles={})
    kwargs = {}
    if source == "agent":
        kwargs.update(requested_output_tokens=4096, output_reserve_source="agent")
    if source == "request":
        kwargs["request_overrides"] = RequestBudgetOverrides(requested_output_tokens=8192)
    budget = ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy(), **kwargs
    )
    projection = {"capacity_fingerprint": capacity.fingerprint, "provider": capacity.provider,
                  "model_name": capacity.model_name, "default_output_reserve_tokens": default}
    return capacity, budget, projection


def model():
    result = OpenAIModel.__new__(OpenAIModel)
    result.client = MagicMock()
    result.model_id = "test-model"
    result.explicit_sampling = ()
    return result


@pytest.mark.parametrize("default,source,caller,expected", [
    (None, "model_default", None, None),
    (4096, "model_default", None, 4096),
    (8192, "model_default", None, 8192),
    (None, "agent", None, 4096),
    (None, "request", None, 8192),
    (None, "model_default", 4096, 4096),
])
def test_dispatch_omits_only_implicit_caps(default, source, caller, expected):
    capacity, budget, projection = contract(default, source)
    client = model()
    before = budget.model_dump()
    supplied = {} if caller is None else {"max_tokens": caller}
    client._dispatch_chat_completion(context_budget_snapshot=budget, capacity_snapshot=projection,
                                     messages=[], **supplied)
    sent = client.client.chat.completions.create.call_args.kwargs
    if expected is None:
        assert "max_tokens" not in sent
    else:
        assert sent["max_tokens"] == expected
    assert budget.model_dump() == before
    assert budget.effective_input_limit_tokens == 32768 - budget.requested_output_tokens
    assert budget.compaction_target_tokens < budget.compaction_trigger_threshold_tokens
    assert budget.compaction_trigger_threshold_tokens < budget.effective_input_limit_tokens
    assert budget.w1_fingerprint == capacity.fingerprint


@pytest.mark.parametrize("projection", [None, {}, {"provider": "test", "model_name": "test-model"}])
def test_legacy_missing_reserve_metadata_keeps_snapshot_cap(projection):
    _, budget, _ = contract()
    client = model()
    client._dispatch_chat_completion(context_budget_snapshot=budget, capacity_snapshot=projection, messages=[])
    assert client.client.chat.completions.create.call_args.kwargs["max_tokens"] == 4096


@pytest.mark.parametrize("failure", ["caller", "fingerprint", "model"])
def test_omission_does_not_bypass_trusted_budget_checks(failure):
    _, budget, projection = contract()
    kwargs = {}
    if failure == "caller":
        kwargs["max_tokens"] = 8192
        error = CallerMaxTokensOverrideForbidden
    elif failure == "model":
        projection["model_name"] = "other-model"
        error = ContextBudgetCapacityMismatch
    else:
        projection["capacity_fingerprint"] = "other-fingerprint"
        error = ContextBudgetCapacityMismatch
    client = model()
    with pytest.raises(error):
        client._dispatch_chat_completion(context_budget_snapshot=budget, capacity_snapshot=projection,
                                         messages=[], **kwargs)
    client.client.chat.completions.create.assert_not_called()


def test_sampling_fallback_does_not_restore_implicit_cap():
    _, budget, projection = contract()
    client = model()
    request = httpx.Request("POST", "http://fixture/v1/chat/completions")
    response = httpx.Response(400, request=request)
    client.client.chat.completions.create.side_effect = [
        BadRequestError("unsupported temperature", response=response, body={}), "ok"
    ]
    assert client._dispatch_chat_completion(context_budget_snapshot=budget, capacity_snapshot=projection,
                                            messages=[], temperature=0.2) == "ok"
    assert client.client.chat.completions.create.call_count == 2
    assert all("max_tokens" not in call.kwargs
               for call in client.client.chat.completions.create.call_args_list)


@pytest.mark.parametrize("outcome", ["success", "empty_length", "overflow_then_success", "overflow_exhausted"])
def test_streaming_and_overflow_recovery_without_wire_cap(outcome):
    from openai import OpenAI

    from nexent.core.context_runtime.contracts import FinalContext
    from nexent.core.models.retry import ModelInvocationTerminalError
    from nexent.core.utils.observer import MessageObserver

    _, budget, projection = contract()
    requests = []
    rebuilds = []

    def provider(request):
        requests.append(json.loads(request.content))
        if outcome == "overflow_exhausted" or (outcome == "overflow_then_success" and len(requests) == 1):
            return httpx.Response(400, json={"error": {
                "message": "maximum context length exceeded", "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }})
        empty = outcome == "empty_length"
        delta = {"role": "assistant", "reasoning_content": "thinking"} if empty else {
            "role": "assistant", "content": "<final_answer>actual reply</final_answer>"
        }
        chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": 0,
                 "model": "test-model", "choices": [{"index": 0, "delta": delta,
                 "finish_reason": "length" if empty else "stop"}],
                 "usage": {"prompt_tokens": 16, "completion_tokens": 4096 if empty else 10,
                           "total_tokens": 4112 if empty else 26}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

    def rebuild():
        rebuilds.append(True)
        return FinalContext(messages=[{"role": "user", "content": "rebuilt context"}])

    instance = OpenAIModel(observer=MessageObserver(lang="en"), model_id="test-model",
                           api_base="http://provider.invalid/v1", api_key="fixture-only",
                           capacity_snapshot=projection, context_budget_snapshot=budget)
    original_client = instance.client
    with OpenAI(api_key="fixture-only", base_url="http://provider.invalid/v1", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(provider))) as client:
        instance.client = client
        if outcome in {"empty_length", "overflow_exhausted"}:
            with pytest.raises(ModelInvocationTerminalError):
                instance([{"role": "user", "content": "original context"}], context_rebuild=rebuild)
        else:
            result = instance([{"role": "user", "content": "original context"}], context_rebuild=rebuild)
            assert "actual reply" in result.content
    original_client.close()
    assert all("max_tokens" not in request for request in requests)
    assert len(requests) == {"success": 1, "empty_length": 1,
                             "overflow_then_success": 2, "overflow_exhausted": 3}[outcome]
    assert len(rebuilds) == {"success": 0, "empty_length": 0,
                            "overflow_then_success": 1, "overflow_exhausted": 2}[outcome]
    if rebuilds:
        assert all("rebuilt context" in str(request["messages"]) for request in requests[1:])
    assert instance.context_budget_snapshot == budget
    if outcome == "empty_length":
        assert instance.last_response_diagnostics["requested_output_tokens"] is None
        assert instance.last_response_diagnostics["reasoning_only_budget_exhausted"] is True


@pytest.mark.parametrize("default", [None, 4096])
def test_resolved_budget_keeps_history_compaction_and_final_fit(default):
    from types import SimpleNamespace

    from smolagents.memory import AgentMemory

    from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
    from nexent.core.agents.context.policy import ContextPolicy, ContextProcessingMode, PolicyLayers

    _, budget, projection = contract(default)
    manager = ContextManager(ContextManagerConfig(
        context_window_tokens=32768,
        effective_input_limit_tokens=budget.effective_input_limit_tokens,
        compaction_trigger_threshold_tokens=budget.compaction_trigger_threshold_tokens,
        compaction_target_tokens=budget.compaction_target_tokens,
        policy_layers=PolicyLayers(request=ContextPolicy(processing_mode=ContextProcessingMode.ADAPTIVE_COMPACT)),
    ))
    item = ContextItemInput(id="turn:1", type="conversation_turn", content={
        "user_message": "old question " * 15000, "assistant_final_answer": "old answer " * 15000,
        "user_message_id": 1, "assistant_message_id": 2,
    })
    memory = AgentMemory(system_prompt="system")
    run = manager.prepare_run_context(memory, "", items=[item])
    summary = "# Compact Result of History\n" + "\n".join(
        "## " + heading + "\npreserved history" for heading in [
            "Task Overview", "Completed Work", "Key Decisions", "Unresolved Issues",
            "Pending Items", "Next Steps", "Context To Preserve",
        ]
    )
    summarize = MagicMock(return_value=SimpleNamespace(content=summary, token_usage=None))
    final = manager.assemble_final_context(model=summarize, memory=memory, current_run_start_idx=0, run_context=run)
    assert final.evidence.history_compression_triggered is True
    assert final.evidence.new_summary_coverage is not None
    assert final.evidence.final_token_estimate <= budget.effective_input_limit_tokens
    assert not final.evidence.exceeds_effective_input_limit
    assert "preserved history" in str(final.messages)
    client = model()
    client._dispatch_chat_completion(context_budget_snapshot=budget, capacity_snapshot=projection,
                                     messages=final.messages)
    sent = client.client.chat.completions.create.call_args.kwargs
    assert ("max_tokens" in sent) is (default is not None)
    assert len(sent["messages"]) > 0
