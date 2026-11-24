# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import TypeAdapter, ValidationError

from contracts.agentos import (
    ChatInvocation,
    ChatMessage,
    ChatOptions,
    EmbeddingInvocation,
    ModelInvocation,
    RerankInput,
    RerankInvocation,
    RerankOptions,
)
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.models.wire_budget import model_wire_budget
from runtime.model.service import ModelAccessError, ModelService

_ACTOR = ServicePrincipal("user", "tenant")


def _record(**overrides):
    return {
        "tenant_id": _ACTOR.tenant_id,
        "delete_flag": "N",
        "model_type": "llm",
        "update_time": "2026-11-09",
        "api_key": "secret",
        **overrides,
    }


@pytest.mark.parametrize("override", ["base_url", "api_key", "provider", "profile", "tenant_id"])
def test_invoke_disallows_connection_and_identity_overrides(override):
    with pytest.raises(ValidationError):
        TypeAdapter(ModelInvocation).validate_python({
            "operation": "chat",
            "model_id": 1,
            "input": [{"role": "user", "content": "question"}],
            override: "override",
        })


@pytest.mark.asyncio
async def test_metadata_omits_credentials():
    load = Mock(return_value=_record(access_token="secret", base_url="private", capability_profile_version="p1"))
    model = await ModelService(load, None).get(1, _ACTOR)
    load.assert_called_once_with(1, "tenant")
    assert model.model_dump() == {
        "model_id": 1,
        "model_type": "llm",
        "display_name": None,
        "revision": "2026-11-09",
        "profile_version": "p1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record", "revision", "status"),
    [
        (None, None, 404),
        (_record(tenant_id="foreign"), None, 404),
        (_record(delete_flag="Y"), None, 404),
        (_record(), "stale", 409),
        (_record(model_type="embedding"), None, 422),
    ],
)
async def test_rejected_model_requests_never_build_provider(record, revision, status):
    build = Mock()
    service = ModelService(Mock(return_value=record), build)
    request = ChatInvocation(
        model_id=1, input=[ChatMessage(role="user", content="question")], expected_revision=revision
    )
    with pytest.raises(ModelAccessError) as exc:
        await service.invoke(request, _ACTOR)
    assert exc.value.status == status
    build.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_type", "request_body", "provider_result", "expected"),
    [
        (
            "chat",
            ChatInvocation(model_id=1, input=[ChatMessage(role="user", content="question")]),
            SimpleNamespace(content="answer"),
            {"content": "answer"},
        ),
        (
            "embedding",
            EmbeddingInvocation(model_id=1, input=["sentence"]),
            [[0.1, 0.2]],
            [[0.1, 0.2]],
        ),
        (
            "rerank",
            RerankInvocation(
                model_id=1,
                input=RerankInput(query="question", documents=["document"]),
                options=RerankOptions(top_n=1),
            ),
            [{"index": 0, "score": 0.9}],
            [{"index": 0, "score": 0.9}],
        ),
    ],
)
async def test_model_invoke_uses_registered_model(model_type, request_body, provider_result, expected):
    record = _record(model_type=model_type)
    adapter = SimpleNamespace(invoke=AsyncMock(return_value=provider_result))
    build = Mock(return_value=adapter)
    result = await ModelService(Mock(return_value=record), build).invoke(request_body, _ACTOR)
    if model_type == "embedding":
        assert adapter.invoke.await_args.args[0].worker_lane == "model-embedding"
    assert result.output == expected
    assert result.revision == record["update_time"]
    assert build.call_args.args[0] is record
    adapter.invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [None, 5])
async def test_private_judge_requires_and_forwards_a_confirmation_lease(mocker, attempt):
    from contextlib import nullcontext

    from runtime.model import service as model_service

    mocker.patch.object(model_service.environment, "EVOLUTION_CONFIRMATION_BUCKET", "private-suites")
    mocker.patch.object(model_service.environment, "ENABLE_TELEMETRY", False)
    mocker.patch.object(model_service, "confirmation_budget", return_value=object())
    meter = mocker.patch.object(model_service, "meter_evaluation", return_value=nullcontext())
    adapter = Mock(spec=model_service.OpenAILLMAdapter)
    adapter.invoke = AsyncMock(return_value=SimpleNamespace(content="measured"))
    build = Mock(return_value=adapter)
    service = ModelService(Mock(return_value=_record()), build)
    payload = ChatInvocation(model_id=1, input=[ChatMessage(role="user", content="private task")],
                             evaluation_attempt=attempt)
    if attempt is None:
        with pytest.raises(ModelAccessError) as exc:
            await service.invoke(payload, _ACTOR)
        assert (exc.value.status, exc.value.code) == (422, "INVALID_EVOLUTION_METERING_SCOPE")
        build.assert_not_called()
    else:
        assert (await service.invoke(payload, _ACTOR)).output == {"content": "measured"}
        meter.assert_called_once_with(attempt, _ACTOR, 1, confirmation=True)
        adapter.invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [None, 32])
async def test_explicit_job_output_limit_reaches_wire_only_for_that_invocation(mocker, limit):
    from runtime.model import service as model_service

    mocker.patch.object(model_service.environment, "EVOLUTION_CONFIRMATION_BUCKET", "")
    wire = {}

    async def invoke(_request):
        admit = model_wire_budget.get()
        if admit:
            admit(wire, 1)
        return SimpleNamespace(content="answer")

    adapter = Mock(spec=model_service.OpenAILLMAdapter, invoke=AsyncMock(side_effect=invoke))
    build = Mock(return_value=adapter)
    payload = ChatInvocation(
        model_id=1, input=[ChatMessage(role="user", content="question")],
        options=ChatOptions(temperature=0.3), evolution_output_limit=limit,
    )
    result = await ModelService(Mock(return_value=_record()), build).invoke(payload, _ACTOR)
    assert result.output == {"content": "answer"}
    assert wire == ({} if limit is None else {"max_tokens": limit})
    assert build.call_args.kwargs == {"stream": False, "temperature": 0.3}
    assert model_wire_budget.get() is None


@pytest.mark.asyncio
async def test_evolution_output_limit_cannot_override_an_evaluation_lease(mocker):
    from runtime.model import service as model_service

    mocker.patch.object(model_service.environment, "EVOLUTION_CONFIRMATION_BUCKET", "")
    build = Mock()
    payload = ChatInvocation(
        model_id=1, input=[ChatMessage(role="user", content="question")],
        evaluation_attempt=5, evolution_output_limit=32,
    )
    with pytest.raises(ModelAccessError) as exc:
        await ModelService(Mock(return_value=_record()), build).invoke(payload, _ACTOR)
    assert (exc.value.status, exc.value.code) == (422, "INVALID_EVOLUTION_METERING_SCOPE")
    build.assert_not_called()


@pytest.mark.parametrize("options", [{"temperature": -1}, {"top_p": 2}, {"api_key": "secret"}])
def test_chat_sampling_does_not_allow_connection_fields_or_unbounded_values(options):
    with pytest.raises(ValidationError):
        ChatOptions.model_validate(options)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "dimension", "missing"])
async def test_memory_query_embedding_checks_binding_and_dimension(mocker, outcome):
    from management.services.memory.embedding import embed_memory_text

    model = SimpleNamespace(model_id=11 if outcome != "missing" else None, revision="rev", dimension=2)
    invoke = mocker.patch(
        "management.clients.model.embed_query", new_callable=AsyncMock,
        return_value=[0.1, 0.2] if outcome == "success" else [0.1],
    )

    result = await embed_memory_text("query", model, _ACTOR.user_id, _ACTOR.tenant_id)

    assert result == ([0.1, 0.2] if outcome == "success" else None)
    if outcome == "missing":
        invoke.assert_not_awaited()
    else:
        invoke.assert_awaited_once_with(
            model_id=11, revision="rev", query="query", user_id=_ACTOR.user_id, tenant_id=_ACTOR.tenant_id,
        )


@pytest.mark.asyncio
async def test_memory_embedding_budget_reaches_runtime_adapter_without_changing_normal_invocations(monkeypatch):
    from infrastructure import memory_embedding_health

    monkeypatch.setattr(memory_embedding_health, "MEMORY_EMBEDDING_COOLDOWN_SECONDS", 0)
    adapter = SimpleNamespace(
        get_embeddings_with_deadline=AsyncMock(return_value=[[0.25, 0.75]]),
        invoke=AsyncMock(return_value=[[0.25, 0.75]]),
    )
    record = _record(model_type="embedding", model_name="embed", max_tokens=2)
    service = ModelService(Mock(return_value=record), Mock(return_value=adapter))
    automatic = await service.invoke(EmbeddingInvocation(
        model_id=7, input=["query"], memory_timeout_seconds=0.5,
    ), _ACTOR)
    assert automatic.output == [[0.25, 0.75]]
    assert 0 < adapter.get_embeddings_with_deadline.await_args.kwargs["timeout"] < 0.5
    adapter.invoke.assert_not_awaited()
    ordinary = await service.invoke(EmbeddingInvocation(model_id=7, input=["a", "b"]), _ACTOR)
    assert ordinary.output == [[0.25, 0.75]]
    assert adapter.invoke.await_args.args[0].inputs == ["a", "b"]
    assert adapter.invoke.await_args.args[0].retries == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["healthy", "upstream_timeout", "connection", "transport_deadline", "cancel"])
async def test_shared_embedding_health_uses_an_available_runtime_lane(monkeypatch, outcome):
    import asyncio
    import httpx
    from threading import Event, get_ident
    from infrastructure import memory_embedding_health as health, memory_io
    from nexent.core.concurrency import LanePolicy, ThreadManager
    from runtime.thread_management import runtime_thread_manager

    # Use the actual Runtime lane names; an invented lane must not silently
    # degrade shared health into process-local-only state.
    manager = ThreadManager('health-runtime-contract', {
        lane.name: LanePolicy(name=lane.name, max_workers=2, max_queue_size=0,
                              queue_timeout_seconds=0, cancel_grace_seconds=0, shutdown_grace_seconds=1)
        for lane in runtime_thread_manager.snapshot().lanes
    })
    manager.start()
    caller = get_ident()
    worker = []
    entered, release = Event(), Event()
    def read(_key):
        worker.append(get_ident())
        entered.set()
        if outcome == "cancel":
            release.wait(.5)
        return None
    redis = Mock(get=Mock(side_effect=read))
    monkeypatch.setattr(health, '_client', lambda: redis)
    monkeypatch.setattr(health, 'MEMORY_EMBEDDING_COOLDOWN_SECONDS', 300)
    monkeypatch.setattr(memory_io, 'get_default_thread_manager', lambda: manager)
    adapter = SimpleNamespace(get_embeddings_with_deadline=AsyncMock(return_value=[[.25, .75]]))
    if outcome in {"upstream_timeout", "transport_deadline", "connection"}:
        adapter.get_embeddings_with_deadline.side_effect = (
            httpx.ConnectError("unreachable") if outcome == "connection" else httpx.ReadTimeout("read deadline")
        )
    if outcome == "transport_deadline":
        from runtime.model import memory_embedding
        monkeypatch.setattr(memory_embedding, "remaining_time", Mock(side_effect=[1., .15, .04]))
    health._local.clear()
    record = _record(model_type='embedding', model_name='embed', max_tokens=2)
    service = ModelService(Mock(return_value=record), Mock(return_value=adapter))
    try:
        invocation = service.invoke(EmbeddingInvocation(model_id=7, input=['query'], memory_timeout_seconds=1), _ACTOR)
        if outcome == "cancel":
            task = asyncio.create_task(invocation)
            while not entered.is_set():
                await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            adapter.get_embeddings_with_deadline.assert_not_awaited()
        else:
            result = await invocation
            assert result.output == ([[.25, .75]] if outcome == "healthy" else None)
            assert redis.set.called is (outcome in {"upstream_timeout", "connection"})
        redis.get.assert_called_once()
        assert worker and worker[0] != caller
    finally:
        release.set()
        await manager.shutdown(timeout=1)
        health._local.clear()
