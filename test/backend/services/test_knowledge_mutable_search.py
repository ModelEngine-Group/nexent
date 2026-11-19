# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirmed manual chunks participate in retrieval without stale or invented references."""

from dataclasses import replace

import pytest
from contracts.agentos_knowledge import KnowledgeSearchHit
from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import (
    Revision,
    VectorCollectionInfo,
    WriteOutcome,
)
from pydantic import ValidationError
from runtime.knowledge_base.chunk_journal import ChunkMutationJournal
from runtime.knowledge_base.tool_search import KnowledgeToolSearch

from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle
from test.backend.services.test_knowledge_search import (
    search as search,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_search import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_search import (
    with_rerank,
)


async def change(search, operation, *, standalone=False, index=0, complete=True):
    s, _, grant, hit, _ = search
    intent = ChunkMutationIntent(
        knowledge_id=1,
        chunk_id=hit.key.key,
        request_key=operation,
        operation=operation,
        resource_revision=grant.knowledge_bases[0].revision,
        changes={} if operation == "delete" else {"content": "manual"},
        **(
            {}
            if standalone
            else {
                "file_ref": {
                    "knowledge_id": 1,
                    "file_id": s.request.file_id,
                    "file_version": 0,
                },
                "generation": hit.generation.value,
                "chunk_index": index,
            }
        ),
    )

    def execute():
        records = bind_knowledge_lifecycle(s.records.scope, s.engine, mode="mutation")
        try:
            journal = ChunkMutationJournal(records, 1)
            row, fresh = journal.reserve(intent, context=s.context)
            assert fresh
            if not complete:
                return row
            journal.begin(row["mutation_id"], context=s.context)
            return journal.complete(
                row["mutation_id"],
                count_delta=-1
                if operation == "delete"
                else 1
                if operation == "create"
                else 0,
                outcome=WriteOutcome.CONFIRMED,
                context=s.context,
            )
        finally:
            records.close()

    return await s.db(execute)


def independent(hit, receipt):
    return replace(
        hit,
        generation=Revision(receipt["mutation_id"]),
        payload={
            **hit.payload,
            "file_id": None,
            "file_version": None,
            "chunk_index": None,
            "filename": None,
            "embedding_model_id": None,
            "embedding_revision": None,
        },
    )


async def test_lexical_retrieves_confirmed_standalone_plaintext_without_model_requests(
    search,
):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=True)
    s.vectors.search.return_value = (independent(hit, receipt),)
    result = await service.search(
        request.model_copy(update={"search_mode": "accurate"}), s.actor
    )
    assert len(result.hits) == 1
    assert (
        result.hits[0].file_id is None
        and result.hits[0].file_version is None
        and result.hits[0].filename is None
    )
    s.models.invoke.assert_not_awaited()
    s.models.embedding_dimensions.assert_not_awaited()
    terms = s.vectors.search.call_args.args[1].where.terms
    assert all(term.field != "embedding_model_id" for term in terms)


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
async def test_plaintext_is_excluded_from_semantic_branch_but_kept_in_hybrid_lexical(
    search, mode
):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=True)
    # KNN returns only documents with actual vectors; lexical search can return plaintext.
    s.vectors.search.side_effect = lambda collection, query, **kwargs: (
        () if query.vector is not None else (independent(hit, receipt),))
    result = await service.search(
        request.model_copy(update={"search_mode": mode}), s.actor
    )
    assert len(result.hits) == (1 if mode == "hybrid" else 0)
    if result.hits:
        assert result.hits[0].score_details["semantic"] == 0


@pytest.mark.parametrize("fault", ["orphan", "generation", "deleted"])
async def test_unconfirmed_wrong_generation_and_deleted_standalones_do_not_reach_rerank(
    search, fault
):
    s, request, _, hit, service = search
    receipt = {"mutation_id": "f" * 32}
    if fault != "orphan":
        receipt = await change(search, "create", standalone=True)
    if fault == "deleted":
        # A different request key lets the delete follow the confirmed create.
        await change(search, "delete", standalone=True)
    row = independent(hit, receipt)
    if fault == "generation":
        row = replace(row, generation=Revision("wrong"))
    s.vectors.search.return_value = (row,)
    result = await service.search(
        with_rerank(request).model_copy(update={"search_mode": "accurate"}), s.actor
    )
    assert result.hits == []
    s.models.invoke.assert_not_awaited()


async def test_confirmed_file_deletion_filters_a_lingering_native_record_before_rerank(
    search,
):
    s, request, _, _, service = search
    await change(search, "delete")
    result = await service.search(with_rerank(request), s.actor)
    assert result.hits == []
    assert [call.args[0].operation for call in s.models.invoke.call_args_list] == [
        "embedding"
    ]


@pytest.mark.parametrize("actual", [7, 8])
async def test_file_manual_create_uses_confirmed_sparse_index(search, actual):
    s, request, _, hit, service = search
    await change(search, "create", index=7)
    s.vectors.search.return_value = (
        replace(hit, payload={**hit.payload, "chunk_index": actual, "filename": None}),
    )
    result = await service.search(request, s.actor)
    assert len(result.hits) == (1 if actual == 7 else 0)


async def test_active_mutation_prevents_storage_search(search):
    s, request, _, _, service = search
    await change(search, "update", complete=False)
    with pytest.raises(Conflict):
        await service.search(request, s.actor)
    s.vectors.search.assert_not_called()


async def test_confirmed_update_during_rerank_invalidates_stale_content(search):
    s, request, _, _, service = search
    invoke = s.models.invoke.side_effect

    async def changing(payload, actor):
        if payload.operation == "rerank":
            await change(search, "update")
        return await invoke(payload, actor)

    s.models.invoke.side_effect = changing
    with pytest.raises(Conflict):
        await service.search(with_rerank(request), s.actor)


async def test_plaintext_collection_has_no_dense_branch(search):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=True)
    s.vectors.search.return_value = (independent(hit, receipt),)
    s.vectors.describe_collection.return_value = VectorCollectionInfo(
        "kb", None, "cosine"
    )
    result = await service.search(
        request.model_copy(update={"search_mode": "hybrid"}), s.actor
    )
    assert len(result.hits) == 1 and s.vectors.search.call_count == 1
    assert s.vectors.search.call_args.args[1].mode == "weighted_text"


async def test_wrong_actual_vector_dimensions_are_refused_before_search(search):
    s, request, _, _, service = search
    s.vectors.describe_collection.return_value = VectorCollectionInfo("kb", 3, "cosine")
    with pytest.raises(Conflict):
        await service.search(request, s.actor)
    s.vectors.search.assert_not_called()


async def test_file_restrictions_cannot_admit_an_independent_chunk(search):
    s, request, _, hit, service = search
    receipt = await change(search, "create", standalone=True)
    s.vectors.search.return_value = (independent(hit, receipt),)
    with pytest.raises(ScopeDenied):
        await service.search(
            request.model_copy(
                update={"search_mode": "accurate", "file_ids": [s.request.file_id]}
            ),
            s.actor,
        )


@pytest.mark.parametrize("fields", [{"file_id": "a" * 32}, {"file_version": 1}])
def test_search_hit_contract_refuses_partial_file_reference(fields):
    with pytest.raises(ValidationError):
        KnowledgeSearchHit(
            knowledge_id=1,
            chunk_id="partial",
            content="text",
            score=1,
            score_kind="text",
            **fields,
        )


def test_tool_rank_merge_can_sort_file_and_standalone_identity_ties():
    common = {"knowledge_id": 1, "content": "text", "score": 1, "score_kind": "text"}
    standalone = KnowledgeSearchHit(chunk_id="manual", **common)
    file = KnowledgeSearchHit(
        chunk_id="file", file_id="a" * 32, file_version=0, **common
    )
    result = KnowledgeToolSearch._merge([[file], [standalone]], 2)
    assert [row.chunk_id for row in result] == ["manual", "file"]
