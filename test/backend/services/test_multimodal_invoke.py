# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Inline image embedding contract and model selection guards."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import EmbeddingInvocation
from pydantic import ValidationError
from runtime.model import service as module

from infrastructure.agentos_identity import ServicePrincipal

IMAGE = "data:image/png;base64,aW1hZ2U="


@pytest.fixture(autouse=True)
def lookups(monkeypatch):
    async def direct(name, fn, *args, **kwargs):
        return fn(*args)
    monkeypatch.setattr(module, "run_blocking", direct)


@pytest.mark.parametrize("value", ["https://images.test/a.png", "s3://files/a.png", "/tmp/a.png",
                                   "data:text/plain;base64,aW1hZ2U=", "data:image/png;base64,***", "data:image/png;base64,"])
def test_image_contract_rejects_untrusted_sources(value):
    with pytest.raises(ValidationError):
        EmbeddingInvocation(model_id=1, input=[value], input_type="image")


@pytest.mark.asyncio
async def test_image_invocation_selects_multimodal_adapter():
    actor = ServicePrincipal("user", "tenant")
    record = {"tenant_id": "tenant", "delete_flag": "N", "model_type": "multi_embedding", "update_time": "v1"}
    adapter = SimpleNamespace(invoke=AsyncMock(return_value=[[1.0, 0.5]]))
    build = Mock(return_value=adapter)
    result = await module.ModelService(Mock(return_value=record), build).invoke(
        EmbeddingInvocation(model_id=1, input=[IMAGE], input_type="image"), actor)
    assert result.output == [[1.0, 0.5]]
    assert build.call_args.args[1:4] == ("multi_embedding", "multiEmbedding", "tenant")
    request = adapter.invoke.await_args.args[0]
    assert request.inputs == [{"image": IMAGE}]
    assert request.worker_lane == "model-embedding"


@pytest.mark.asyncio
async def test_text_model_rejects_image_before_adapter_construction():
    record = {"tenant_id": "tenant", "delete_flag": "N", "model_type": "embedding", "update_time": "v1"}
    build = Mock()
    with pytest.raises(module.ModelAccessError) as caught:
        await module.ModelService(Mock(return_value=record), build).invoke(
            EmbeddingInvocation(model_id=1, input=[IMAGE], input_type="image"), ServicePrincipal("user", "tenant"))
    assert caught.value.status == 422
    build.assert_not_called()
