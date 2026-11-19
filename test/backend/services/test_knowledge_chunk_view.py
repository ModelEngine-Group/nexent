# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirmed mutation history explains sparse windows without masking missing or orphaned records."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeChunksGrant
from contracts.knowledge_chunk_mutation import CHANGES, ChunkMutationIntent
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import (
    FieldPatch,
    Page,
    PageRequest,
    RecordQuery,
    Revision,
    VectorKey,
    VectorRecord,
    WriteOutcome,
)
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.data_revision import knowledge_data_revision

from infrastructure.rdb.knowledge_jobs import FILES, JOBS
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle
from test.backend.services.test_knowledge_chunk_fencing import (
    context,
    publish,
)
from test.backend.services.test_knowledge_chunk_fencing import (
    lifecycle as lifecycle,  # noqa: PLC0414
)


@pytest.fixture
def view(lifecycle):
    s = lifecycle
    handle = publish(s)
    manifest = s.record.query(
        FILES, RecordQuery(), PageRequest(), context=context()
    ).items[0]
    job = s.record.get(JOBS, handle["job_id"], context=context())
    resource = KnowledgeChunksGrant(
        knowledge_id=1,
        collection="collection",
        resource_tenant_id=s.actor.tenant_id,
        revision="a" * 64,
    )
    rows = [
        VectorRecord(
            VectorKey("collection", f"base{index}"),
            (),
            {
                "knowledge_id": 1,
                "file_id": handle["file_id"],
                "file_version": 1,
                "chunk_index": index,
                "content": f"body{index}",
                "filename": "file.txt",
                "location": {},
                "embedding_model_id": 2,
                "embedding_revision": "r1",
            },
            Revision(handle["attempt_id"]),
        )
        for index in range(3)
    ]
    vectors = Mock()
    vectors.scan.side_effect = lambda *args, **kwargs: Page(tuple(rows))

    def mutate(operation, key, index, delta, *, standalone=False):
        values = {
            "knowledge_id": 1,
            "chunk_id": key,
            "request_key": operation
            + key
            + str(s.record.count(CHANGES, RecordQuery(), context=context())),
            "operation": operation,
            "resource_revision": "a" * 64,
            "changes": {} if operation == "delete" else {"content": "changed"},
        }
        if not standalone:
            values.update(
                file_ref={
                    "knowledge_id": 1,
                    "file_id": handle["file_id"],
                    "file_version": 1,
                },
                generation=handle["attempt_id"],
                chunk_index=index,
            )
        value = ChunkMutationIntent(**values)
        row, fresh = s.mutation.reserve(value, context=context())
        assert fresh and s.mutation.begin(row["mutation_id"], context=context())[1]
        return s.mutation.complete(
            row["mutation_id"],
            count_delta=delta,
            outcome=WriteOutcome.CONFIRMED,
            context=context(),
        )

    def reader():
        return ChunkReadView(s.record, 1, context=context())

    def file_window(start=0, end=None):
        current = reader()
        count = current.file_count(manifest, job, context=context())
        return current.file_window(
            vectors,
            resource,
            manifest,
            job,
            start,
            count if end is None else end,
            context=context(),
        )

    return SimpleNamespace(**locals())


def test_confirmed_deletion_explains_a_gap_and_window_uses_position_not_index(view):
    s = view
    s.mutate("delete", "base1", 1, -1)
    s.rows.pop(1)
    assert s.reader().file_count(s.manifest, s.job, context=context()) == 2
    assert [row.chunk_index for row in s.file_window()] == [0, 2]
    assert [row.chunk_id for row in s.file_window(1, 2)] == ["base2"]


def test_confirmed_create_allows_sparse_or_repeated_display_index_and_null_filename(
    view,
):
    s = view
    s.mutate("create", "manual", 1, 1)
    s.rows.append(
        replace(
            s.rows[1],
            key=VectorKey("collection", "manual"),
            payload={**s.rows[1].payload, "filename": None},
        )
    )
    assert [row.chunk_id for row in s.file_window()] == [
        "base0",
        "base1",
        "manual",
        "base2",
    ]
    assert s.file_window()[2].filename is None


def test_unaccounted_missing_original_is_not_hidden_by_new_manual_record(view):
    s = view
    s.mutate("create", "manual", 9, 1)
    s.rows[1] = replace(
        s.rows[1],
        key=VectorKey("collection", "manual"),
        payload={**s.rows[1].payload, "chunk_index": 9},
    )
    with pytest.raises(Conflict):
        s.file_window()


def test_deleted_record_cannot_be_kept_by_losing_another_record(view):
    s = view
    s.mutate("delete", "base1", 1, -1)
    s.rows.pop(2)
    with pytest.raises(Conflict):
        s.file_window()


def test_updated_key_cannot_be_replaced_by_an_untracked_key_at_the_same_index(view):
    s = view
    s.mutate("update", "base1", 1, 0)
    s.rows[1] = replace(s.rows[1], key=VectorKey("collection", "orphan"))
    with pytest.raises(Conflict):
        s.file_window()


def test_delete_and_recreate_same_logical_key_has_latest_payload_and_correct_count(
    view,
):
    s = view
    s.mutate("delete", "base1", 1, -1)
    s.mutate("create", "base1", 7, 1)
    s.rows[1] = replace(
        s.rows[1],
        payload={**s.rows[1].payload, "chunk_index": 7, "content": "recreated"},
    )
    assert [row.chunk_index for row in s.file_window()] == [0, 2, 7]
    assert s.file_window()[-1].content == "recreated"


def test_standalone_needs_a_confirmed_create_generation_and_has_no_file_reference(view):
    s = view
    receipt = s.mutate("create", "independent", None, 1, standalone=True)
    s.rows[:] = [
        VectorRecord(
            VectorKey("collection", "independent"),
            (),
            {
                "knowledge_id": 1,
                "file_id": None,
                "file_version": None,
                "chunk_index": None,
                "content": "standalone",
                "filename": None,
                "location": {},
            },
            Revision(receipt["mutation_id"]),
        )
    ]
    current = s.reader()
    assert current.standalone_count(context=context()) == 1
    row = current.standalone_window(s.vectors, s.resource, 0, 1, context=context())[0]
    assert row.file_id is None and row.file_version is None and row.chunk_index is None
    assert row.filename is None and row.content == "standalone"


@pytest.mark.parametrize("fault", ["orphan", "missing", "generation", "partial-file"])
def test_standalone_orphans_missing_rows_and_wrong_generation_are_refused(view, fault):
    s = view
    receipt = s.mutate("create", "independent", None, 1, standalone=True)
    data = {
        "knowledge_id": 1,
        "file_id": None,
        "file_version": None,
        "chunk_index": None,
        "content": "standalone",
        "filename": None,
        "location": {},
    }
    key = "other" if fault == "orphan" else "independent"
    if fault == "partial-file":
        data["file_version"] = 1
    s.rows[:] = (
        []
        if fault == "missing"
        else [
            VectorRecord(
                VectorKey("collection", key),
                (),
                data,
                Revision("wrong" if fault == "generation" else receipt["mutation_id"]),
            )
        ]
    )
    with pytest.raises((Conflict, ScopeDenied)):
        s.reader().standalone_window(s.vectors, s.resource, 0, 1, context=context())


def test_epoch_changes_snapshot_even_without_any_manifest_change(view):
    s = view
    before = knowledge_data_revision(s.s.record, 1, context=context())
    s.mutate("update", "base1", 1, 0)
    after = knowledge_data_revision(s.s.record, 1, context=context())
    assert before != after


def test_active_mutation_prevents_a_stable_snapshot(view):
    s = view
    value = ChunkMutationIntent(
        knowledge_id=1,
        chunk_id="pending",
        request_key="pending",
        operation="create",
        resource_revision="a" * 64,
        changes={"content": "pending"},
    )
    s.s.mutation.reserve(value, context=context())
    with pytest.raises(Conflict):
        knowledge_data_revision(s.s.record, 1, context=context())


def test_read_binding_projects_only_selected_kb_and_refuses_writes(view):
    s = view
    records = bind_knowledge_lifecycle(
        s.s.scope, s.s.engine, mode="read", knowledge_ids=(2,)
    )
    try:
        assert not records.query(
            FILES, RecordQuery(), PageRequest(), context=context()
        ).items
        with pytest.raises(ScopeDenied):
            records.patch(
                FILES,
                s.manifest["record_id"],
                FieldPatch(set_values={}),
                context=context(),
            )
    finally:
        records.close()


def test_private_path_selector_keeps_standalone_content_without_fake_file_ids(view):
    from contracts.agentos_knowledge import KnowledgeChunks
    from runtime.knowledge_base.chunks import _window

    s = view
    rows = []
    for key, path in (("alpha", "manual/source"), ("beta", "other/source")):
        receipt = s.mutate("create", key, None, 1, standalone=True)
        rows.append(
            VectorRecord(
                VectorKey("collection", key),
                (),
                {
                    "knowledge_id": 1,
                    "file_id": None,
                    "file_version": None,
                    "chunk_index": None,
                    "content": key,
                    "filename": None,
                    "location": {"path_or_url": path},
                },
                Revision(receipt["mutation_id"]),
            )
        )
    def scoped_scan(collection, where, page, **kwargs):
        file_term = next(term for term in where.terms if term.field == "file_id")
        return Page(tuple(rows if file_term.operator == "is_null" else s.rows))

    s.vectors.scan.side_effect = scoped_scan
    request = KnowledgeChunks(
        knowledge_id=1,
        expected_revision="a" * 64,
        file_ids=[],
        standalone_path="manual/source",
    )
    total, result = _window(
        s.s.record, s.vectors, request, s.resource, context=context()
    )
    assert total == 1 and [row.chunk_id for row in result] == ["alpha"]


def test_completed_mutation_during_vector_scan_invalidates_the_whole_window(view):
    s = view
    current = s.reader()

    def scan(*args, **kwargs):
        s.mutate("update", "base1", 1, 0)
        return Page(tuple(s.rows))

    s.vectors.scan.side_effect = scan
    with pytest.raises(Conflict):
        current.file_window(
            s.vectors, s.resource, s.manifest, s.job, 0, 3, context=context()
        )


@pytest.mark.parametrize("ids", [None, (), (True,), (0,), (-1,), (1, 1), ([],), ("1",)])
def test_read_binding_requires_explicit_distinct_positive_knowledge_ids(view, ids):
    from nexent.storage.errors import InvalidInput

    with pytest.raises(InvalidInput):
        bind_knowledge_lifecycle(
            view.s.scope, view.s.engine, mode="read", knowledge_ids=ids
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"file_id": "a" * 32},
        {"file_version": 1},
        {"chunk_index": 0},
        {"file_id": "a" * 32, "file_version": 1},
    ],
)
def test_chunk_contract_refuses_partial_file_identity(fields):
    from contracts.agentos_knowledge import KnowledgeChunk
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KnowledgeChunk(knowledge_id=1, chunk_id="partial", content="body", **fields)
