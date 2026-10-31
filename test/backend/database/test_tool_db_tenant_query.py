# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

from management.db.tool import repository as tool_db


def test_query_tenant_tools_by_ids_empty_list_skips_database(monkeypatch):
    get_db_session = MagicMock(
        side_effect=AssertionError("Empty tool IDs must not open a database session")
    )
    monkeypatch.setattr(tool_db, "get_db_session", get_db_session)

    assert tool_db.query_tenant_tools_by_ids("tenant-a", []) == []

    get_db_session.assert_not_called()
