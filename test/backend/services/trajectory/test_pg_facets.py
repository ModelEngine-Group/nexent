# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Facet SQL must use the application's real schema and preserve bounded filters."""

import re
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.agent.models import AgentInfo
from management.db.base import TableBase
from ops.db.trajectory.queries import ExecutionCatalog
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError


@pytest.fixture
def database(monkeypatch):
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    monkeypatch.setattr(
        "ops.db.trajectory.queries._session", lambda: nullcontext(session)
    )
    return session


@pytest.mark.parametrize("facet", ["agents", "conversations", "models"])
@pytest.mark.parametrize("after", [None, ["tenant", "7"]])
def test_facet_relations_exist_in_application_metadata_and_filters_are_bound(
    database, facet, after
):
    assert (
        ExecutionCatalog().facets(
            ["tenant"],
            {"target_user_id": "owner", "agent_id": "7"},
            facet,
            "报告_%",
            after,
            20,
        )
        == []
    )
    statement, params = database.execute.call_args.args
    sql = str(statement.compile(dialect=postgresql.dialect()))
    relations = set(
        re.findall(r"\b(?:FROM|JOIN)\s+(nexent\.[a-z_]+)", sql, re.IGNORECASE)
    )
    assert relations and relations <= set(TableBase.metadata.tables)
    assert "ut.tenant_id IN" in sql and "user_id=" in sql and "agent_id=" in sql
    assert (
        params["tenants"] == ["tenant"]
        and params["owner"] == "owner"
        and params["agent"] == 7
    )
    assert params["search"] == "%报告\\_\\%%" and params["limit"] == 21
    assert ("(tenant_id,id) >" in sql) == bool(after)
    if after:
        assert params["after_tenant"] == "tenant" and params["after_id"] == "7"
    if facet == "agents":
        assert f"FROM {AgentInfo.__table__.fullname} a" in sql
        assert "a.version_no=0" in sql and "a.delete_flag='N'" in sql
        assert "a.tenant_id IN (options.tenant_id," in sql
        assert "CASE WHEN a.tenant_id=options.tenant_id THEN 0 ELSE 1 END" in sql
        assert params["shared"] == ASSET_OWNER_TENANT_ID


def test_agent_facet_preserves_result_contract(database):
    rows = [{"tenant_id": "tenant", "id": "7", "name": "分析助手"}]
    database.execute.return_value.mappings.return_value.all.return_value = rows
    assert ExecutionCatalog().facets(["tenant"], {}, "agents", "", None, 20) == rows


def test_facet_database_error_remains_visible(database):
    database.execute.side_effect = ProgrammingError(
        "query", {}, RuntimeError("controlled database failure")
    )
    with pytest.raises(ProgrammingError):
        ExecutionCatalog().facets(["tenant"], {}, "agents", "", None, 20)
