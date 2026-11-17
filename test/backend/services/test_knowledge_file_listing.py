# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-LIST-01: current-reader pages and deletion preconditions."""

import pytest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_file_reader import reader  # noqa: F401


def test_current_reader_lists_own_kb_including_tombstones(reader):  # noqa: F811
    with reader.engine.begin() as connection:
        connection.execute(reader.table.update().values(status="DELETE_REQUESTED"))
    rows = reader.service.files("kb-one", reader.actor, context=context())
    assert len(rows) == 1 and rows[0]["status"] == "DELETE_REQUESTED"
    assert rows[0]["knowledge_id"] == 1
    assert reader.opened == [("tenant-a", "user-a")]


def test_current_reader_lists_only_shared_asset_rows(reader):  # noqa: F811
    rows = reader.service.files("shared", reader.actor, context=context())
    assert len(rows) == 1 and rows[0]["knowledge_id"] == 2
    assert reader.opened == [(ASSET_OWNER_TENANT_ID, "user-a")]


def test_revoked_reader_cannot_list_or_open_lifecycle_handle(reader):  # noqa: F811
    reader.update("cleanse_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        reader.service.files("kb-one", reader.actor, context=context())
    assert reader.opened == []


def test_reader_consumes_all_si_pages_without_cross_kb_rows(reader):  # noqa: F811
    with reader.engine.begin() as connection:
        connection.execute(reader.table.insert(), [{
            "file_id": f"{i:032x}", "tenant_id": "tenant-a", "knowledge_id": 1,
            "index_name": "kb-one", "original_filename": f"{i}.txt",
            "object_name": f"knowledge/{i}.txt", "status": "UPLOADED", "delete_flag": "N",
        } for i in range(1000)])
    rows = reader.service.files("kb-one", reader.actor, context=context())
    assert len(rows) == 1001 and len({row["file_id"] for row in rows}) == 1001
    assert {row["knowledge_id"] for row in rows} == {1}
    assert reader.opened == [("tenant-a", "user-a")]
