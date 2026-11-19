# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-TOOL-CONTENT-01/02/03/04 reject changes during outer tool reranking."""

import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeSearchGrant,
    KnowledgeSearchResult,
    ModelVersion,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext
from pydantic import ValidationError
from runtime.knowledge_base.tool_search import KnowledgeToolSearch

from test.backend.services.test_knowledge_mutable_search import change
from test.backend.services.test_knowledge_search import (
    search as search,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_search import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_tool_search import binding, hit
from test.backend.services.test_knowledge_tool_search import (
    service as service,  # noqa: PLC0414
)


@pytest.mark.parametrize("change_during_rerank", [None, "update", "delete", "active", "file-delete"])
async def test_outer_rerank_requires_unchanged_confirmed_content(search, change_during_rerank):
    s, _, grant, _, service = search
    invoke = s.models.invoke.side_effect

    async def changing(payload, actor):
        if payload.operation == "rerank":
            if change_during_rerank == "file-delete":
                await s.db(s.policy.submit, KnowledgeFileDelete(
                    knowledge_id=1, file_id=s.request.file_id, file_version=0, idempotency_key="delete"), context=s.context)
            elif change_during_rerank is not None:
                await change(search, "update" if change_during_rerank == "active" else change_during_rerank,
                             complete=change_during_rerank != "active")
        return await invoke(payload, actor)

    s.models.invoke.side_effect = changing
    tool = KnowledgeToolSearch(service, s.actor, [(grant.knowledge_bases[0], ModelVersion(model_id=2, revision="v1"))])
    if change_during_rerank is None:
        rows = await tool.search("query", ["kb"], search_mode="semantic", rerank_model=ModelVersion(model_id=3, revision="v1"))
        assert len(rows) == 1 and rows[0].content == "worker content" and rows[0].score_kind == "model.rerank"
    else:
        with pytest.raises(Conflict):
            await tool.search("query", ["kb"], search_mode="semantic", rerank_model=ModelVersion(model_id=3, revision="v1"))
    assert [call.args[0].operation for call in s.models.invoke.await_args_list] == ["embedding", "rerank"]
    assert s.vectors.search.call_count == 1


async def test_search_returns_complete_data_revisions_for_final_verification(search):
    s, request, grant, _, service = search
    result = await service.search(request, s.actor)
    assert set(result.data_revisions) == {1} and len(result.data_revisions[1]) == 64
    await service.verify_data_revisions(grant.knowledge_bases, result.data_revisions, s.actor, context=s.context)
    assert s.vectors.search.call_count == 1 and s.models.invoke.await_count == 1
    await change(search, "update")
    with pytest.raises(Conflict):
        await service.verify_data_revisions(grant.knowledge_bases, result.data_revisions, s.actor, context=s.context)
    assert s.vectors.search.call_count == 1 and s.models.invoke.await_count == 1


@pytest.mark.parametrize("versions", [{}, {2: "a" * 64}, {1: "a" * 64, 2: "a" * 64}])
async def test_missing_or_extra_group_revisions_are_refused_before_rerank(service, versions):
    actor = SimpleNamespace(user_id="user", tenant_id="tenant")
    service.search.return_value = SimpleNamespace(hits=[hit()], data_revisions=versions)
    tool = KnowledgeToolSearch(service, actor, [binding()])
    with pytest.raises(ScopeDenied):
        await tool.search("query", ["kb-1"], rerank_model=ModelVersion(model_id=3, revision="v1"))
    service.models.invoke.assert_not_called()
    service.verify_data_revisions.assert_not_called()


async def test_final_content_check_uses_parent_deadline_without_replay(service, caplog):
    ended = asyncio.Event()

    async def hanging(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    actor = SimpleNamespace(user_id="user", tenant_id="tenant")
    service.search.return_value = SimpleNamespace(hits=[hit()], data_revisions={1: "a" * 64})
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[binding()[0]])
    service.verify_data_revisions.side_effect = hanging
    tool = KnowledgeToolSearch(service, actor, [binding()])
    context = OperationContext("tool-content-timeout", monotonic() + 0.05)
    with pytest.raises(DeadlineExceeded):
        await tool.search("private query", ["kb-1"], context=context)
    assert ended.is_set() and service.search.await_count == 1
    service.models.invoke.assert_not_called()
    call = service.verify_data_revisions.await_args
    assert call.args == ([binding()[0]], {1: "a" * 64}, actor)
    assert call.kwargs["context"] is context
    assert "phase=content" in caplog.text and "private query" not in caplog.text


def test_data_revisions_round_trip_decoded_json_response():
    result = KnowledgeSearchResult(hits=[], data_revisions={1: "a" * 64},
                                   embedding_model=ModelVersion(model_id=2, revision="v1"))
    assert KnowledgeSearchResult.model_validate(result.model_dump(mode="json")) == result
    assert KnowledgeSearchResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("values", [{}, {"01": "a" * 64}, {"1": "a" * 64, 1: "a" * 64},
                                    {-1: "a" * 64}, {True: "a" * 64}, {1: "invalid"}])
def test_data_revisions_refuse_ambiguous_or_invalid_scope(values):
    with pytest.raises(ValidationError):
        KnowledgeSearchResult(hits=[], data_revisions=values, embedding_model=ModelVersion(model_id=2, revision="v1"))
