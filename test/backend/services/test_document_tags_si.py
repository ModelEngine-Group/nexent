# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOCUMENT-TAGS-01 preserve display rules through real RecordStore."""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.constants.constants import PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS
from management.services.tag.document_projection import DocumentTagProjection
from management.services.tag.identity import _encode_document_resource_id
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.document_tag_records import TABLES, bind_document_tag_records


def resource(path):
    return _encode_document_resource_id("local", "kb", path)


@pytest.fixture
def tags():
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
        execution_options={"schema_translate_map": {"nexent": None}},
    )
    for table in TABLES.values():
        table.create(engine)
    actor = ServicePrincipal("reader", "tenant-a")
    opened, closed, queries = [], [], []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        records = bind_document_tag_records(principal, engine)
        original = records.query

        def query(dataset, request, page, *, context):
            queries.append((dataset, request, page))
            return original(dataset, request, page, context=context)

        records.query = query
        opened.append(records)
        try:
            yield records
        finally:
            records.close()
            closed.append(True)

    with engine.begin() as conn:
        conn.execute(
            TABLES["knowledge"].insert(),
            [
                {
                    "knowledge_id": 1,
                    "tenant_id": "tenant-a",
                    "index_name": "kb",
                    "delete_flag": "N",
                },
                {
                    "knowledge_id": 2,
                    "tenant_id": "owner",
                    "index_name": "shared",
                    "delete_flag": "N",
                },
            ],
        )
        conn.execute(
            TABLES["bucket"].insert(),
            [
                {
                    "bucket_id": 1,
                    "tenant_id": "tenant-a",
                    "bucket_key": "knowledge_content",
                    "status": "active",
                    "delete_flag": "N",
                },
                {
                    "bucket_id": 2,
                    "tenant_id": "other",
                    "bucket_key": "knowledge_content",
                    "status": "active",
                    "delete_flag": "N",
                },
            ],
        )
        conn.execute(
            TABLES["binding"].insert(),
            {
                "bucket_resource_type_id": 1,
                "tenant_id": "tenant-a",
                "bucket_id": 1,
                "resource_type": "knowledge_document",
                "status": "active",
                "delete_flag": "N",
            },
        )
        conn.execute(
            TABLES["definition"].insert(),
            [
                {
                    "definition_id": 1,
                    "tenant_id": "tenant-a",
                    "definition_key": "domain",
                    "definition_name": "Domain",
                    "selection_mode": "multi_select",
                    "sort_order": 2,
                    "status": "disabled",
                    "delete_flag": "Y",
                },
                {
                    "definition_id": 2,
                    "tenant_id": "other",
                    "definition_key": "secret",
                    "definition_name": "Secret",
                    "selection_mode": "single_select",
                    "sort_order": 1,
                    "status": "active",
                    "delete_flag": "N",
                },
            ],
        )
        conn.execute(
            TABLES["value"].insert(),
            [
                {
                    "value_id": 1,
                    "tenant_id": "tenant-a",
                    "definition_id": 1,
                    "display_value": "Second",
                    "status": "active",
                    "sort_order": 2,
                    "delete_flag": "N",
                },
                {
                    "value_id": 2,
                    "tenant_id": "tenant-a",
                    "definition_id": 1,
                    "display_value": "First",
                    "status": "disabled",
                    "sort_order": 1,
                    "delete_flag": "Y",
                },
                {
                    "value_id": 3,
                    "tenant_id": "other",
                    "definition_id": 2,
                    "display_value": "Secret",
                    "status": "active",
                    "sort_order": 1,
                    "delete_flag": "N",
                },
            ],
        )
        conn.execute(
            TABLES["assignment"].insert(),
            [
                {
                    "assignment_id": i,
                    "tenant_id": tenant,
                    "definition_id": definition,
                    "value_id": value,
                    "resource_type": "knowledge_document",
                    "resource_id": resource("a"),
                    "delete_flag": deleted,
                }
                for i, tenant, definition, value, deleted in [
                    (1, "tenant-a", 1, 1, "N"),
                    (2, "tenant-a", 1, 2, "N"),
                    (3, "other", 2, 3, "N"),
                    (4, "tenant-a", 1, 1, "Y"),
                    (5, "tenant-a", 2, 3, "N"),
                ]
            ],
        )
    service = DocumentTagProjection(ports=ports)
    context = OperationContext("document-tags-unit", monotonic() + 20)
    try:
        yield SimpleNamespace(**locals())
    finally:
        engine.dispose()


def test_original_sort_public_fields_and_deleted_value_semantics(tags):
    s = tags
    files = [
        {"path_or_url": " a ", "file": "one"},
        {"path_or_url": "a"},
        {"file": "no-path"},
    ]
    result = s.service.project(files, "kb", s.actor, context=s.context)
    assert [tag["display_value"] for tag in result[0]["tags"]] == ["First", "Second"]
    assert result[0]["tags"][0]["value_status"] == "disabled"
    assert set(result[0]["tags"][0]) == set(PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS)
    assert result[1]["tags"] == result[0]["tags"] and result[2]["tags"] == []
    assert files == [
        {"path_or_url": " a ", "file": "one"},
        {"path_or_url": "a"},
        {"file": "no-path"},
    ]
    assert len(s.opened) == 1 and s.closed == [True]
    assert (
        s.opened[0].scope.actor_id,
        s.opened[0].scope.tenant_id,
        s.opened[0].scope.system,
    ) == ("reader", "tenant-a", False)


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("bucket", "status", "disabled"),
        ("bucket", "delete_flag", "Y"),
        ("bucket", "bucket_key", "other-library"),
        ("binding", "status", "disabled"),
        ("binding", "delete_flag", "Y"),
        ("binding", "resource_type", "agent"),
    ],
)
def test_inactive_or_wrong_library_binding_keeps_tags_empty(tags, table, field, value):
    s = tags
    with s.engine.begin() as conn:
        conn.execute(TABLES[table].update().values({field: value}))
    assert (
        s.service.project([{"path_or_url": "a"}], "kb", s.actor, context=s.context)[0][
            "tags"
        ]
        == []
    )
    assert len(s.closed) == 1


def test_shared_resource_does_not_expose_owner_tags(tags):
    s = tags
    result = s.service.project(
        [{"path_or_url": "a"}], "shared", s.actor, context=s.context
    )
    assert result == [{"path_or_url": "a", "tags": []}]
    assert len(s.queries) == 1


def test_definition_order_precedes_value_order_and_deleted_assignment_is_hidden(tags):
    s = tags
    with s.engine.begin() as conn:
        conn.execute(
            TABLES["definition"].insert(),
            {
                "definition_id": 3,
                "tenant_id": "tenant-a",
                "definition_key": "category",
                "definition_name": "Category",
                "selection_mode": "single_select",
                "sort_order": 1,
                "status": "active",
                "delete_flag": "N",
            },
        )
        conn.execute(
            TABLES["value"].insert(),
            {
                "value_id": 5,
                "tenant_id": "tenant-a",
                "definition_id": 3,
                "display_value": "Earlier definition",
                "status": "active",
                "sort_order": 99,
                "delete_flag": "N",
            },
        )
        conn.execute(
            TABLES["assignment"].insert(),
            {
                "assignment_id": 9,
                "tenant_id": "tenant-a",
                "definition_id": 3,
                "value_id": 5,
                "resource_type": "knowledge_document",
                "resource_id": resource("a"),
                "delete_flag": "N",
            },
        )
    result = s.service.project([{"path_or_url": "a"}], "kb", s.actor, context=s.context)
    assert [tag["display_value"] for tag in result[0]["tags"]] == [
        "Earlier definition",
        "First",
        "Second",
    ]


def test_storage_failure_does_not_return_partial_tags_or_retry(tags, caplog):
    from nexent.storage.errors import Unavailable

    s = tags
    calls = []

    @contextmanager
    def fail(principal, *, context):
        calls.append(principal)
        raise Unavailable()
        yield

    files = [{"path_or_url": "a", "chunk_count": 9}]
    assert DocumentTagProjection(ports=fail).project(
        files, "kb", s.actor, context=s.context
    ) == [dict(files[0], tags=[])]
    assert calls == [s.actor]
    assert (
        sum("document_tag_projection_unavailable" in r.message for r in caplog.records)
        == 1
    )


def test_si_document_datasets_are_read_only(tags):
    from nexent.storage.errors import ScopeDenied
    from nexent.storage.models import FieldPatch

    from infrastructure.rdb.document_tag_records import KNOWLEDGE

    s = tags
    records = bind_document_tag_records(s.actor, s.engine)
    try:
        with pytest.raises(ScopeDenied):
            records.patch(
                KNOWLEDGE,
                1,
                FieldPatch(set_values={"index_name": "forbidden"}),
                expected=None,
                context=s.context,
            )
    finally:
        records.close()
    with s.engine.connect() as conn:
        assert (
            conn.execute(
                sa.select(TABLES["knowledge"].c.index_name).where(
                    TABLES["knowledge"].c.knowledge_id == 1
                )
            ).scalar_one()
            == "kb"
        )


@pytest.mark.parametrize("files", [[], [{"file": "no-path"}]])
def test_empty_paths_never_open_storage(tags, files):
    s = tags
    assert s.service.project(files, "kb", s.actor, context=s.context) == [
        dict(f, tags=[]) for f in files
    ]
    assert not s.opened


def test_501_ids_are_batched_and_multiple_assignment_pages_are_not_truncated(tags):
    s = tags
    with s.engine.begin() as conn:
        conn.execute(
            TABLES["value"].insert(),
            {
                "value_id": 4,
                "tenant_id": "tenant-a",
                "definition_id": 1,
                "display_value": "Third",
                "status": "active",
                "sort_order": 3,
                "delete_flag": "N",
            },
        )
        conn.execute(
            TABLES["assignment"].insert(),
            [
                {
                    "assignment_id": 1000 + i,
                    "tenant_id": "tenant-a",
                    "definition_id": 1,
                    "value_id": 1,
                    "resource_type": "knowledge_document",
                    "resource_id": resource(str(i)),
                    "delete_flag": "N",
                }
                for i in range(501)
            ],
        )
        conn.execute(
            TABLES["assignment"].insert(),
            [
                {
                    "assignment_id": 2000 + i,
                    "tenant_id": "tenant-a",
                    "definition_id": 1,
                    "value_id": 2,
                    "resource_type": "knowledge_document",
                    "resource_id": resource(str(i)),
                    "delete_flag": "N",
                }
                for i in range(501)
            ],
        )
        conn.execute(
            TABLES["assignment"].insert(),
            [
                {
                    "assignment_id": 3000 + i,
                    "tenant_id": "tenant-a",
                    "definition_id": 1,
                    "value_id": 4,
                    "resource_type": "knowledge_document",
                    "resource_id": resource(str(i)),
                    "delete_flag": "N",
                }
                for i in range(501)
            ],
        )
    files = [{"path_or_url": str(i)} for i in range(501)]
    result = s.service.project(files, "kb", s.actor, context=s.context)
    assert len(result) == 501 and all(
        [tag["display_value"] for tag in row["tags"]] == ["First", "Second", "Third"]
        for row in result
    )
    from infrastructure.rdb.document_tag_records import ASSIGNMENTS

    reads = [
        (query, page) for dataset, query, page in s.queries if dataset == ASSIGNMENTS
    ]
    assert len(reads) == 3 and reads[1][1].cursor is not None
    assert reads[2][1].cursor is None
