# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-EMBED-03/04 keep image inference explicit and Runtime-owned."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata
from contracts.knowledge_chunk_mutation import ChunkCreateData
from pydantic import ValidationError

from test.backend.services.test_knowledge_chunk_creation import context
from test.backend.services.test_knowledge_chunk_creation import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_required_embedding import strict_intent

IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4x8AAAAASUVORK5CYII="


@pytest.mark.parametrize("changes", [{"embedding_input": "https://example.invalid/a.png"},
    {"embedding_input": "data:image/png;base64,"}, {"embedding_input": "data:image/png;base64,%%%"},
    {"embedding_input": None}, {"embedding_model": None}, {"require_embedding": False}])
def test_image_contract_refuses_unpinned_or_noninline_requests(changes):
    with pytest.raises(ValidationError):
        ChunkCreateData(content="caption", embedding_input_type="image", **{
            "embedding_input": IMAGE, "embedding_model": {"model_id": 2, "revision": "r1"},
            "require_embedding": True, **changes})


async def test_image_invoke_keeps_caption_and_image_bytes_separate(creation):
    s = creation
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type="multi_embedding", display_name="image", revision="r1"))
    value = strict_intent(s, content="caption", embedding_input_type="image", embedding_input=IMAGE)
    result = await s.service.execute(value, context=context())
    assert result["status"] == "completed" and s.stored[0].payload["content"] == "caption"
    invocation, actor = s.models.invoke.await_args.args
    assert actor == s.s.actor and invocation.input_type == "image" and invocation.input == [IMAGE]
    assert invocation.expected_revision == "r1" and s.stored[0].payload["embedding_revision"] == "r1"
    assert IMAGE not in str(s.stored[0].payload) and IMAGE not in str(result)


@pytest.mark.parametrize("model_type,revision", [("embedding", "r1"), ("multi_embedding", "stale")])
async def test_image_rejects_incompatible_or_stale_model_before_inference(creation, model_type, revision):
    s = creation
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type=model_type, display_name="image", revision=revision))
    with pytest.raises(ValueError):
        await s.service.execute(strict_intent(s, embedding_input_type="image", embedding_input=IMAGE), context=context())
    s.models.invoke.assert_not_called()
    s.vectors.put.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("image provider failed"), asyncio.CancelledError()])
async def test_image_failure_or_cancellation_never_becomes_plaintext(creation, error):
    s = creation
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type="multi_embedding", display_name="image", revision="r1"))
    s.models.invoke.side_effect = error
    with pytest.raises(type(error)) as caught:
        await s.service.execute(strict_intent(s, embedding_input_type="image", embedding_input=IMAGE,
                                             supplied_embedding=[0, 1, 0]), context=context())
    assert caught.value is error and s.models.invoke.await_count == 1
    s.vectors.put.assert_not_called()
