# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-UPDATE-03 preserves confirmed user-supplied vector recall."""

from dataclasses import replace

import pytest
from nexent.storage.models import Revision

from test.backend.services.test_knowledge_mutable_search import change, independent
from test.backend.services.test_knowledge_mutable_search import (
    search as search,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_mutable_search import (
    setup as setup,  # noqa: PLC0414
)


@pytest.mark.parametrize("standalone", [True, False])
async def test_confirmed_manual_vector_without_model_tags_can_be_recalled(search, standalone):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=standalone, index=7)
    row = independent(hit, receipt) if standalone else replace(hit, payload={**hit.payload,
        "chunk_index": 7, "embedding_model_id": None, "embedding_revision": None})
    s.vectors.search.return_value = (row,)
    result = await service.search(request.model_copy(update={"search_mode": "semantic"}), s.actor)
    assert len(result.hits) == 1 and result.hits[0].chunk_id == row.key.key
    assert row.payload["embedding_model_id"] is None and row.payload["embedding_revision"] is None
    assert [call.args[0].operation for call in s.models.invoke.await_args_list] == ["embedding"]


@pytest.mark.parametrize("model_id,revision", [(9, "v1"), (2, "wrong"), (None, "v1"), (2, None)])
async def test_declared_other_or_partial_model_identity_is_never_treated_as_unbound(search, model_id, revision):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=True)
    row = independent(hit, receipt)
    row = replace(row, payload={**row.payload, "embedding_model_id": model_id, "embedding_revision": revision})
    s.vectors.search.return_value = (row,)
    result = await service.search(request.model_copy(update={"search_mode": "semantic"}), s.actor)
    assert result.hits == []


@pytest.mark.parametrize("fault", ["untracked-file", "orphan", "generation", "deleted"])
async def test_missing_current_manual_origin_cannot_enable_unbound_vector_recall(search, fault):
    s, request, _, hit, service = search
    if fault == "untracked-file":
        row = replace(hit, payload={**hit.payload, "embedding_model_id": None, "embedding_revision": None})
    else:
        receipt = await change(search, "create", standalone=True) if fault != "orphan" else {"mutation_id": "f" * 64}
        row = independent(hit, receipt)
        if fault == "generation":
            row = replace(row, generation=Revision("wrong"))
        if fault == "deleted":
            await change(search, "delete", standalone=True)
    s.vectors.search.return_value = (row,)
    result = await service.search(request.model_copy(update={"search_mode": "semantic"}), s.actor)
    assert result.hits == []
