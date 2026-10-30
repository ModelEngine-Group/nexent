# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual loopback HTTP integration of ModelService, sender, SSE and adapter."""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import LanePolicy, ManagedTaskSpec
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.concurrency import ModelConcurrencyLimiter
from nexent.core.model_service.contracts import (
    ModelMessage,
    ModelRequest,
    ToolDefinition,
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
from nexent.core.model_service.registry import AuthenticationRegistry, model_service_references
from nexent.core.model_service.service import ModelService, ModelServiceError
from nexent.core.models.capacity_budget import (
    CapacityReservePolicy,
    ContextBudgetCalculator,
    ContextBudgetCapacityMismatch,
)
from nexent.core.models.capacity_resolver import resolve_capacity
from smolagents.models import CODEAGENT_RESPONSE_FORMAT

from .empty_response_cases import test_legacy_empty_policy  # noqa: F401 - Collected by pytest.
from .empty_response_cases import test_legacy_context_recovery_shares_real_http_budget, test_legacy_connectivity_uses_real_service_defaults  # noqa: F401 - Collected by pytest.
from .empty_response_cases import test_actual_agent_factory_uses_resolved_outlet, test_resolved_gateway_stream_uses_real_async_transport, test_resource_conversion_and_saved_snapshot_reach_real_peer  # noqa: F401 - Collected by pytest.
from .prompt_generation_cases import test_auxiliary_prompt_uses_saved_outlet_http_without_outer_retry, test_long_text_preparation_uses_saved_outlet_real_http  # noqa: F401

from .prompt_generation_cases import test_saved_parameter_transform_reaches_actual_http_body  # noqa: F401

from .prompt_generation_cases import test_migrated_legacy_configuration_reaches_shared_http_without_extra_defaults  # noqa: F401

pytestmark = [pytest.mark.case_id("MST-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture
def peer(tmp_path):
    ready, journal = tmp_path / "ready", tmp_path / "requests.jsonl"
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("http_peer.py")),
            str(ready),
            str(journal),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None, "Loopback peer exited before becoming ready"
            assert time.monotonic() < deadline, "Loopback peer startup timed out"
            time.sleep(0.01)
        yield f"http://127.0.0.1:{int(ready.read_text())}", journal
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        assert process.poll() is not None


def records(journal, *, kind="request", scenario=None):
    lines = journal.read_text().splitlines() if journal.exists() else []
    values = [json.loads(line) for line in lines]
    return [
        value
        for value in values
        if value["kind"] == kind and (scenario is None or value["scenario"] == scenario)
    ]


def setup(peer, scenario, *, outlet_reader=None, http_headers=None, retry_policy=None):
    root, journal = peer
    catalog = load_profile_catalog()
    refs = dict(model_service_references())
    auth = AuthenticationRegistry()
    policy = compose_provider_model_policy(
        catalog,
        provider_key="alibaba-cn",
        request_model_id="qwen3.5-plus",
        model_profile_key=None,
        base_bindings={
            key: value[0].model_dump()
            for key, value in refs.items()
            if key != "parameter_transform"
        },
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=refs,
        submitted_values={"enable_thinking": False},
    )
    profile = construct_resolved_model_profile(
        policy,
        catalog,
        tenant_id="loopback-tenant",
        display_name="controlled peer",
        model_type="llm",
        provider_id="alibaba",
        connection=OutletConnection(
            base_url=f"{root}/v1?scenario={scenario}",
            ssl_verify=True,
            timeout_seconds=5,
            concurrency_limit=1,
            credential_ref={"kind": "model_record", "model_id": None},
        ),
        connection_rules=ConnectionRules(
            credential_kind="model_record",
            relative_path="chat/completions",
            method="POST",
            headers={},
        ),
        context_configuration=ContextConfiguration(
            output_reserve_tokens=None,
            tokenizer_family=None,
            capacity_source="profile",
            capability_profile_version=None,
        ),
        registered_references=refs,
    )
    limiter = ModelConcurrencyLimiter()
    credential_reads = []

    def credentials(tenant_id, reference):
        assert tenant_id == "loopback-tenant"
        credential_reads.append(reference)
        return "dummy-loopback"

    service = ModelService(lambda snapshot: auth.sender_for(snapshot, credentials, http_headers=http_headers), limiter=limiter, outlet_reader=outlet_reader, retry_policy=retry_policy)
    request = ModelRequest(
        request_id=f"request-{scenario}",
        outlet_id=None,
        config_revision=1,
        messages=[
            ModelMessage(
                semantic_role="system",
                content_parts=[{"type": "text", "text": "instructions"}],
            ),
            ModelMessage(
                semantic_role="user",
                content_parts=[{"type": "text", "text": "question"}],
            ),
        ],
    )
    return service, request, profile, limiter, journal, credential_reads


@pytest.mark.parametrize("deferred,suppressed,accepted", [
    (False, False, True), (True, False, True), (True, False, False),
    (False, True, True), (True, True, True),
])
def test_legacy_model_interface_uses_real_transport_and_retains_usage(peer, deferred, suppressed, accepted):
    service, _request, profile, limiter, journal, credential_reads = setup(peer, "stream")
    snapshot = profile.model_dump()
    for key, schema in (("response_format", {"type": "object"}),):
        snapshot["parameter_rules"].append({
            "key": key, "schema": schema, "visible": False, "editable": True,
            "required": False, "allowed_scopes": ["outlet"], "ui_group": "legacy", "owner": "provider",
            "source": {"ref": "loopback_fixture_v1", "version": 1},
            "api_binding": {"path": "/" + key, "transform_ref": "identity_v1", "transform_version": 1},
        })
    profile = profile.__class__.model_validate(snapshot)
    model = LegacyChatModel(profile, service)
    capacity = resolve_capacity(model_id=model.model_id, provider=model.model_factory,
                                operator_overrides={"context_window_tokens": 200000}, capability_profiles={})
    model.capacity_snapshot = {"capacity_fingerprint": capacity.fingerprint,
                               "provider": capacity.provider, "model_name": capacity.model_name}
    model.context_budget_snapshot = ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy())
    result = model([
        {"role": "system", "content": "Code instructions"},
        {"role": "tool-response", "content": "observation"},
    ], stop_sequences=["Observation:", "Calling tools:"], response_format=CODEAGENT_RESPONSE_FORMAT,
       _defer_attempt_commit=deferred, _suppress_attempt_stream=suppressed)
    assert result.content == "中间正文"
    assert result.raw.reasoning_parts == [{"type": "text", "text": "consider"}]
    assert result.tool_calls[0].id == "call-peer"
    assert result.tool_calls[0].function.arguments == '{"n":0}'
    assert result.token_usage.input_tokens == 10 and result.token_usage.output_tokens == 5
    assert model.last_finish_reason == "tool_calls" and result.model_attempt_number == 1
    def phases():
        return [json.loads(item)["phase"] for item in model.observer.message_query
                if json.loads(item)["type"] == "model_attempt_control"]
    assert phases() == ([] if suppressed else ["begin"] if deferred else ["begin", "commit"])
    if suppressed:
        assert model.observer.message_query == []
    elif deferred:
        core = CoreAgent.__new__(CoreAgent)
        core.observer, core.step_number = model.observer, 1
        core._resolve_deferred_model_attempt(result, accepted=accepted)
        core._resolve_deferred_model_attempt(result, accepted=accepted)
        assert phases() == ["begin", "commit" if accepted else "rollback"]
        assert result.model_attempt_commit_deferred is False
    captured = records(journal)
    assert len(captured) == 1 and len(credential_reads) == 1
    assert captured[0]["body"]["messages"] == [
        {"role": "system", "content": "Code instructions"},
        {"role": "user", "content": "observation"},
    ]
    assert captured[0]["body"]["stop"] == ["Observation:", "Calling tools:"]
    assert captured[0]["body"]["response_format"] == CODEAGENT_RESPONSE_FORMAT
    assert captured[0]["body"]["max_tokens"] == model.context_budget_snapshot.requested_output_tokens
    assert "stop" not in model.profile.parameter_values
    model.capacity_snapshot["capacity_fingerprint"] = "stale"
    with pytest.raises(ContextBudgetCapacityMismatch):
        model([{"role": "user", "content": "must not send"}])
    assert len(records(journal)) == 1 and len(credential_reads) == 1
    assert not limiter._entries


async def consume(service, request, profile, asynchronous, **kwargs):
    if asynchronous:
        async with service.astream(request, profile, **kwargs) as events:
            return [event async for event in events]
    with service.stream(request, profile, **kwargs) as events:
        return list(events)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_exact_request_reaches_real_peer(peer, asynchronous):
    service, request, profile, limiter, journal, credential_reads = setup(
        peer, "normal", http_headers={"X-Gateway": "dummy-gateway"}
    )
    profile = profile.model_copy(deep=True, update={"extra_api_parameters": [{"path": "/vendor/thinking", "value": False}]})
    result = (
        await service.ainvoke(request, profile)
        if asynchronous
        else service.invoke(request, profile)
    )
    assert result.content_parts == [{"type": "text", "text": "answer"}]
    assert result.reasoning_parts == [{"type": "text", "text": "consider"}]
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 5
    captured = records(journal)
    assert captured[0]["gateway"] == "dummy-gateway"
    assert captured[0]["body"]["vendor"] == {"thinking": False}
    assert "X-Gateway" not in captured[0]["body"]
    assert "dummy-gateway" not in repr(profile.model_dump())
    assert (
        len(captured) == 1
        and captured[0]["path"] == "/v1/chat/completions?scenario=normal"
    )
    assert captured[0]["authorization"] == "Bearer dummy-loopback"
    assert captured[0]["body"] == {
        "model": "qwen3.5-plus",
        "messages": [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "question"},
        ],
        "stream": False,
        "enable_thinking": False,
        "vendor": {"thinking": False},
    }
    assert len(credential_reads) == 1 and not limiter._entries


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_fragmented_stream_retains_kinds_calls_and_usage(peer, asynchronous):
    service, request, profile, limiter, journal, credential_reads = setup(
        peer, "stream"
    )
    tool = ToolDefinition(
        name="test_tool",
        description="Controlled declaration",
        input_schema={
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    )
    request = request.model_copy(update={"stream": True, "tools": [tool]})
    events = await consume(service, request, profile, asynchronous)
    assert [event.type for event in events] == [
        "reasoning_delta",
        "text_delta",
        "tool_call_delta",
        "tool_call_delta",
        "usage",
        "message_completed",
    ]
    assert [event.sequence for event in events] == list(range(1, 7))
    assert len({event.message_id for event in events}) == 1
    final = events[-1].message
    assert final.content_parts == [{"type": "text", "text": "中间正文"}]
    assert final.reasoning_parts == [{"type": "text", "text": "consider"}]
    assert final.finish_reason == "tool_calls" and final.usage.total_tokens == 15
    assert final.tool_calls[0].provider_call_id == "call-peer" and final.tool_calls[
        0
    ].parsed_arguments == {"n": 0}
    assert events[2].tool_call_delta.arguments_delta == '{"n":'
    assert events[3].tool_call_delta.arguments_delta == "0}"
    assert (
        events[2].tool_call_delta.local_call_id
        == events[3].tool_call_delta.local_call_id
        == final.tool_calls[0].local_call_id
    )
    captured = records(journal)
    assert len(captured) == 1 and captured[0]["body"]["stream_options"] == {
        "include_usage": True
    }
    assert captured[0]["body"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
    ]
    assert len(credential_reads) == 1 and not limiter._entries


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_retry_error_and_partial_output_boundaries(peer, asynchronous):
    for scenario, expected_count in [
        ("retry", 2),
        ("disconnect", 2),
        ("exhaust", 3),
        ("auth", 1),
    ]:
        service, request, profile, limiter, journal, credential_reads = setup(
            peer, scenario
        )
        if scenario in {"exhaust", "auth"}:
            with pytest.raises(ModelServiceError) as caught:
                if asynchronous:
                    await service.ainvoke(request, profile)
                else:
                    service.invoke(request, profile)
            assert caught.value.error.category == (
                "MODEL_SERVICE_UNAVAILABLE"
                if scenario == "exhaust"
                else "MODEL_AUTHENTICATION_ERROR"
            )
            assert (
                caught.value.error.attempt == expected_count
                and not caught.value.error.will_retry
            )
            assert "dummy-loopback" not in caught.value.error.model_dump_json()
            assert "provider rejected" in caught.value.error.safe_message
        else:
            result = (
                await service.ainvoke(request, profile)
                if asynchronous
                else service.invoke(request, profile)
            )
            assert result.content_parts == [{"type": "text", "text": "answer"}]
        captured = records(journal, scenario=scenario)
        assert len(captured) == expected_count and len(credential_reads) == 1
        assert all(item["body"] == captured[0]["body"] for item in captured)
        assert not limiter._entries
    for scenario, category in [
        ("malformed", "MODEL_PROTOCOL_ERROR"),
        ("truncate", "MODEL_PROTOCOL_ERROR"),
        ("visible_disconnect", "MODEL_NETWORK_ERROR"),
    ]:
        service, request, profile, limiter, journal, _ = setup(peer, scenario)
        request = request.model_copy(update={"stream": True})
        events = await consume(service, request, profile, asynchronous)
        assert events[-1].type == "error" and events[-1].error.category == category
        assert not events[-1].error.will_retry and not any(
            event.type == "message_completed" for event in events
        )
        if scenario != "malformed":
            assert events[0].type == "text_delta" and events[0].delta == "partial"
        assert len(records(journal, scenario=scenario)) == 1 and not limiter._entries
    service, request, profile, limiter, journal, _ = setup(peer, "early_exit")
    request = request.model_copy(update={"stream": True})
    scope = RunCancellationScope()
    if asynchronous:
        async with service.astream(request, profile, scope=scope) as events:
            assert (await anext(events)).type == "reasoning_delta"
            scope.cancel()
            with pytest.raises(RunTerminated):
                await anext(events)
        with pytest.raises(StopAsyncIteration):
            await anext(events)
    else:
        with service.stream(request, profile, scope=scope) as events:
            assert next(events).type == "reasoning_delta"
            scope.cancel()
            with pytest.raises(RunTerminated):
                next(events)
        with pytest.raises(StopIteration):
            next(events)
    assert len(records(journal, scenario="early_exit")) == 1 and not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["stall", "header_stall"])
async def test_cancellation_closes_blocked_real_response(peer, scenario):
    service, request, profile, limiter, journal, _ = setup(peer, scenario)
    request = request.model_copy(update={"stream": True})
    scope = RunCancellationScope()
    task = asyncio.create_task(consume(service, request, profile, True, scope=scope))
    try:
        async with asyncio.timeout(2):
            while not records(journal, kind="waiting", scenario=scenario):
                await asyncio.sleep(0.01)
        scope.cancel()
        with pytest.raises(RunTerminated):
            await asyncio.wait_for(task, timeout=2)
        async with asyncio.timeout(2):
            while not records(journal, kind="finished", scenario=scenario):
                await asyncio.sleep(0.01)
        assert (
            records(journal, kind="finished", scenario=scenario)[0]["disconnected"]
            is True
        )
        assert not records(journal, kind="peer_timeout")
        assert len(records(journal, scenario=scenario)) == 1 and not limiter._entries
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RunTerminated):
                pass


@pytest.mark.parametrize("scenario", ["stall", "header_stall"])
def test_sync_cancellation_reclaims_blocked_managed_worker(peer, scenario):
    service, request, profile, limiter, journal, _ = setup(peer, scenario)
    request = request.model_copy(update={"stream": True})
    scope = RunCancellationScope()
    manager = ThreadManager(
        service_name="loopback-test",
        lane_policies={
            "agent-run": LanePolicy(
                name="agent-run",
                max_workers=1,
                max_queue_size=0,
                cancel_grace_seconds=2,
                shutdown_grace_seconds=4,
            ),
        },
    )
    manager.start()

    def consume_blocked():
        with service.stream(request, profile, scope=scope) as events:
            return list(events)

    execution = manager.submit(
        "agent-run",
        ManagedTaskSpec(
            task_name="blocked-model-stream",
            owner="MST-D3-001",
            close_hook=scope.cancel,
        ),
        consume_blocked,
    )
    try:
        deadline = time.monotonic() + 2
        while not records(journal, kind="waiting", scenario=scenario):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        time.sleep(0.05)
        scope.cancel()
        with pytest.raises(RunTerminated):
            execution.future.result(timeout=2)
        assert manager.snapshot().active_count == 0
        assert not limiter._entries and len(records(journal, scenario=scenario)) == 1
        deadline = time.monotonic() + 1
        while not records(journal, kind="finished", scenario=scenario):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert (
            records(journal, kind="finished", scenario=scenario)[0]["disconnected"]
            is True
        )
        assert not records(journal, kind="peer_timeout")
    finally:
        scope.cancel()
        result = asyncio.run(manager.shutdown(timeout=4))
        assert not result.stuck_execution_ids


from .stream_compatibility_cases import (
    test_agent_bridge_uses_vllm_tail_and_shared_localized_errors,
    test_compatible_stream_tails_complete_once_through_actual_http,
    test_http_detail_reaches_agent_bridge_without_credentials_or_extra_retry,
)  # noqa: F401 - Collected through this Case primary script.
