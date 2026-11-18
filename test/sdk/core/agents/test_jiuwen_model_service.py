# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated mapping, completion, stream and lifecycle contracts for Jiuwen's model bridge."""

import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.core.agents.cores.jiuwen.messages import resource_view
from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
from nexent.core.agents.cores.jiuwen.protocol import JiuwenProtocolError
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.contracts import (
    AssistantMessage,
    ModelEvent,
    TokenUsage,
    ToolCall,
)
from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import (
    construct_resolved_model_profile,
)
from nexent.core.model_service.profiles.resolved_profile import (
    ConnectionRules,
    ContextConfiguration,
    OutletConnection,
)
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references
from nexent.core.model_service.service import ModelServiceError
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def saved_profile():
    registry = dict(model_service_references())
    catalog = load_profile_catalog()
    policy = compose_provider_model_policy(
        catalog, provider_key="alibaba-cn", request_model_id="qwen3.5-plus", model_profile_key=None,
        base_bindings={key: registry[key][0].model_dump() for key in
                       ("protocol", "auth", "adapter", "code_converter", "native_converter")},
        base_instruction=VersionedReference(ref="system_only_v1", version=1), registered_references=registry,
        submitted_values={"enable_thinking": False},
    )
    profile = construct_resolved_model_profile(
        policy, catalog, tenant_id="tenant", display_name="fixture", model_type="llm", provider_id="alibaba",
        connection=OutletConnection(base_url="http://fixture/v1", ssl_verify=True, timeout_seconds=5,
                                    concurrency_limit=None, credential_ref={"kind": "model_record", "model_id": None}),
        connection_rules=ConnectionRules(credential_kind="model_record", relative_path="/chat/completions",
                                         method="POST", headers={}),
        context_configuration=ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                    capacity_source="profile", capability_profile_version=None),
        registered_references=registry,
    )
    data = profile.model_dump()
    data["outlet_id"] = 7
    data["connection"]["credential_ref"]["model_id"] = 7
    return type(profile).model_validate(data)


MESSAGES = [{"role": "system", "content": "Instructions"}, {"role": "user", "content": "Latest request"}]
TOOLS = [{"name": "add", "description": "Add", "parameters": {"type": "object", "properties": {
    "a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}]


def message(content="Answer", **kwargs):
    return AssistantMessage(content_parts=[{"type": "text", "text": content}], finish_reason="stop", **kwargs)


def stream_service(build_events):
    closed = Mock()

    @asynccontextmanager
    async def astream(request, profile, **kwargs):
        async def events():
            for event in build_events(request):
                yield event
        try:
            yield events()
        finally:
            closed()

    return SimpleNamespace(astream=astream), closed


def event(request, kind, seq=1, **kwargs):
    return ModelEvent(request_id=request.request_id, message_id=kwargs.pop("message_id", uuid.uuid4()),
                      sequence=seq, type=kind, **kwargs)


def completion(request, result, seq=2):
    return event(request, "message_completed", seq, message_id=result.message_id,
                 message=result, finish_reason=result.finish_reason)


async def test_invoke_uses_detached_snapshot_and_authorized_history(saved_profile):
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=message()))
    prefix = [{"role": "user", "content": "Earlier"}, {"role": "assistant", "content": "Previous answer"}]
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope(), prefix=prefix)
    original = deepcopy(MESSAGES)
    saved_profile.parameter_values["temperature"] = 0.123
    prefix[0]["content"] = "mutated"
    response = await model.invoke(MESSAGES, tools=TOOLS)
    request, snapshot = service.ainvoke.await_args.args
    assert [part["text"] for item in request.messages for part in item.content_parts] == [
        "Instructions", "Earlier", "Previous answer", "Latest request",
    ]
    assert snapshot.parameter_values.get("temperature") != 0.123
    assert MESSAGES == original
    assert response.content == "Answer" and response.usage_metadata is None
    assert model.last_usage.origin == "unknown"


@pytest.mark.parametrize("kwargs", [{"temperature": 0.1}, {"max_tokens": 1}, {"model": "other"}])
async def test_runtime_generation_or_model_override_rejected(saved_profile, kwargs):
    service = SimpleNamespace(ainvoke=AsyncMock())
    with pytest.raises(JiuwenProtocolError):
        await JiuwenServiceModel(service, saved_profile, RunCancellationScope()).invoke(MESSAGES, **kwargs)
    service.ainvoke.assert_not_awaited()


@pytest.mark.parametrize("result,category", [
    (AssistantMessage(finish_reason="mystery"), "MODEL_FINISH_REASON_UNSUPPORTED"),
    (AssistantMessage(finish_reason="length"), "MODEL_RESPONSE_INCOMPLETE"),
    (AssistantMessage(finish_reason="stop"), "MODEL_EMPTY_RESPONSE"),
    (message(refusal="refused"), "MODEL_RESPONSE_REFUSED"),
    (AssistantMessage(finish_reason="tool_calls"), "JIUWEN_TOOL_FINISH_MISMATCH"),
])
async def test_noncomplete_response_is_not_success(saved_profile, result, category):
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=result))
    with pytest.raises(ModelServiceError) as failure:
        await JiuwenServiceModel(service, saved_profile, RunCancellationScope()).invoke(MESSAGES)
    assert failure.value.error.category == category


@pytest.mark.parametrize("name,args,error", [
    ("unknown", {}, "JIUWEN_UNAUTHORIZED_TOOL"), ("add", {"a": "x", "b": 3}, "INVALID_TOOL_ARGUMENTS"),
    ("add", {"a": 2}, "INVALID_TOOL_ARGUMENTS"),
])
async def test_complete_calls_validated_before_exposure(saved_profile, name, args, error):
    import json
    result = AssistantMessage(finish_reason="tool_calls", tool_calls=[ToolCall(
        provider_call_id="provider-1", index=0, name=name, raw_arguments=json.dumps(args), parsed_arguments=args,
    )])
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=result))
    with pytest.raises(ModelServiceError) as failure:
        await JiuwenServiceModel(service, saved_profile, RunCancellationScope()).invoke(MESSAGES, tools=TOOLS)
    assert failure.value.error.category == error


async def test_streams_visible_deltas_once_and_closes(saved_profile):
    result = message("Answer", usage=TokenUsage(input_tokens=2, output_tokens=1, total_tokens=3, origin="provider"))
    service, closed = stream_service(lambda request: [event(request, "text_delta", delta="Answer"),
                                                      completion(request, result)])
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope())
    chunks = [chunk async for chunk in model.stream(MESSAGES)]
    assert "".join(chunk.content for chunk in chunks) == "Answer"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage_metadata.total_tokens == 3
    closed.assert_called_once()


@pytest.mark.parametrize("variant", ["missing", "duplicate", "mismatch"])
async def test_stream_completion_contract(saved_profile, variant):
    result = message()
    def events(request):
        output = [event(request, "text_delta", delta="partial" if variant == "mismatch" else "Answer")]
        if variant != "missing":
            output.append(completion(request, result))
        if variant == "duplicate":
            output.append(completion(request, result, 3))
        return output
    service, closed = stream_service(events)
    with pytest.raises(ModelServiceError):
        model = JiuwenServiceModel(service, saved_profile, RunCancellationScope())
        _ = [chunk async for chunk in model.stream(MESSAGES)]
    closed.assert_called_once()


async def test_consumer_close_releases_stream(saved_profile):
    service, closed = stream_service(lambda request: [event(request, "text_delta", delta="Answer"),
                                                      completion(request, message())])
    stream = JiuwenServiceModel(service, saved_profile, RunCancellationScope()).stream(MESSAGES)
    assert (await anext(stream)).content == "Answer"
    await stream.aclose()
    closed.assert_called_once()


async def test_pre_cancelled_call_never_sends(saved_profile):
    scope = RunCancellationScope()
    scope.cancel()
    service = SimpleNamespace(ainvoke=AsyncMock())
    with pytest.raises(RunTerminated):
        await JiuwenServiceModel(service, saved_profile, scope).invoke(MESSAGES)
    service.ainvoke.assert_not_awaited()


def test_tool_history_and_input_are_detached():
    messages = [*MESSAGES, {"role": "assistant", "content": "", "tool_calls": [{
        "id": "provider-1", "function": {"name": "add", "arguments": '{"a":2,"b":3}'}}]},
        {"role": "tool", "content": "5", "tool_call_id": "provider-1"}]
    original = deepcopy(messages)
    view = resource_view(messages, TOOLS)
    assert view.history[-1].message.tool_call_id == "provider-1"
    assert view.history[-2].message.tool_calls[0].provider_call_id == "provider-1"
    assert messages == original


def test_mixed_text_media_input_keeps_parts_and_order():
    content = ["Question", {"type": "image_url", "image_url": {"url": "https://fixture.invalid/image.png"}}]
    view = resource_view([{"role": "user", "content": content}], [])
    assert view.current_user_input.message.content_parts == [
        {"type": "text", "text": "Question"}, content[1],
    ]
    content[1]["image_url"]["url"] = "changed"
    assert view.current_user_input.message.content_parts[1]["image_url"]["url"] != "changed"


async def test_text_mode_builds_internal_call_without_provider_tools(saved_profile):
    data = saved_profile.model_dump()
    data["capabilities"]["tools"]["status"] = "unknown"
    profile = type(saved_profile).model_validate(data)
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=message("<code>add(a=2,b=3)</code>")))
    model = JiuwenServiceModel(service, profile, RunCancellationScope())
    response = await model.invoke(MESSAGES, tools=TOOLS)
    assert response.tool_calls[0].name == "nexent_execute_block"
    request = service.ainvoke.await_args.args[0]
    assert request.tools == []
    assert "available_tools" in str(request.model_dump())
    assert "controlled text execution protocol" in str(request.model_dump())


async def test_tool_deltas_cannot_be_executed(saved_profile):
    from nexent.core.model_service.contracts import ToolCallDelta

    result = AssistantMessage(finish_reason="tool_calls", tool_calls=[ToolCall(
        provider_call_id="provider-1", index=0, name="add", raw_arguments='{"a":2,"b":3}',
        parsed_arguments={"a": 2, "b": 3},
    )])
    service, closed = stream_service(lambda request: [
        event(request, "tool_call_delta", tool_call_delta=ToolCallDelta(
            local_call_id=uuid.uuid4(), index=0, provider_call_id="provider-1", arguments_delta='{"a":',
        )), completion(request, result),
    ])
    chunks = [chunk async for chunk in JiuwenServiceModel(service, saved_profile, RunCancellationScope()).stream(
        MESSAGES, tools=TOOLS,
    )]
    assert len(chunks) == 1
    assert chunks[0].tool_calls[0].id == "provider-1"
    assert chunks[0].tool_calls[0].arguments == '{"a":2,"b":3}'
    closed.assert_called_once()


async def test_mid_stream_cancellation_closes(saved_profile):
    scope = RunCancellationScope()

    def events(request):
        yield event(request, "text_delta", delta="partial")
        scope.cancel()
        yield completion(request, message())

    service, closed = stream_service(events)
    public = []
    model = JiuwenServiceModel(service, saved_profile, scope, on_event=public.append)
    with pytest.raises(RunTerminated):
        _ = [chunk async for chunk in model.stream(MESSAGES)]
    assert any(e.type == "text_delta" and e.delta == "partial" for e in public)
    closed.assert_called_once()


@pytest.mark.parametrize("variant", ["missing", "tenant", "endpoint", "unsaved"])
def test_adapter_requires_trusted_matching_snapshot(saved_profile, variant):
    from threading import Event

    from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
    data = saved_profile.model_dump()
    if variant == "unsaved":
        data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = None
    model = ModelConfig(cite_name="fixture", model_name="qwen3.5-plus", url="http://fixture/v1",
                        resolved_profile=None if variant == "missing" else type(saved_profile).model_validate(data))
    if variant == "endpoint":
        model.url = "http://other/v1"
    info = AgentRunInfo(query="Request", observer=Mock(spec=MessageObserver), stop_event=Event(),
        tenant_id="other" if variant == "tenant" else "tenant", model_config_list=[model],
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[]))
    with pytest.raises(UnsupportedAgentCoreConfig):
        JiuwenAdapter(info).validate()


def test_request_output_budget_cannot_be_silently_ignored(saved_profile):
    from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

    cap = saved_profile.parameter_values.get("max_output_tokens", saved_profile.parameter_values.get("max_tokens"))
    info = SimpleNamespace(agent_config=SimpleNamespace(requested_output_tokens=None),
                           context_budget_snapshot=SimpleNamespace(requested_output_tokens=(cap or 0) + 1))
    adapter = JiuwenAdapter(info)
    adapter.model_config = SimpleNamespace(resolved_profile=saved_profile)
    with pytest.raises(UnsupportedAgentCoreConfig, match="output budget"):
        adapter._create_model()


def test_adapter_freezes_connection_headers_and_credential_scope(saved_profile, mocker):
    from threading import Event

    from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

    authentication = mocker.patch("nexent.core.model_service.registry.AuthenticationRegistry").return_value
    service = mocker.patch("nexent.core.model_service.service.ModelService")
    model = ModelConfig(cite_name="fixture", model_name="qwen3.5-plus", url="http://fixture/v1",
                        resolved_profile=saved_profile, api_key="original-credential",
                        http_headers={"X-Gateway-Route": "original-route"})
    info = AgentRunInfo(query="Request", observer=Mock(spec=MessageObserver), stop_event=Event(),
                        tenant_id="tenant", model_config_list=[model],
                        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[]))
    adapter = JiuwenAdapter(info)
    adapter.model_config = model
    adapter.scope = RunCancellationScope(info.stop_event)
    adapter._create_model()
    model.http_headers["X-Gateway-Route"] = "later-route"
    model.api_key = "later-credential"
    service.call_args.args[0](saved_profile)
    profile, lookup = authentication.sender_for.call_args.args
    assert profile is saved_profile
    assert authentication.sender_for.call_args.kwargs["http_headers"] == {"X-Gateway-Route": "original-route"}
    assert lookup("tenant", saved_profile.connection.credential_ref) == "original-credential"
    with pytest.raises(PermissionError, match="scope mismatch"):
        lookup("other-tenant", saved_profile.connection.credential_ref)
    assert "http_headers" not in model.model_dump()


def test_adapter_uses_resolved_a2a_callables_for_authorization_and_delegation(saved_profile):
    from threading import Event

    from nexent.core.agent_names import resolve_external_agent_configs
    from nexent.core.agents.contracts.config import AgentConfig, ExternalA2AAgentConfig, ModelConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

    external = [ExternalA2AAgentConfig(agent_id=str(index), name=name, url="https://unused.invalid")
                for index, name in enumerate(["file-helper", "file-helper"], 1)]
    model = ModelConfig(cite_name="fixture", model_name="qwen3.5-plus", url="http://fixture/v1",
                        resolved_profile=saved_profile)
    info = AgentRunInfo(query="Invoke a sub-agent to create a document", observer=Mock(spec=MessageObserver),
                        stop_event=Event(), tenant_id="tenant", model_config_list=[model],
                        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture",
                                                 tools=[], external_a2a_agents=external))
    adapter = JiuwenAdapter(info)
    adapter.validate()
    expected = {item.invocation_name for item in resolve_external_agent_configs(external)}
    assert {item.invocation_name for item in adapter.external_agents} == expected
    assert adapter.visible_tool_names == expected
    assert adapter.delegation.pending and adapter.delegation.names == expected
    assert all(item.invocation_name is None for item in info.agent_config.external_a2a_agents)


@pytest.mark.parametrize("invalid", [None, "tools", "refusal", "nontext"])
def test_context_summary_accepts_shared_chat_messages_and_validates_completion(saved_profile, invalid):
    from nexent.core.agents.cores.jiuwen.context import SummaryModel
    from smolagents.models import ChatMessage, MessageRole

    service = Mock()
    response = message("Summary")
    if invalid == "tools":
        response = message("Summary", tool_calls=[ToolCall(provider_call_id="call", index=0,
                           name="unexpected", raw_arguments="{}")])
    elif invalid == "refusal":
        response = message("Summary", refusal="Cannot summarize")
    elif invalid == "nontext":
        response = SimpleNamespace(finish_reason="stop", tool_calls=[], refusal=None,
                                   content_parts=[{"type": "image", "url": "fixture"}])
    service.invoke.return_value = response
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope())
    summary = SummaryModel(model)
    messages = [ChatMessage(role=MessageRole.SYSTEM, content=[{"type":"text", "text":"Summary policy"}]),
                ChatMessage(role=MessageRole.USER, content=[{"type":"text", "text":"Completed fact"}])]
    original = saved_profile.model_dump()
    if invalid:
        with pytest.raises(ValueError):
            summary(messages, max_tokens=1000)
    else:
        assert summary(messages, max_tokens=1000).content == "Summary"
    request, profile = service.invoke.call_args.args
    assert profile.parameter_values["max_output_tokens"] == 1000
    assert profile.parameter_values["enable_thinking"] is False
    assert not request.tools
    assert request.messages[-1].content_parts == [{"type": "text", "text": "Completed fact"}]
    assert saved_profile.model_dump() == original


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("kind", ["arguments", "empty", "reasoning", "length"])
async def test_logical_recovery_preserves_request_and_separates_counters(saved_profile, streaming, kind):
    values = {"content_parts": [{"type": "text", "text": "Partial" if kind == "length" else ""}],
              "finish_reason": "length" if kind == "length" else "stop"}
    if kind == "reasoning":
        values["reasoning_parts"] = [{"type": "text", "text": "Thinking"}]
    if kind == "arguments":
        values.update(finish_reason="tool_calls", tool_calls=[ToolCall(provider_call_id="bad", index=0,
            name="add", raw_arguments='{"a":1}', parsed_arguments={"a": 1})])
    bad = AssistantMessage(**values)
    requests, corrections, errors = [], [], []
    responses = [bad, message("Recovered")]
    async def invoke(request, *_args, **_kwargs):
        requests.append(request)
        return responses.pop(0)
    @asynccontextmanager
    async def stream(request, *_args, **_kwargs):
        async def events():
            yield completion(request, await invoke(request))
        yield events()
    model = JiuwenServiceModel(SimpleNamespace(ainvoke=invoke, astream=stream), saved_profile,
        RunCancellationScope(), on_recovery=corrections.append, on_error=errors.append)
    original = deepcopy(MESSAGES)
    if streaming:
        result = [chunk async for chunk in model.stream(MESSAGES, tools=TOOLS)]
        assert result[-1].content == "Recovered"
    else:
        assert (await model.invoke(MESSAGES, tools=TOOLS)).content == "Recovered"
    assert MESSAGES == original and len(requests) == 2
    assert requests[0].request_id != requests[1].request_id
    assert model.logical_requests == 2 and len(corrections) == len(errors) == 1
    assert model.argument_corrections == (kind == "arguments")
    assert model.response_corrections == (kind != "arguments")
    assert "Regenerate this model step" in requests[1].model_dump_json()


async def test_argument_step_and_turn_budget_are_independent(saved_profile):
    bad = AssistantMessage(finish_reason="tool_calls", tool_calls=[ToolCall(
        provider_call_id="bad", index=0, name="add", raw_arguments="{}", parsed_arguments={})])
    service = SimpleNamespace(ainvoke=AsyncMock(side_effect=[bad, message(), bad, message(), bad, message(), bad]))
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope())
    for _ in range(3):
        await model.invoke(MESSAGES, tools=TOOLS)
    with pytest.raises(ModelServiceError, match="INVALID_TOOL_ARGUMENTS"):
        await model.invoke(MESSAGES, tools=TOOLS)
    assert model.argument_corrections == 3 and service.ainvoke.await_count == 7
    service.ainvoke = AsyncMock(return_value=bad)
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope())
    with pytest.raises(ModelServiceError):
        await model.invoke(MESSAGES, tools=TOOLS)
    assert service.ainvoke.await_count == 2 and model.argument_corrections == 1


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
async def test_no_followup_after_correction_cancel_or_deadline(saved_profile, stop):
    import time
    scope = RunCancellationScope()
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=message("")))
    model = JiuwenServiceModel(service, saved_profile, scope)
    def terminate(_details):
        if stop == "cancel":
            scope.cancel()
        else:
            model.deadline = time.monotonic() - 1
    model.on_recovery = terminate
    with pytest.raises((RunTerminated, ModelServiceError)):
        await model.invoke(MESSAGES)
    assert service.ainvoke.await_count == 1


async def test_rejected_stream_partial_is_not_native_history(saved_profile):
    requests, public = [], []
    @asynccontextmanager
    async def stream(request, *_args, **_kwargs):
        requests.append(request)
        first = len(requests) == 1
        result = (AssistantMessage(content_parts=[{"type": "text", "text": "PARTIAL"}], finish_reason="length")
                  if first else message("Recovered"))
        async def events():
            yield event(request, "text_delta", delta="PARTIAL" if first else "Recovered")
            yield completion(request, result)
        yield events()
    model = JiuwenServiceModel(SimpleNamespace(astream=stream), saved_profile,
                              RunCancellationScope(), on_event=public.append)
    chunks = [chunk async for chunk in model.stream(MESSAGES)]
    assert "".join(c.content or "" for c in chunks) == "Recovered"
    assert [e.delta for e in public if e.type == "text_delta"] == ["PARTIAL", "Recovered"]



@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("bad", ["<code><code>print(1)</code></code>", "<code>a=</code>", "<code></code>"])
async def test_text_code_arguments_use_the_shared_correction_quota(saved_profile, streaming, bad):
    data = saved_profile.model_dump()
    data["capabilities"]["tools"]["status"] = "unsupported"
    profile = type(saved_profile).model_validate(data)
    responses = [message(bad), message("<code>add(a=2,b=3)</code>")]
    requests = []
    async def invoke(request, *_args, **_kwargs):
        requests.append(request)
        return responses.pop(0)
    @asynccontextmanager
    async def stream(request, *_args, **_kwargs):
        async def events():
            yield completion(request, await invoke(request))
        yield events()
    model = JiuwenServiceModel(SimpleNamespace(ainvoke=invoke, astream=stream), profile, RunCancellationScope())
    if streaming:
        result = [c async for c in model.stream(MESSAGES, tools=TOOLS)]
        assert result[-1].tool_calls[0].name == "nexent_execute_block"
    else:
        assert (await model.invoke(MESSAGES, tools=TOOLS)).tool_calls[0].name == "nexent_execute_block"
    assert len(requests) == 2 and model.argument_corrections == 1 and model.response_corrections == 0


async def test_persistent_bad_code_stops_after_one_correction(saved_profile):
    data = saved_profile.model_dump()
    data["capabilities"]["tools"]["status"] = "unsupported"
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=message("<code><code>x=1</code></code>")))
    model = JiuwenServiceModel(service, type(saved_profile).model_validate(data), RunCancellationScope())
    with pytest.raises(ModelServiceError, match="JIUWEN_NESTED_EXECUTION_BLOCK"):
        await model.invoke(MESSAGES)
    assert service.ainvoke.await_count == 2 and model.argument_corrections == 1


@pytest.mark.parametrize("name,args,allowed", [
    ("nexent_execute_python", {"code": "print(1)"}, True),
    ("nexent_execute_python", {"code": 1}, False),
    ("nexent_execute_python", {"code": "print(1)", "shell": True}, False),
    ("nexent_execute_block", {"code": "print(1)"}, False),
    ("unregistered", {"code": "print(1)"}, False),
])
async def test_native_file_call_requires_registered_tool_and_complete_schema(saved_profile, name, args, allowed):
    import json
    tools = [{"name": "nexent_execute_python", "parameters": {
        "type": "object", "properties": {"code": {"type": "string"}},
        "required": ["code"], "additionalProperties": False}}]
    result = AssistantMessage(content_parts=[], finish_reason="tool_calls", tool_calls=[ToolCall(
        provider_call_id="file-call", index=0, name=name, raw_arguments=json.dumps(args), parsed_arguments=args)])
    model = JiuwenServiceModel(SimpleNamespace(ainvoke=AsyncMock(return_value=result)),
                              saved_profile, RunCancellationScope())
    if allowed:
        response = await model.invoke(MESSAGES, tools=tools)
        assert response.tool_calls[0].name == name
    else:
        with pytest.raises(ModelServiceError):
            await model.invoke(MESSAGES, tools=tools)
