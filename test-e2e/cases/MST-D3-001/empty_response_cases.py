# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy empty-response policy over the same real HTTP peer and sender."""

import json
from threading import Event
from types import SimpleNamespace

import pytest
from nexent.core.agent_runtime_support.contracts import (
    ResourceItem,
    RuntimeResourceView,
)
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.context_runtime.contracts import ContextEvidence, FinalContext
from nexent.core.gateway.modality.llm.llm_adapter import LLMRequest
from nexent.core.gateway.modality.llm.openai import OpenAILLMAdapter
from nexent.core.gateway.model_context import LLMContext
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import ModelMessage, ToolDefinition
from nexent.core.model_service.profiles.outlet_storage import (
    decode_resolved_model_profile,
    encode_resolved_model_profile,
)
from nexent.core.model_service.registry import model_service_references
from nexent.core.model_service.resource_conversion import ResourceConverterRegistry
from nexent.core.utils.observer import MessageObserver


@pytest.mark.parametrize('scenario,retry,calls,succeeds', [
    ('legacy_empty_fail', False, 1, False),
    ('legacy_empty_budget', True, 3, True),
    ('legacy_reasoning_empty', True, 1, False),
])
def test_legacy_empty_policy(peer, request, scenario, retry, calls, succeeds):
    module = request.module
    service, _request, profile, limiter, journal, credentials = module.setup(peer, scenario)
    observer = MessageObserver()
    model = LegacyChatModel(profile, service, observer=observer)
    messages = [{'role': 'user', 'content': 'hello'}]
    if succeeds:
        response = model.generate(messages, _retry_empty_response=retry)
        assert response.content == '中间正文'
        assert response.model_attempt_number == 3
        assert response.tool_calls[0].id == 'call-peer'
    else:
        with pytest.raises(ModelInvocationTerminalError) as caught:
            model.generate(messages, _retry_empty_response=retry)
        assert caught.value.error_code == ModelErrorCode.EMPTY_RESPONSE_EXHAUSTED
    actual = module.records(journal, scenario=scenario)
    assert len(actual) == calls and len(credentials) == 1
    assert not limiter._entries
    assert all('_retry_empty_response' not in value['body'] for value in actual)
    assert all(value['body'] == actual[0]['body'] for value in actual)

    events = [json.loads(item) for item in observer.message_query]
    phases = [event['phase'] for event in events if 'phase' in event]
    assert phases == (['begin', 'rollback', 'begin', 'commit'] if succeeds else ['begin', 'rollback'])

    diagnostics = model.last_response_diagnostics
    assert diagnostics['finish_reason'] == ('tool_calls' if succeeds else 'stop')
    assert diagnostics['input_tokens'] == 10
    assert diagnostics['output_tokens'] == (5 if succeeds else 0)
    assert diagnostics['content_char_count'] == (len('中间正文') if succeeds else 0)
    assert diagnostics['reasoning_char_count'] == (len('consider') if succeeds else len('thought') if scenario == 'legacy_reasoning_empty' else 0)
    assert model.last_prompt_cache_usage is None


def test_legacy_context_recovery_shares_real_http_budget(peer, request):
    module = request.module
    scenario = 'legacy_context_budget'
    service, _, profile, limiter, journal, credentials = module.setup(peer, scenario)
    model = LegacyChatModel(profile, service)
    evidence = ContextEvidence(compression_attempted=True)
    rebuilt = [{'role': 'user', 'content': 'short context'}]
    callbacks = []

    def rebuild():
        assert not limiter._entries
        assert len(module.records(journal, scenario=scenario)) == 2
        callbacks.append(True)
        return FinalContext(messages=rebuilt, evidence=evidence)

    response = model.generate([{'role': 'user', 'content': 'long context'}], context_rebuild=rebuild)
    actual = module.records(journal, scenario=scenario)
    assert response.content == '中间正文' and response.model_attempt_number == 3
    assert len(actual) == 3 and len(credentials) == len(callbacks) == 1
    assert actual[0]['body'] == actual[1]['body']
    assert actual[2]['body']['messages'] == rebuilt
    assert {key: value for key, value in actual[2]['body'].items() if key != 'messages'} == {
        key: value for key, value in actual[0]['body'].items() if key != 'messages'
    }
    assert all('context_rebuild' not in item['body'] for item in actual)
    assert model.last_context_evidence is evidence and not limiter._entries
    phases = [json.loads(item)['phase'] for item in model.observer.message_query if '"phase"' in item]
    assert phases == ['begin', 'commit']


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,available', [('probe', True), ('auth', False)])
async def test_legacy_connectivity_uses_real_service_defaults(peer, request, scenario, available):
    module = request.module
    service, _, profile, limiter, journal, credentials = module.setup(peer, scenario)
    model = LegacyChatModel(profile, service)
    assert await model.check_connectivity() is available
    actual = module.records(journal, scenario=scenario)
    assert len(actual) == len(credentials) == 1 and not limiter._entries
    body = actual[0]['body']
    assert body['messages'] == [{'role': 'user', 'content': 'Hello'}]
    assert body['model'] == profile.identity.request_model_id and body['stream'] is False
    assert body['enable_thinking'] is False
    assert 'max_tokens' not in body and 'tools' not in body


def test_actual_agent_factory_uses_resolved_outlet(peer, request):
    module = request.module
    scenario = 'agent_factory'
    _, _, profile, _, journal, _ = module.setup(peer, scenario)
    agent = NexentAgent.__new__(NexentAgent)
    agent.tenant_id = profile.identity.tenant_id
    agent.stop_event = Event()
    agent.cancellation_scope = RunCancellationScope(agent.stop_event)
    agent.observer = MessageObserver()
    agent.model_config_list = [ModelConfig(
        cite_name='chosen', model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, api_key='dummy-loopback', resolved_profile=profile,
        http_headers={'x-gateway': 'dummy-agent-gateway'},
        temperature=0.9,
    )]
    model = agent.create_model('chosen')
    response = model.generate([{'role': 'user', 'content': 'hello'}], stop_sequences=['Observation:', 'Calling tools:'])
    assert isinstance(model, LegacyChatModel) and model.cancellation_scope is agent.cancellation_scope
    assert response.content == '中间正文' and response.token_usage.input_tokens == 10
    assert response.tool_calls[0].id == 'call-peer'
    actual = module.records(journal, scenario=scenario)
    assert len(actual) == 1 and actual[0]['authorization'] == 'Bearer dummy-loopback'
    assert actual[0]['gateway'] == 'dummy-agent-gateway'
    assert actual[0]['body']['enable_thinking'] is False
    assert actual[0]['body'].get('temperature') == profile.parameter_values.get('temperature')
    assert actual[0]['body']['stop'] == ['Observation:', 'Calling tools:']
    assert 'stop' not in profile.parameter_values


@pytest.mark.asyncio
async def test_resolved_gateway_stream_uses_real_async_transport(peer, request):
    module = request.module
    _, _, profile, _, journal, _ = module.setup(peer, "stream")
    scope = RunCancellationScope()
    adapter = OpenAILLMAdapter(LLMContext(
        model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="dummy-loopback", http_headers={"x-gateway": "dummy-gateway-stream"}, modality="llm", factory="openai",
        tenant_id=profile.identity.tenant_id, resolved_profile=profile, cancellation_scope=scope,
    ))
    stream = await adapter.stream(LLMRequest(messages=[{"role": "user", "content": "hello"}]))
    chunks = [chunk async for chunk in stream]
    assert "".join(chunk.content or "" for chunk in chunks) == "中间正文"
    calls = [call for chunk in chunks for call in chunk.tool_calls or []]
    assert "".join(call.function.arguments for call in calls) == '{"n":0}'
    usages = [chunk.token_usage for chunk in chunks if chunk.token_usage is not None]
    assert len(usages) == 1 and usages[0].input_tokens == 10 and usages[0].output_tokens == 5
    actual = module.records(journal, scenario="stream")
    assert len(actual) == 1 and actual[0]["authorization"] == "Bearer dummy-loopback"
    assert actual[0]["gateway"] == "dummy-gateway-stream"
    assert actual[0]["body"]["stream_options"] == {"include_usage": True}
    assert actual[0]["body"]["enable_thinking"] is False
    assert adapter._model.cancellation_scope is scope


@pytest.mark.parametrize("native,status", [(False, "supported"), (True, "supported"), (True, "unknown")])
def test_resource_conversion_and_saved_snapshot_reach_real_peer(peer, request, native, status):
    module = request.module
    scenario = "resource_conversion"
    selected = {}
    selections = []

    def read_outlet(model_id, context):
        selections.append((model_id, context.tenant_id))
        return selected[model_id]

    service, _, profile, limiter, journal, credentials = module.setup(peer, scenario, outlet_reader=read_outlet)
    values = profile.model_dump()
    values["outlet_id"] = 42
    values["connection"]["credential_ref"]["model_id"] = 42
    values["capabilities"]["tools"]["status"] = status
    profile = profile.__class__.model_validate(values)
    registry = model_service_references()
    row = encode_resolved_model_profile(profile, registered_references=registry)
    selected[42] = decode_resolved_model_profile(row, registered_references=registry)
    frozen = service.bind_outlet(42, SimpleNamespace(tenant_id="loopback-tenant"))
    assert selections == [(42, "loopback-tenant")]
    assert frozen is not selected[42] and not credentials and not limiter._entries
    assert not module.records(journal, scenario=scenario)
    resources = RuntimeResourceView(
        instructions=[ResourceItem(source="platform_instruction", order=1,
            message=ModelMessage(semantic_role="platform_instruction", content_parts=[{"type": "text", "text": "instructions"}]))],
        references=[ResourceItem(source="knowledge", order=2,
            message=ModelMessage(semantic_role="reference_data", content_parts=[{"type": "text", "text": "selected knowledge"}]))],
        current_user_input=ResourceItem(source="current_input", order=3,
            message=ModelMessage(semantic_role="user_input", content_parts=[{"type": "text", "text": "hello"}])),
        tool_definitions=[ToolDefinition(name="lookup", description="Find data", input_schema={"type": "object"})],
    )
    reference = frozen.bindings.native_converter if native else frozen.bindings.code_converter
    converted = ResourceConverterRegistry().resolve(reference).convert(resources, frozen)
    result = service.invoke(converted.request, frozen)
    assert result.content_parts == [{"type": "text", "text": "answer"}]
    assert result.usage.input_tokens == 10
    actual = module.records(journal, scenario=scenario)
    assert len(actual) == len(credentials) == 1 and not limiter._entries
    body = actual[0]["body"]
    assert body["messages"][0] == {"role": "system", "content": "instructions"}
    assert body["messages"][1] == {"role": "user", "content": "selected knowledge"}
    assert body["messages"][-1] == {"role": "user", "content": "hello"}
    assert bool(body.get("tools")) == (native and status == "supported")
    assert converted.tool_protocol == ("native" if native and status == "supported" else "text_block")
    assert frozen == profile and row["native_tool_call_supported"] == (None if status == "unknown" else True)
