# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Chunk writes require live EDIT rights and never borrow a KB creator's identity."""

import pytest
from contracts.knowledge_chunk_mutation import ChunkMutationAuthorization
from management.services.knowledge_base.chunk_write_authorization import (
    authorize_chunk_mutation,
)
from nexent.storage.errors import NotFound, ScopeDenied

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_file_reader import (
    reader as reader,  # noqa: PLC0414
)


def request():
    return ChunkMutationAuthorization(
        knowledge_id=1, chunk_id="manual", operation="create"
    )


def test_creator_receives_exact_write_grant_with_actual_actor(reader):
    s = reader
    result = authorize_chunk_mutation(
        request(), s.actor, context=context(), reader=s.service
    )
    assert (
        result.knowledge_id == 1
        and result.chunk_id == "manual"
        and result.operation == "create"
    )
    assert (
        result.collection == "kb-one" and result.resource_tenant_id == s.actor.tenant_id
    )
    assert len(result.revision) == 64


@pytest.mark.parametrize(
    "updates",
    [
        {"created_by": "other", "ingroup_permission": "READ_ONLY"},
        {"created_by": "other", "ingroup_permission": "PRIVATE"},
        {"deletion_request": {"scope": "full"}},
        {"knowledge_sources": "datamate"},
    ],
)
def test_read_only_private_deleting_and_external_resources_cannot_receive_write_grant(
    reader, updates
):
    reader.update("cleanse_knowledge", **updates)
    with pytest.raises(ScopeDenied):
        authorize_chunk_mutation(
            request(), reader.actor, context=context(), reader=reader.service
        )


def test_missing_knowledge_is_not_found_without_exposing_internal_lookup(reader):
    missing = request().model_copy(update={"knowledge_id": 999})
    with pytest.raises(NotFound):
        authorize_chunk_mutation(
            missing, reader.actor, context=context(), reader=reader.service
        )
