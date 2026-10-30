# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolved outlets retain the existing gateway interface over one transport."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.gateway.modality.llm.llm_adapter import LLMRequest
from nexent.core.gateway.modality.llm.openai import OpenAILLMAdapter
from nexent.core.gateway.model_context import LLMContext
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import TokenUsage


def adapter_for(profile):
    return OpenAILLMAdapter(LLMContext(
        model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="controlled-key", modality="llm", factory="openai",
        tenant_id=profile.identity.tenant_id, resolved_profile=profile,
        cancellation_scope=RunCancellationScope(),
    ))


def test_gateway_constructs_shared_model_and_declares_profile_capabilities(openai_profile):
    adapter = adapter_for(openai_profile)
    adapter._build_model()
    assert isinstance(adapter._model, LegacyChatModel)
    assert adapter._model.cancellation_scope is adapter._context.cancellation_scope
    info = adapter.get_model_info()
    assert info.provider == openai_profile.identity.provider_id
    assert info.model_id == openai_profile.identity.request_model_id
    assert info.capabilities["tool_calling"] == (openai_profile.capabilities.tools.status == "supported")
    assert info.capabilities["text"] == ("text" in openai_profile.capabilities.modalities.output)


@pytest.mark.parametrize("field,value", [("tenant_id", "other"), ("model_name", "other"), ("base_url", "https://other.test")])
def test_gateway_rejects_mixed_snapshot_identity(openai_profile, field, value):
    adapter = adapter_for(openai_profile)
    setattr(adapter._context, field, value)
    with pytest.raises(ValueError, match="outlet snapshot"):
        adapter._build_model()
    assert adapter._model is None


@pytest.mark.asyncio
async def test_gateway_health_uses_shared_model_probe(openai_profile, monkeypatch):
    adapter = adapter_for(openai_profile)
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr(LegacyChatModel, "check_connectivity", probe)
    assert await adapter.health_check() is True
    probe.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_gateway_async_stream_closes_transport_on_early_exit_or_cancel(openai_profile, monkeypatch, cancel):
    adapter = adapter_for(openai_profile)
    adapter._build_model()
    opened, closed = [], []

    @asynccontextmanager
    async def transport(request, profile, *, scope):
        opened.append((request, profile, scope))

        async def events():
            if cancel:
                raise RunTerminated()
            yield SimpleNamespace(type="text_delta", content_kind="text", delta="body")
            yield SimpleNamespace(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=2))

        try:
            yield events()
        finally:
            closed.append(True)

    monkeypatch.setattr(adapter._model.service, "astream", transport)
    stream = await adapter.stream(LLMRequest(messages=[{"role": "user", "content": "hello"}]))
    if cancel:
        with pytest.raises(RunTerminated):
            await anext(stream)
    else:
        assert (await anext(stream)).content == "body"
        await stream.aclose()
    assert closed == [True] and len(opened) == 1
    assert opened[0][2] is adapter._context.cancellation_scope
    assert opened[0][0].stream is True
