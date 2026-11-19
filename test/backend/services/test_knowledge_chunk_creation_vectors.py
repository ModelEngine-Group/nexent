# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-CREATE-02 preserves supplied vectors and Runtime model resolution."""

from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
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


@pytest.mark.parametrize("model_failure", [False, True])
async def test_supplied_vector_is_preserved_without_model_success(creation, model_failure):
    s = creation
    changes = {**s.value.changes, "supplied_embedding": [0.0, 1.0, 0.0]}
    if model_failure:
        changes["embedding_model"] = {"model_id": 2, "revision": "r1"}
        s.models.invoke.side_effect = RuntimeError("original provider failure")
    result = await s.service.execute(s.value.model_copy(update={"changes": changes}), context=context())
    assert result["status"] == "completed" and s.stored[0].vector == (0.0, 1.0, 0.0)
    assert s.models.invoke.await_count == int(model_failure)


async def test_generated_vector_overrides_invalid_supplied_value_and_source_model_id(creation):
    s = creation
    value = s.value.model_copy(update={"changes": {**s.value.changes,
        "supplied_embedding": {"invalid": True}, "embedding_model": {"model_id": 2, "revision": "r1"},
        "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "manual", "embedding_model_id": "untrusted"}}}})
    result = await s.service.execute(value, context=context())
    assert result["status"] == "completed" and s.stored[0].vector == (1.0, 0.0, 0.0)
    assert s.stored[0].payload["location"][PUBLIC_CHUNK_SOURCE_KEY]["embedding_model_id"] == 2
    assert s.models.invoke.await_count == 1


async def test_id_only_model_is_resolved_in_runtime_with_actual_actor(creation):
    s = creation
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type="embedding", display_name=None, revision="r1"))
    value = s.value.model_copy(update={"changes": {**s.value.changes,
        "content": ["stored", "metadata"], "embedding_input": "original request",
        "embedding_model": {"model_id": 2}}})
    assert (await s.service.execute(value, context=context()))["status"] == "completed"
    s.models.get.assert_awaited_once_with(2, s.s.actor)
    assert s.models.invoke.await_args.args[0].expected_revision == "r1"
    assert s.models.invoke.await_args.args[0].input == ["original request"]
    assert s.stored[0].payload["content"] == ["stored", "metadata"]


async def test_model_lookup_failure_preserves_explicit_vector_and_does_not_invoke(creation):
    s = creation
    s.models.get = AsyncMock(side_effect=RuntimeError("unavailable"))
    value = s.value.model_copy(update={"changes": {**s.value.changes, "embedding_model": {"model_id": 2},
        "supplied_embedding": [1.0, 0.0, 0.0]}})
    assert (await s.service.execute(value, context=context()))["status"] == "completed"
    assert s.stored[0].vector == (1.0, 0.0, 0.0)
    assert s.stored[0].payload["embedding_model_id"] is None
    s.models.invoke.assert_not_awaited()


@pytest.mark.parametrize("supplied", [[], [0.0, 0.0], [True, 1.0], "bad", {"bad": 1}])
async def test_invalid_used_vector_fails_before_vector_write_and_releases_admission(creation, supplied):
    s = creation
    value = s.value.model_copy(update={"changes": {**s.value.changes, "supplied_embedding": supplied}})
    with pytest.raises(InvalidInput):
        await s.service.execute(value, context=context())
    s.vectors.put.assert_not_called()
    await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.parametrize("supplied", [None])
async def test_empty_supplied_vector_retains_plaintext_semantics(creation, supplied):
    s = creation
    value = s.value.model_copy(update={"changes": {**s.value.changes, "supplied_embedding": supplied}})
    assert (await s.service.execute(value, context=context()))["status"] == "completed"
    assert s.stored[0].vector == ()
    s.models.invoke.assert_not_awaited()
