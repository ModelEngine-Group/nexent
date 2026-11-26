# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Group ownership filtering for monitoring resource scopes."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@contextmanager
def _fake_db_session(rows):
    class Session:
        def execute(self, _statement):
            return iter(rows)

    yield Session()


@pytest.fixture
def scope_rows(monkeypatch):
    """Patch group_scope_ids' DB read to return (id, group_ids) pairs."""
    from ops.monitoring import query

    def patch(rows):
        monkeypatch.setattr(query, "get_db_session", lambda: _fake_db_session(rows))

    return patch


def test_no_group_scope_short_circuits_to_none(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([])
    assert group_scope_ids("tenant", "agent", None) is None
    assert group_scope_ids("tenant", "mcp", None) is None
    assert group_scope_ids("tenant", "skill", None) is None


def test_model_kind_always_returns_none(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([])
    assert group_scope_ids("tenant", "model", 1) is None
    assert group_scope_ids("tenant", "model", "ungrouped") is None


def test_specific_group_keeps_resources_owned_by_group(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([(1, "1,2"), (2, "2"), (3, None), (4, "")])
    assert group_scope_ids("tenant", "agent", 1) == {1}
    assert group_scope_ids("tenant", "agent", 2) == {1, 2}


def test_ungrouped_keeps_resources_without_groups(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([(1, "1,2"), (2, "2"), (3, None), (4, "")])
    assert group_scope_ids("tenant", "agent", "ungrouped") == {3, 4}


def test_skill_ids_are_stringified_to_match_facts(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([(10, "1"), (20, "2")])
    assert group_scope_ids("tenant", "skill", 1) == {"10"}
    assert group_scope_ids("tenant", "skill", "ungrouped") == set()


def test_mcp_ids_remain_integers(scope_rows):
    from ops.monitoring.query import group_scope_ids

    scope_rows([(7, "1"), (8, ""), (9, None)])
    assert group_scope_ids("tenant", "mcp", 1) == {7}
    assert group_scope_ids("tenant", "mcp", "ungrouped") == {8}

def test_published_query_pushes_resource_ids_into_es_and_skips_empty_scope():
    from ops.monitoring.query import _read_published_rows

    day = date(2026, 11, 23)
    states = [{"tenant_id": "tenant", "statistic_date": day, "publish_id": "ready"}]
    point = Mock()
    point.documents.return_value = iter([{"skill_id": "167", "usage_count": 1}])

    @contextmanager
    def snapshot(*_args):
        yield states, point

    service = SimpleNamespace(publication_snapshot=snapshot)
    scope = dict(tenant="tenant", kind="skill", start=day, end=day)
    rows, _, _ = _read_published_rows(service, **scope, resource_scope=("skill_id", {"167", "200"}))
    assert rows == [{"skill_id": "167", "usage_count": 1}]
    filters = point.documents.call_args.args[0]["bool"]["filter"]
    assert {"terms": {"skill_id": ["167", "200"]}} in filters
    assert not any("initiator_group_ids" in clause.get("terms", {}) for clause in filters)
    point.reset_mock()
    assert _read_published_rows(service, **scope, resource_scope=("skill_id", set())) == ([], states, states)
    point.documents.assert_not_called()


@pytest.mark.parametrize("covered, expected", [(False, None), (True, 0)])
def test_mcp_service_list_keeps_registered_services_without_calls(covered, expected):
    from ops.monitoring.query import mcp_server_rows

    items = mcp_server_rows([], [
        {"tenant_id": "tenant", "service_id": 8, "name": "No calls", "type": "remote"},
    ], covered=covered)
    assert len(items) == 1
    assert items[0]["mcp_server_id"] == 8
    assert items[0]["metrics"]["request_count"] == expected
    assert items[0]["active_tools"] == expected


def test_resource_group_checks_the_tenant_without_reading_operator_membership(monkeypatch):
    from fastapi import HTTPException
    from ops.api import monitoring

    def tenant_groups(ids, tenant):
        assert ids == [12]
        return ids if tenant == "owner-tenant" else []

    monkeypatch.setattr(monitoring, "filter_tenant_group_ids", tenant_groups)
    selected = SimpleNamespace(resource_group="12", group_ids=[])
    assert monitoring._resource_group(selected, "owner-tenant") == 12
    with pytest.raises(HTTPException) as foreign:
        monitoring._resource_group(selected, "foreign-tenant")
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as all_tenants:
        monitoring._resource_group(selected, None)
    assert all_tenants.value.status_code == 422
