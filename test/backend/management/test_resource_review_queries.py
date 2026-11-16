# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorized review SQL keeps search, pagination and locking scopes intact."""

from unittest.mock import MagicMock

import pytest
from contracts.review import ReviewListQuery
from management.db import repository_reviews as queries
from sqlalchemy.dialects import postgresql


def compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


@pytest.mark.parametrize("filtered", [True, False])
def test_list_counts_and_pages_share_authorized_filters(filtered):
    session = MagicMock()
    session.scalar.return_value = 31 if filtered else None
    session.scalars.return_value.all.return_value = ["row"] if filtered else []
    query = (
        ReviewListQuery(type="skill", status="rejected", search="100%_match", page=3, page_size=10)
        if filtered
        else ReviewListQuery()
    )
    rows, total = queries.list_reviews(session, "user", "tenant", "DEV", query)
    count = compiled(session.scalar.call_args.args[0])
    page = compiled(session.scalars.call_args.args[0])
    for statement in (count, page):
        values = list(statement.params.values())
        assert "tenant" in values and "user" in values
        assert "delete_flag" in str(statement)
        if filtered:
            assert "rejected" in values
            assert any(isinstance(value, str) and "/%" in value and "/_" in value for value in values)
            assert "resource_snapshot" in str(statement)
    assert total == (31 if filtered else 0)
    assert rows == (["row"] if filtered else [])
    assert "submitted_at DESC" in str(page) and "review_id DESC" in str(page)
    if filtered:
        assert 20 in page.params.values() and 10 in page.params.values()


@pytest.mark.parametrize("lock", [True, False])
def test_get_scopes_bigint_identity_and_optional_lock(lock):
    session = MagicMock()
    session.scalar.return_value = "visible"
    assert queries.get_review(session, 9007199254740993, "u", "t", "DEV", for_update=lock) == "visible"
    statement = session.scalar.call_args.args[0]
    sql = compiled(statement)
    assert 9007199254740993 in sql.params.values()
    assert "u" in sql.params.values() and "t" in sql.params.values()
    assert ("FOR UPDATE" in str(sql)) is lock
    assert statement.get_execution_options().get("populate_existing", False) is lock
