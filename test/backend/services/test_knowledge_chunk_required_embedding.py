# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-EMBED-02 preserves strict document inference failure semantics."""

from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata, ModelResult
from contracts.knowledge_chunk_mutation import mutation_id
from nexent.storage.errors import InvalidInput

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


def strict_intent(s, **changes):
    return s.value.model_copy(update={"changes": {**s.value.changes, "require_embedding": True,
        "embedding_model": {"model_id": 2, "revision": "r1"}, **changes}})


@pytest.mark.parametrize("output", [[], [[0, 0, 0]], [[1, 0]], [[float("nan"), 0, 0]]])
async def test_invalid_strict_result_never_writes_plaintext_or_supplied_vector(creation, output):
    s = creation
    s.models.invoke.return_value = ModelResult(revision="r1", output=output)
    with pytest.raises((ValueError, InvalidInput)):
        await s.service.execute(strict_intent(s, supplied_embedding=[0, 1, 0]), context=context())
    assert s.stored[0] is None
    s.vectors.put.assert_not_called()
    s.vectors.ensure_collection.assert_not_called()
    assert await s.db(s.s.mutation.standalone_count, context=context()) == 0
    key = mutation_id(s.s.actor.tenant_id, s.s.actor.user_id, strict_intent(s, supplied_embedding=[0, 1, 0]))
    state = await s.db(s.s.mutation.inspect, key, context=context())
    assert state["status"] == "failed" and state["writer_ended"]


async def test_strict_provider_failure_preserves_original_exception_and_existing_body(creation):
    s = creation
    await s.service.execute(s.value, context=context())
    original = s.stored[0]
    error = RuntimeError("provider failed")
    s.models.invoke.side_effect = error
    value = strict_intent(s, supplied_embedding=[0, 1, 0]).model_copy(update={"request_key": "strict"})
    with pytest.raises(RuntimeError) as caught:
        await s.service.execute(value, context=context())
    assert caught.value is error and s.stored[0] is original
    assert s.vectors.put.call_count == 1 and s.models.invoke.await_count == 1


async def test_required_id_only_model_is_resolved_in_runtime_and_writes_vector(creation):
    s = creation
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type="embedding", display_name="model", revision="r1"))
    value = strict_intent(s, embedding_model={"model_id": 2})
    result = await s.service.execute(value, context=context())
    assert result["status"] == "completed" and s.stored[0].vector == (1, 0, 0)
    s.models.get.assert_awaited_once_with(2, s.s.actor)
    assert s.models.invoke.await_args.args[0].expected_revision == "r1"
