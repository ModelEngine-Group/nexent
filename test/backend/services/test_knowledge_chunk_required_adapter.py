# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-EMBED-01 keeps required inference under trusted caller control."""

import pytest
from contracts.knowledge import ChunkCreateRequest
from contracts.knowledge_chunk_mutation import ChunkCreateData
from management.services.knowledge_base.chunk_creation import create_manual_chunk
from nexent.storage.errors import InvalidInput
from pydantic import ValidationError

from test.backend.services.test_knowledge_chunk_public_create import (
    creation as creation,  # noqa: PLC0414
)


@pytest.mark.parametrize("required", [False, True])
async def test_adapter_transmits_required_inference_without_trusting_display_metadata(creation, required):
    s = creation
    request = ChunkCreateRequest(content="body", metadata={"require_embedding": not required})
    await create_manual_chunk("kb", request, s.actor, reader=s.reader, client=s.client, require_embedding=required)
    changes = s.client.mutate_knowledge_chunk.await_args.args[0].changes
    assert changes.get("require_embedding", False) is required
    if not required:
        assert "require_embedding" not in changes


@pytest.mark.parametrize("required", [None, 1, "true"])
async def test_invalid_policy_is_refused_before_resource_or_http(creation, required):
    s = creation
    with pytest.raises(InvalidInput):
        await create_manual_chunk("kb", ChunkCreateRequest(content="body"), s.actor,
                                  reader=s.reader, client=s.client, require_embedding=required)
    s.reader.knowledge.assert_not_called()
    s.client.inspect_knowledge_chunk.assert_not_called()


@pytest.mark.parametrize("values", [{"embedding_model": None}, {"embedding_input": ""}, {"content": ""}])
def test_required_contract_cannot_skip_inference(values):
    with pytest.raises(ValidationError):
        ChunkCreateData.model_validate({"content": "body", "require_embedding": True,
                                       "embedding_model": {"model_id": 2}, **values})
