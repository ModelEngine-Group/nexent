# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Sampling shares confirmed chunk visibility and retains real optional vectors."""

from dataclasses import replace

import pytest
from contracts.agentos_knowledge import ModelVersion
from nexent.storage.errors import Conflict
from nexent.storage.models import Page, Revision, VectorKey, VectorRecord
from runtime.knowledge_base.sample import _sample_documents

from test.backend.services.test_knowledge_chunk_view import (
    context,
)
from test.backend.services.test_knowledge_chunk_view import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_view import (
    view as view,  # noqa: PLC0414
)


@pytest.fixture
def sample_view(view):
    s = view
    s.rows[:] = [replace(row, vector=(1.0, 0.0)) for row in s.rows]

    def match(where, row):
        if hasattr(where, "terms"):
            return all(match(term, row) for term in where.terms)
        value = row.payload.get(where.field)
        if where.operator == "eq":
            return value == where.value
        if where.operator == "is_null":
            return (value is None) == where.value
        if where.operator == "gte":
            return value is not None and value >= where.value
        if where.operator == "lt":
            return value is not None and value < where.value
        raise AssertionError(where)

    s.vectors.scan.side_effect = lambda collection, where, *args, **kwargs: Page(
        tuple(row for row in s.rows if match(where, row))
    )
    s.sample = lambda limit=200: _sample_documents(
        s.s.record,
        s.vectors,
        s.resource,
        ModelVersion(model_id=2, revision="r1"),
        limit,
        context=context(),
    )
    return s


def standalone(s, key, path=None, vector=()):
    receipt = s.mutate("create", key, None, 1, standalone=True)
    s.rows.append(
        VectorRecord(
            VectorKey("collection", key),
            vector,
            {
                "knowledge_id": 1,
                "file_id": None,
                "file_version": None,
                "chunk_index": None,
                "content": key,
                "filename": None,
                "location": {"path_or_url": path} if path else {},
                "embedding_model_id": 2 if vector else None,
                "embedding_revision": "r1" if vector else None,
            },
            Revision(receipt["mutation_id"]),
        )
    )


def test_sample_keeps_sparse_and_repeated_display_indices_with_real_chunk_ids(
    sample_view,
):
    s = sample_view
    s.mutate("delete", "base1", 1, -1)
    s.rows.pop(1)
    s.mutate("create", "manual", 2, 1)
    s.rows.append(
        replace(
            s.rows[-1],
            key=VectorKey("collection", "manual"),
            vector=(),
            payload={
                **s.rows[-1].payload,
                "content": "plain manual",
                "filename": None,
                "embedding_model_id": None,
                "embedding_revision": None,
            },
        )
    )
    document = s.sample()[0]
    assert [row.chunk_index for row in document.chunks] == [0, 2, 2]
    assert [row.chunk_id for row in document.chunks] == ["base0", "base2", "manual"]
    assert document.chunks[-1].embedding is None and document.chunks[0].embedding == [
        1.0,
        0.0,
    ]
    assert s.vectors.scan.call_args.kwargs["allow_missing_vector"] is True


def test_sample_groups_independent_chunks_by_real_path_without_fake_files(sample_view):
    s = sample_view
    standalone(s, "independent-a", "source/path")
    standalone(s, "independent-b", "source/path", (0.0, 1.0))
    standalone(s, "no-path")
    documents = s.sample()
    independent = [doc for doc in documents if doc.file_ref is None]
    assert len(documents) == 3 and len(independent) == 2
    grouped = next(doc for doc in independent if doc.path_or_url == "source/path")
    assert grouped.filename is None and len(grouped.standalone_key) == 64
    assert [row.chunk_id for row in grouped.chunks] == [
        "independent-a",
        "independent-b",
    ]
    assert all(row.chunk_index is None for row in grouped.chunks)
    assert grouped.chunks[0].embedding is None and grouped.chunks[1].embedding == [
        0.0,
        1.0,
    ]


def test_file_and_independent_groups_share_the_total_sample_limit(sample_view):
    s = sample_view
    for i in range(5):
        standalone(s, f"key-{i}", f"path-{i}")
    assert len(s.sample(2)) == 2


def test_new_plaintext_cannot_hide_missing_original_from_sample(sample_view):
    s = sample_view
    s.mutate("create", "manual", 9, 1)
    s.rows[1] = replace(
        s.rows[1],
        key=VectorKey("collection", "manual"),
        payload={**s.rows[1].payload, "chunk_index": 9},
    )
    with pytest.raises(Conflict):
        s.sample()


def test_existing_model_tag_with_missing_vector_is_not_plaintext(sample_view):
    s = sample_view
    s.rows[0] = replace(s.rows[0], vector=())
    with pytest.raises(Conflict):
        s.sample()


def test_sample_refuses_unconfirmed_independent_generation(sample_view):
    s = sample_view
    standalone(s, "independent")
    s.rows[-1] = replace(s.rows[-1], generation=Revision("wrong"))
    with pytest.raises(Conflict):
        s.sample()


def test_sample_refuses_a_completed_mutation_during_scan(sample_view):
    s = sample_view
    original = s.vectors.scan.side_effect

    def changing(*args, **kwargs):
        s.mutate("update", "base1", 1, 0)
        return original(*args, **kwargs)

    s.vectors.scan.side_effect = changing
    with pytest.raises(Conflict):
        s.sample()


@pytest.mark.parametrize(
    "source",
    [
        {},
        {
            "file_ref": {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 0},
            "standalone_key": "a" * 64,
        },
    ],
)
def test_sample_document_requires_exactly_one_real_source(source):
    from contracts.agentos_knowledge import KnowledgeSampleDocument
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KnowledgeSampleDocument(filename=None, chunks=[], **source)
