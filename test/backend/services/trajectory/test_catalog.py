# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile real catalog queries while isolating the database execution boundary."""

from contextlib import contextmanager

import pytest
from management.db.conversation.trajectory_catalog import TrajectoryCatalog
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


@pytest.fixture
def catalog(mocker):
    sql = []
    session = Session()

    @contextmanager
    def scoped():
        yield session

    def empty(query):
        sql.append(
            str(
                query.statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return []

    mocker.patch("management.db.conversation.trajectory_catalog._session", scoped)
    mocker.patch("sqlalchemy.orm.Query.all", empty)
    yield TrajectoryCatalog(), sql
    session.close()


def test_catalog_ownership_filter_and_limit_are_pushed_to_pg(catalog):
    service, statements = catalog
    assert (
        service.candidates(["t"], target_user_id="u", conversation_id="123", limit=20)
        == []
    )
    sql = statements[-1]
    for fragment in [
        "user_tenant_t.tenant_id IN ('t')",
        "conversation_record_t.created_by = 'u'",
        "conversation_record_t.conversation_id = 123",
        "LIMIT 21",
        "user_account_t.delete_flag = 'N'",
    ]:
        assert fragment in sql


@pytest.mark.parametrize("group", [None, "agent:7", "other"])
def test_directory_keyset_and_category_compile(catalog, group):
    service, statements = catalog
    assert service.directory_page("t", "u", "workbench", group, 0, 20, "报告_%") == []
    sql = statements[-1]
    assert "LIMIT 21" in sql and "ORDER BY" in sql
    assert "user_tenant_t.tenant_id IN ('t')" in sql
    assert "workbench_config IS NOT NULL" in sql
    assert "nl2agent_main" in sql and "nl2skill_main" in sql
    if group == "other":
        assert "agent_id IS NULL" in sql
    elif group:
        assert "agent_id = 7" in sql
    else:
        assert "GROUP BY coalesce" in sql


def test_user_facet_search_and_keyset_compile(catalog):
    service, statements = catalog
    assert service.user_page(["t", "t2"], "owner", ["t", "u"], 20) == []
    sql = statements[-1]
    assert "LIMIT 21" in sql and "user_account_t.user_email ILIKE" in sql
    assert "user_tenant_t.tenant_id > 't'" in sql
    assert "user_tenant_t.user_id > 'u'" in sql


def test_message_queries_transfer_bounded_previews_and_byte_slices(catalog, mocker):
    service, statements = catalog
    assert service.messages("123", 100, 10, 50) == []
    sql = statements[-1]
    assert "substr" in sql and "4096" in sql and "LIMIT 51" in sql
    assert "message_id <= 100" in sql and "message_id > 10" in sql
    mocker.patch(
        "sqlalchemy.orm.Query.first",
        lambda query: statements.append(
            str(
                query.statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        ),
    )
    service.message_content("123", "11", 1000, 1048576)
    assert (
        "convert_to(nexent.conversation_message_t.message_content, 'UTF8')"
        in statements[-1]
    )
    assert "1001" in statements[-1] and "1048576" in statements[-1]
    service.message_content("123", "11", 0, 0)
    assert "), 1, 0)" in statements[-1]
    assert "md5(nexent.conversation_message_t.message_content)" in statements[-1]
    assert "conversation_message_t.message_id = 11" in statements[-1]
    assert "conversation_message_t.delete_flag = 'N'" in statements[-1]


def test_source_message_query_is_scalar_owned_bounded_and_keeps_deleted_history(
    catalog,
):
    service, statements = catalog
    assert service.source_messages("t", "u", "123", upper="20", limit=100) == []
    sql = statements[-1]
    assert "message_content" not in sql
    assert "conversation_record_t.created_by = 'u'" in sql
    assert "user_tenant_t.tenant_id IN ('t')" in sql
    assert "conversation_record_t.conversation_id = 123" in sql
    assert "message_role = 'user'" in sql and "message_id <= 20" in sql
    assert "ORDER BY" in sql and "LIMIT 101" in sql
    assert "conversation_message_t.delete_flag" not in sql


def test_source_message_budget_returns_retryable_error(catalog, mocker):
    from management.services.trajectory.primitives import QueryError

    service, _ = catalog
    mocker.patch("sqlalchemy.orm.Query.all", return_value=[(1,), (2,)])
    with pytest.raises(QueryError, match="source_coverage_budget_exceeded") as error:
        service.source_messages("t", "u", "123", limit=1)
    assert error.value.status == 503 and error.value.retry_after == 2


def test_agent_names_match_existing_display_and_public_fallback(catalog, mocker):
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID

    service, statements = catalog
    assert service.agent_names(["t"], ["7"]) == {("t", "7"): "7"}
    assert "coalesce" in statements[-1] and "display_name" in statements[-1]
    mocker.patch(
        "sqlalchemy.orm.Query.all", return_value=[(ASSET_OWNER_TENANT_ID, 7, "Public")]
    )
    assert service.agent_names(["t"], ["7"]) == {("t", "7"): "Public"}
    mocker.patch(
        "sqlalchemy.orm.Query.all",
        return_value=[(ASSET_OWNER_TENANT_ID, 7, "Public"), ("t", 7, "Local")],
    )
    assert service.agent_names(["t"], ["7"]) == {("t", "7"): "Local"}
