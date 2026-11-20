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
