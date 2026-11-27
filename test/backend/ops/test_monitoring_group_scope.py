# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Group ownership filtering for monitoring resource scopes."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ops.api import monitoring
from test.backend.ops.test_monitoring_api import monitoring_client


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


def test_mcp_resource_group_filters_registered_integer_ids(monkeypatch):
    from ops.monitoring import query

    day = date(2026, 11, 23)
    records = [
        {"tenant_id": "tenant", "mcp_server_id": 7, "group_ids": (1,)},
        {"tenant_id": "tenant", "mcp_server_id": 8, "group_ids": ()},
        {"tenant_id": "tenant", "mcp_server_id": 9, "group_ids": None},
        {"tenant_id": "tenant", "mcp_server_id": None, "group_ids": None, "mcp_server_type": "builtin"},
    ]
    monkeypatch.setattr(query, "mcp_server_inventory", lambda tenant: records)
    monkeypatch.setattr(query, "_publication_status", lambda *args, **kwargs: {})
    states = [{"tenant_id": "tenant", "statistic_date": day, "publish_id": "ready"}]
    point = Mock()
    point.documents.return_value = []

    @contextmanager
    def snapshot(*_args):
        yield states, point

    service = SimpleNamespace(publication_snapshot=snapshot, store=Mock())
    scope = dict(tenant="tenant", start=day, end=day, groups=[], server_id=None, server_type=None, tool_name=None)
    _, all_inventory, _, _ = query.read_mcp_tools(service, **scope)
    assert [entry["mcp_server_id"] for entry in all_inventory] == [7, 8, 9, None]
    for group, expected_ids in ((1, [7]), ("ungrouped", [8, 9])):
        _, inventory, _, _ = query.read_mcp_tools(service, **scope, resource_group=group)
        assert [entry["mcp_server_id"] for entry in inventory] == expected_ids
        assert {"terms": {"mcp_server_id": expected_ids}} in point.documents.call_args.args[0]["bool"]["filter"]
    point.reset_mock()
    _, inventory, _, _ = query.read_mcp_tools(service, **scope, resource_group=2)
    assert not inventory
    point.documents.assert_not_called()


def test_mcp_tool_details_isolate_same_name_and_exclude_retired_tools():
    from ops.monitoring.query import mcp_tool_rows

    def server(tenant, identifier, names):
        return {"tenant_id": tenant, "mcp_server_id": identifier, "mcp_server_name": "docs",
                "mcp_server_type": "remote", "tool_names": names}

    directory = [server("a", 3, ("search", "idle")), server("a", 4, ("search",)),
                 server("b", 3, ("search",))]

    def fact(tenant, identifier, name, count):
        return {"tenant_id": tenant, "mcp_server_id": identifier, "mcp_server_name": "previous-name",
                "mcp_server_type": "container", "tool_name": name, "request_count": count,
                "error_count": 0, "error_eligible_count": count, "duration_ms_sum": 0, "duration_ms_sample_count": 0}

    stats = [fact("a", 3, "search", 2), fact("b", 3, "search", 4),
             fact("a", 3, "removed", 8), fact("a", 9, "deleted-service", 16),
             dict(fact("a", None, "local-tool", 1), mcp_server_type="builtin")]
    for covered, missing_count in [(False, None), (True, 0)]:
        items = mcp_tool_rows(stats, directory, covered=covered)
        assert {item["mcp_server_name"] for item in items} == {"docs"}
        assert {item["mcp_server_type"] for item in items} == {"remote"}
        assert {(item["tenant_id"], item["mcp_server_id"], item["tool_name"]): item["metrics"]["request_count"]
                for item in items} == {("a", 3, "search"): 2, ("b", 3, "search"): 4,
                                       ("a", 4, "search"): missing_count, ("a", 3, "idle"): missing_count}


@pytest.mark.parametrize("coverage, calls", [("uncovered", None), ("partial", None), ("covered", 0)])
def test_mcp_idle_directory_is_visible_independent_of_coverage(monitoring_client, monkeypatch, coverage, calls):
    client, _ = monitoring_client
    params = {"start_date": "2026-11-17", "end_date": "2026-11-17", "server_id": 3, "tool_name": "list_docs"}
    inventory = [{"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs",
                  "mcp_server_type": "remote", "tool_names": ("list_docs",)}]
    available = [] if coverage == "uncovered" else [date(2026, 11, 17)]
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        Mock(return_value=([], inventory, available, {"data_as_of": None, "coverage_state": coverage, "is_stale": False})))

    summary = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params).json()["data"]
    assert summary == {"service_count": 1, "active_services": 0, "tool_count": 1, "active_tools": 0,
                       "request_count": calls, "error_count": calls, "error_eligible_count": calls,
                       "error_rate": None, "avg_duration_ms": None}
    listing = client.get("/ops/v1/monitoring/mcp-tools", params={**params, "dimension": "tools"})
    assert listing.status_code == 200
    item, = listing.json()["data"]["items"]
    assert item["tool_name"] == "list_docs" and item["metrics"]["request_count"] == calls
    assert monitoring.read_mcp_tools.call_args.kwargs["include_tool_directory"] is True


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
        {"tenant_id": "tenant", "mcp_server_id": 8, "mcp_server_name": "No calls", "mcp_server_type": "remote"},
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
