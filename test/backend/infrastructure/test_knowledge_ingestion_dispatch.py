# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only admitted pending ingestion exposes minimal cross-tenant scheduling identities."""

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery, Sort

from infrastructure.rdb.knowledge_ingestion_dispatch import (
    DATASET,
    bind_ingestion_dispatch,
)
from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_contract import intent


def test_discovery_is_minimal_read_only_and_preserves_original_actor(records):  # noqa: F811
    _, engine, table = records
    value = intent()
    with engine.begin() as conn:
        conn.execute(
            table.update().values(
                ingestion_request=value.model_dump(mode="json"), stage="INGEST_ACCEPTED"
            )
        )
    discover = bind_ingestion_dispatch(engine)
    try:
        page = discover.query(DATASET, RecordQuery(), PageRequest(), context=context())
        assert len(page.items) == 1
        row = page.items[0]
        assert row["file_id"] == value.file_id and row["tenant_id"] == "tenant-a"
        assert row["user_id"] == "user-a"
        assert set(row) == {
            "file_id",
            "tenant_id",
            "user_id",
            "create_time",
            "update_time",
            "created_by",
            "updated_by",
            "delete_flag",
        }
        with pytest.raises(InvalidInput):
            discover.query(
                DATASET,
                RecordQuery(fields=("ingestion_request",)),
                PageRequest(),
                context=context(),
            )
        with pytest.raises(ScopeDenied):
            discover.patch(
                DATASET,
                value.file_id,
                FieldPatch(set_values={"user_id": "foreign"}),
                context=context(),
            )
    finally:
        discover.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"ingestion_request": None},
        {"delete_flag": "Y"},
        {"status": "FAILED", "stage": "FAILED"},
        {"status": "COMPLETED", "stage": "COMPLETE"},
        {"status": "DELETE_REQUESTED"},
        {"status": "UPLOADING"},
        {"stage": "PROCESS"},
    ],
)
def test_discovery_excludes_unadmitted_terminal_deleted_and_legacy_stages(
    records, changes  # noqa: F811
):
    _, engine, table = records
    values = {
        "ingestion_request": intent().model_dump(mode="json"),
        "stage": "INGEST_ACCEPTED",
        **changes,
    }
    with engine.begin() as conn:
        conn.execute(table.update().values(**values))
    discover = bind_ingestion_dispatch(engine)
    try:
        assert not discover.query(
            DATASET, RecordQuery(), PageRequest(), context=context()
        ).items
    finally:
        discover.close()


def test_pending_pages_reach_other_tenants_without_mutating_old_pending_rows(records):  # noqa: F811
    _, engine, table = records
    with engine.begin() as conn:
        template = dict(conn.execute(table.select()).mappings().one())
        conn.execute(table.delete())
        for number in range(105):
            file_id = format(number, "032x")
            actor = "user-a" if number < 100 else "user-b"
            value = intent(file_id=file_id, user_id=actor)
            conn.execute(
                table.insert().values(
                    **{
                        **template,
                        "file_id": file_id,
                        "tenant_id": "tenant-a" if number < 100 else "tenant-b",
                        "ingestion_request": value.model_dump(mode="json"),
                        "stage": "CLEANSE_PENDING",
                        "status": "PROCESSING",
                    }
                )
            )
    discover = bind_ingestion_dispatch(engine)
    try:
        query = RecordQuery(order_by=(Sort("file_id"),))
        first = discover.query(
            DATASET, query, PageRequest(limit=100), context=context()
        )
        assert len(first.items) == 100 and first.next_cursor
        second = discover.query(
            DATASET,
            query,
            PageRequest(limit=100, cursor=first.next_cursor),
            context=context(),
        )
        assert len(second.items) == 5 and second.next_cursor is None
        assert {row["tenant_id"] for row in second.items} == {"tenant-b"}
        assert {row["user_id"] for row in second.items} == {"user-b"}
    finally:
        discover.close()
