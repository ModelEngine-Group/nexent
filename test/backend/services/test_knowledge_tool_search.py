# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound tool retrieval must preserve every model and authorization scope."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelResult
from contracts.agentos_knowledge import (
    KnowledgeBaseGrant,
    KnowledgeFileReference,
    KnowledgeSearchGrant,
    KnowledgeSearchHit,
    ModelVersion,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from runtime.knowledge_base.tool_search import KnowledgeToolSearch


def binding(knowledge_id=1, model_id=2):
    return (KnowledgeBaseGrant(knowledge_id=knowledge_id, collection=f"kb-{knowledge_id}", resource_tenant_id="tenant",
                              embedding_model_id=model_id, revision="a" * 64),
            ModelVersion(model_id=model_id, revision="v1"))


def hit(knowledge_id=1, score=0.8):
    return KnowledgeSearchHit(knowledge_id=knowledge_id, file_id="f" * 32, file_version=0,
                              chunk_id=f"{knowledge_id}/f/0/0", content="visible content",
                              score=score, score_kind="elasticsearch.cosine", location={"page_number": 3})


def _response(*, hits):
    return SimpleNamespace(hits=hits, data_revisions={hit.knowledge_id: "a" * 64 for hit in hits})


@pytest.fixture
def service():
    return SimpleNamespace(search=AsyncMock(), verify_data_revisions=AsyncMock(), models=SimpleNamespace(invoke=AsyncMock()),
                           client=SimpleNamespace(authorize_knowledge_search=AsyncMock()))


@pytest.mark.asyncio
async def test_groups_all_models_and_fuses_ranks_without_comparing_raw_scores(service):
    bindings = [binding(), binding(2, 3), binding(3, 2)]
    service.search.side_effect = [_response(hits=[hit(1, .1), hit(3, .09)]), _response(hits=[hit(2, 900)])]
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[b[0] for b in bindings])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), bindings)
    rows = await tool.search("query", ["kb-1", "kb-2", "kb-3"], top_k=3)
    assert [row.knowledge_id for row in rows] == [1, 2, 3]
    assert all(row.score_kind == "runtime.model_rrf" for row in rows)
    calls = service.search.await_args_list
    assert [c.args[0].knowledge_ids for c in calls] == [[1, 3], [2]]
    assert [c.args[0].embedding_model.model_id for c in calls] == [2, 3]
    assert calls[0].args[0].expected_revisions == {1: "a" * 64, 3: "a" * 64}
    assert calls[0].kwargs["context"] is calls[1].kwargs["context"]
    assert rows[0].location == {"page_number": 3}
    assert rows[0].score_details["model_score"] == .1
    service.models.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_fixed_files_and_single_group_preserve_scores_and_model_rerank(service):
    resource, model = binding()
    service.search.return_value = _response(hits=[hit()])
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[resource])
    service.models.invoke.return_value = ModelResult(revision="v2", output=[{"index": 0, "relevance_score": .95}])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [(resource, model)], file_refs=[KnowledgeFileReference(knowledge_id=1, file_id="f" * 32, file_version=0)])
    plain = await tool.search("query", ["kb-1"], top_k=1)
    assert plain[0].score == .8 and plain[0].score_kind == "elasticsearch.cosine"
    rows = await tool.search("query", ["kb-1"], top_k=1, rerank_model=ModelVersion(model_id=4, revision="v2"))
    assert rows[0].score == .95 and rows[0].score_kind == "model.rerank"
    payload = service.search.await_args.args[0]
    assert payload.file_ids == ["f" * 32] and payload.rerank_model is None
    assert payload.file_versions == {"f" * 32: 0}
    invoke = service.models.invoke.await_args.args[0]
    assert invoke.input.documents == ["visible content"] and invoke.model_id == 4


@pytest.mark.asyncio
async def test_native_tool_uses_pinned_file_versions_and_rechecks_native_snapshot_after_rerank(service):
    resource, model = binding()
    service.search.return_value = _response(hits=[hit()])
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[resource])
    service.models.invoke.return_value = ModelResult(revision="v2", output=[{"index": 0, "relevance_score": .95}])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [(resource, model)],
        file_refs=[KnowledgeFileReference(knowledge_id=1, file_id="f" * 32, file_version=0)], native_documents=True)
    assert (await tool.search("query", ["kb-1"], search_mode="semantic", top_k=1,
                             rerank_model=ModelVersion(model_id=4, revision="v2")))[0].score == .95
    request = service.search.await_args.args[0]
    assert request.native_documents and request.include_public_document
    assert request.file_versions == {"f" * 32: 0}
    assert service.verify_data_revisions.await_args.kwargs["native_documents"] is True


@pytest.mark.asyncio
async def test_empty_files_deny_all_and_unknown_collection_is_rejected(service):
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [binding()], file_refs=[])
    assert await tool.search("query", ["kb-1"]) == []
    with pytest.raises(ScopeDenied):
        await tool.search("query", ["kb-foreign"])
    service.search.assert_not_called()
    service.client.authorize_knowledge_search.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.CancelledError, TimeoutError])
async def test_failed_group_is_not_replayed_or_replaced(service, error):
    service.search.side_effect = error()
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [binding()])
    with pytest.raises(DeadlineExceeded if error is TimeoutError else error):
        await tool.search("query", ["kb-1"])
    assert service.search.await_count == 1
    service.models.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_whole_operation_deadline_cancels_final_authorization_and_logs_once(service, caplog):
    from time import monotonic

    from nexent.storage.models import OperationContext

    ended = asyncio.Event()

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    service.search.return_value = _response(hits=[hit()])
    service.client.authorize_knowledge_search.side_effect = hanging
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [binding()])
    with pytest.raises(DeadlineExceeded):
        await tool.search("private-query", ["kb-1"], context=OperationContext("tool-test", monotonic() + .1))
    assert ended.is_set() and service.search.await_count == 1
    assert service.client.authorize_knowledge_search.await_count == 1
    records = [r for r in caplog.records if "knowledge_tool_timeout" in r.message]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "phase=reauthorize" in records[0].message and "private-query" not in caplog.text


@pytest.mark.asyncio
async def test_revocation_before_return_rejects_all_results(service):
    service.search.return_value = _response(hits=[hit()])
    changed = binding()[0].model_copy(update={"revision": "b" * 64})
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[changed])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [binding()])
    with pytest.raises(Conflict):
        await tool.search("query", ["kb-1"])


@pytest.mark.asyncio
async def test_multiple_model_groups_rerank_once_and_reject_stale_model(service):
    bindings = [binding(), binding(2, 3)]
    service.search.side_effect = [_response(hits=[hit()]), _response(hits=[hit(2)])]
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[b[0] for b in bindings])
    service.models.invoke.return_value = ModelResult(revision="v2", output=[{"index": 1, "relevance_score": .99}])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), bindings)
    rows = await tool.search("query", ["kb-1", "kb-2"], rerank_model=ModelVersion(model_id=4, revision="v2"))
    assert [h.knowledge_id for h in rows] == [2]
    assert service.models.invoke.await_count == 1
    assert len(service.models.invoke.await_args.args[0].input.documents) == 2
    service.search.side_effect = None
    service.search.return_value = _response(hits=[hit()])
    service.models.invoke.return_value = ModelResult(revision="changed", output=[])
    with pytest.raises(Conflict):
        await tool.search("query", ["kb-1"], rerank_model=ModelVersion(model_id=4, revision="v2"))


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [hit(2), hit().model_copy(update={"file_id": "a" * 32})])
async def test_out_of_scope_service_result_is_never_returned(service, row):
    service.search.return_value = _response(hits=[row])
    tool = KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), [binding()], file_refs=[KnowledgeFileReference(knowledge_id=1, file_id="f" * 32, file_version=0)])
    with pytest.raises(ScopeDenied):
        await tool.search("query", ["kb-1"])
    service.models.invoke.assert_not_called()


@pytest.mark.parametrize("bindings", [[binding(), binding()], [(binding()[0], ModelVersion(model_id=9, revision="v1"))]])
def test_invalid_binding_rejected_before_io(service, bindings):
    with pytest.raises(ValueError):
        KnowledgeToolSearch(service, SimpleNamespace(user_id="user", tenant_id="tenant"), bindings)
    service.search.assert_not_called()


@pytest.mark.asyncio
async def test_fixed_references_skip_other_model_groups_without_changing_single_group_score(service):
    bindings = [binding(), binding(2, 3)]
    service.search.return_value = _response(hits=[hit()])
    service.client.authorize_knowledge_search.return_value = KnowledgeSearchGrant(knowledge_bases=[b[0] for b in bindings])
    actor = SimpleNamespace(user_id="user", tenant_id="tenant")
    tool = KnowledgeToolSearch(service, actor, bindings, file_refs=[
        KnowledgeFileReference(knowledge_id=1, file_id="f" * 32, file_version=0)])
    rows = await tool.search("query", ["kb-1", "kb-2"])
    assert service.search.await_count == 1 and service.search.await_args.args[0].knowledge_ids == [1]
    assert rows[0].score == .8
    service.search.return_value = _response(hits=[hit().model_copy(update={"file_version": 1})])
    with pytest.raises(ScopeDenied):
        await tool.search("query", ["kb-1"])
