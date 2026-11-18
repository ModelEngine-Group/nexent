# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve capture ownership checks independently of operations query modules."""

from contextlib import contextmanager

import pytest
from contracts.errors.trajectory import QueryError
from management.db.conversation import trajectory_capture as database
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


@pytest.fixture
def catalog(mocker):
    session = Session()
    statements = []

    @contextmanager
    def scoped():
        yield session

    def rows(query):
        statements.append(
            str(
                query.statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        return [(11,), (12,)]

    mocker.patch.object(database, "_session", scoped)
    mocker.patch("sqlalchemy.orm.Query.all", rows)
    try:
        yield database.CaptureCatalog(), statements
    finally:
        session.close()


def test_capture_reads_scalar_messages_with_same_owner_and_tenant_scope(catalog):
    service, statements = catalog
    assert service.source_messages("t", "u", "123", upper="20") == ["11", "12"]
    sql = statements[-1]
    assert "message_content" not in sql
    assert "user_tenant_t.tenant_id IN ('t')" in sql
    assert "conversation_record_t.created_by = 'u'" in sql
    assert "conversation_record_t.conversation_id = 123" in sql
    assert "message_role = 'user'" in sql and "message_id <= 20" in sql
    assert "user_account_t.delete_flag = 'N'" in sql
    assert "user_tenant_t.delete_flag = 'N'" in sql
    assert "conversation_message_t.delete_flag" not in sql
    assert "LIMIT 10001" in sql


@pytest.mark.parametrize("limit", [0, 10001])
def test_capture_rejects_unbounded_source_requests(catalog, limit):
    with pytest.raises(ValueError):
        catalog[0].source_messages("t", "u", "123", limit=limit)
    assert catalog[1] == []


def test_capture_source_budget_failure_stays_retryable(catalog):
    with pytest.raises(QueryError) as error:
        catalog[0].source_messages("t", "u", "123", limit=1)
    assert error.value.code == "source_coverage_budget_exceeded"
    assert error.value.status == 503 and error.value.retry_after == 2


def test_deleted_conversation_check_is_owner_scoped_and_propagates_database_failure(
    catalog, mocker
):
    service, _ = catalog
    first = mocker.patch("sqlalchemy.orm.Query.first", return_value=None)
    assert service.conversation_deleted("123", "u") is True
    first.return_value = (123,)
    assert service.conversation_deleted("123", "u") is False
    first.side_effect = OSError("controlled database error")
    with pytest.raises(OSError, match="controlled"):
        service.conversation_deleted("123", "u")
