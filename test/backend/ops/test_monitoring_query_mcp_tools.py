# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP tool monitoring read surface: registered inventory, published documents and grouping."""

import json
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo


def _tool_service(states, documents=()):
    """Fake the Monitoring read surface used by read_mcp_tools."""
    captured = {}
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {}

    @contextmanager
    def fake_snapshot(tenant, kind, start, end):
        captured["snapshot_args"] = (tenant, kind, start, end)
        point = None
        if any(row["publish_id"] for row in states):
            def read_documents(constraints):
                captured["constraints"] = constraints
                return iter(documents)

            point = SimpleNamespace(documents=read_documents)
        yield states, point

    return SimpleNamespace(store=store, zone=ZoneInfo("UTC"), publication_snapshot=fake_snapshot), store, captured


def test_read_mcp_tools_scopes_the_query_to_the_requested_tenant_and_kind(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    registered = [{"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
                   "mcp_server_type": "container", "group_ids": (1,)}]
    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: registered)
    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 2,
               "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": "t1"}]
    documents = [{"tenant_id": "tenant-a", "statistic_date": "2026-11-17", "mcp_server_id": 3,
                  "mcp_server_name": "docs", "mcp_server_type": "container", "tool_name": "search_docs",
                  "request_count": 5, "error_count": 0, "error_eligible_count": 5,
                  "duration_ms_sum": 100, "duration_ms_sample_count": 5}]
    service, store, captured = _tool_service(states, documents)
    store.coverage_starts.return_value = {"tenant-a": datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC"))}

    rows, inventory, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                                        end=date(2026, 11, 17), groups=[1], server_id=3,
                                                        server_type=None, tool_name=None)

    assert captured["snapshot_args"] == ("tenant-a", "mcp_tool", date(2026, 11, 17), date(2026, 11, 17))
    assert store.has_failed_batches.call_args.args[1] == "mcp_tool"
    assert store.coverage_starts.call_args.args[1] == "mcp_tool"
    constraints = captured["constraints"]["bool"]["filter"]
    assert {"term": {"fact_kind": "mcp_tool"}} in constraints
    # Group filtering resolves to the configured server identity, not initiator groups.
    assert {"terms": {"mcp_server_id": [3]}} in constraints
    assert "initiator_group_ids" not in json.dumps(captured["constraints"])
    selection = json.dumps(constraints[-1])
    assert "tenant-a" in selection and "tenant-b" not in selection and "pub-1" in selection
    assert rows == documents
    assert inventory == registered
    assert available == [date(2026, 11, 17)]
    assert status["coverage_state"] == "covered"


def test_read_mcp_tools_matches_requested_groups_against_configured_access_groups(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    registered = [
        {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
         "mcp_server_type": "container", "group_ids": (5,)},
        {"tenant_id": "tenant-a", "mcp_server_id": 8, "mcp_server_name": "idle",
         "mcp_server_type": "remote", "group_ids": (7,)},
        # Public and unassigned servers never match an active group filter.
        {"tenant_id": "tenant-a", "mcp_server_id": 11, "mcp_server_name": "public",
         "mcp_server_type": "remote", "group_ids": None},
        {"tenant_id": "tenant-a", "mcp_server_id": 12, "mcp_server_name": "unassigned",
         "mcp_server_type": "remote", "group_ids": ()},
    ]
    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: registered)
    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": 1, "publish_id": "pub-1", "source_snapshot_at": None}]
    service, _, captured = _tool_service(states)

    def selected(**kwargs):
        _, inventory, _, _ = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                            end=date(2026, 11, 17), **kwargs)
        return [entry["mcp_server_id"] for entry in inventory]

    assert selected(groups=[5], server_id=None, server_type=None, tool_name=None) == [3]
    assert {"terms": {"mcp_server_id": [3]}} in captured["constraints"]["bool"]["filter"]
    # A group no server is configured for still constrains the query to nothing.
    assert selected(groups=[9], server_id=None, server_type=None, tool_name=None) == []
    assert {"terms": {"mcp_server_id": []}} in captured["constraints"]["bool"]["filter"]
    # Without a group filter the registered inventory passes through unfiltered.
    assert selected(groups=[], server_id=None, server_type=None, tool_name=None) == [3, 8, 11, 12]
    assert "mcp_server_id" not in json.dumps(captured["constraints"])


def test_read_mcp_tools_applies_resource_filters_to_the_inventory(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    registered = [
        {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
         "mcp_server_type": "container", "group_ids": (5,)},
        {"tenant_id": "tenant-a", "mcp_server_id": 8, "mcp_server_name": "idle",
         "mcp_server_type": "remote", "group_ids": (5,)},
    ]
    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: registered)
    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": 1, "publish_id": "pub-1", "source_snapshot_at": None}]
    service, _, _ = _tool_service(states)

    def selected(**kwargs):
        _, inventory, _, _ = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                            end=date(2026, 11, 17), **kwargs)
        return [entry["mcp_server_id"] for entry in inventory]

    assert selected(groups=[5], server_id=8, server_type=None, tool_name=None) == [8]
    assert selected(groups=[5], server_id=None, server_type="remote", tool_name=None) == [8]
    # api_convert and unknown are fact-row types without registered inventory entries.
    assert selected(groups=[5], server_id=None, server_type="api_convert", tool_name=None) == []


def test_read_mcp_tools_reports_uncovered_days_and_staleness(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: [])
    states = [
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 3,
         "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": None},
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 16), "source_revision": 1,
         "published_source_revision": None, "publish_id": None, "source_snapshot_at": None},
    ]
    service, store, _ = _tool_service(states)
    store.has_failed_batches.return_value = True

    rows, inventory, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 16),
                                                        end=date(2026, 11, 17), groups=[], server_id=None,
                                                        server_type=None, tool_name=None)

    assert rows == [] and inventory == []
    assert available == [date(2026, 11, 17)]
    assert status == {"data_as_of": None, "coverage_state": "partial", "is_stale": True}


def test_read_mcp_tools_reports_uncovered_window_without_zeroing(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: [])
    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": None, "publish_id": None, "source_snapshot_at": None}]
    service, _, _ = _tool_service(states)

    rows, inventory, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                                        end=date(2026, 11, 17), groups=[], server_id=None,
                                                        server_type=None, tool_name=None)

    assert rows == [] and inventory == [] and available == []
    assert status["coverage_state"] == "uncovered"


def test_mcp_tool_rows_group_by_tenant_server_and_tool():
    from ops.monitoring.query import mcp_tool_rows

    def row(**overrides):
        return {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
                "mcp_server_type": "container", "tool_name": "search_docs", "statistic_date": "2026-11-17",
                "request_count": 1, "error_count": 0, "error_eligible_count": 1,
                "duration_ms_sum": 10, "duration_ms_sample_count": 1, **overrides}

    rows = [
        row(request_count=2, duration_ms_sum=50, duration_ms_sample_count=2),
        row(request_count=3, duration_ms_sum=40, duration_ms_sample_count=1),
        row(tenant_id="tenant-b", tool_name="translate"),
        {"tenant_id": "tenant-a", "mcp_server_name": "outer-apis", "mcp_server_type": "builtin",
         "tool_name": "search_docs", "statistic_date": "2026-11-17", "request_count": 4,
         "error_count": 0, "error_eligible_count": 4, "duration_ms_sum": 8, "duration_ms_sample_count": 4},
    ]
    items = mcp_tool_rows(rows)
    assert len(items) == 3
    by_tool = {(item["tenant_id"], item.get("mcp_server_id"), item["tool_name"]): item for item in items}
    docs = by_tool[("tenant-a", 3, "search_docs")]
    assert docs["metrics"]["request_count"] == 5
    assert docs["metrics"]["avg_duration_ms"] == 30
    assert by_tool[("tenant-b", 3, "translate")]["metrics"]["request_count"] == 1
    local = by_tool[("tenant-a", None, "search_docs")]
    assert local["mcp_server_type"] == "builtin"
    assert local["metrics"]["request_count"] == 4


def test_read_mcp_tool_directory_honors_snapshot_precedence_and_tool_filter(monkeypatch):
    from ops.monitoring import query

    day = date(2026, 11, 17)
    records = [
        {"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": None,
         "registry_json": {"_toolNames": ["search_docs", "index_docs", "search_docs", None],
                           "tools": [{"name": "stale_snapshot"}]}},
        {"mcp_id": 4, "mcp_name": "empty", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": "", "registry_json": {"_toolNames": []}},
        {"mcp_id": 5, "mcp_name": "docs", "tenant_id": "tenant-b", "container_id": None,
         "config_json": None, "group_ids": None, "registry_json": None},
        {"mcp_id": 6, "mcp_name": "described", "tenant_id": "tenant-b", "container_id": None,
         "config_json": None, "group_ids": "", "registry_json": {"tools": [{"name": "search_docs"}]}},
    ]
    statements = []

    @contextmanager
    def session():
        def execute(statement):
            statements.append(statement)
            if "ag_tool_info_t" in str(statement):
                return [(5, "search_docs"), (5, "legacy_only"), (5, "search_docs")]
            return SimpleNamespace(mappings=lambda: records)

        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(query, "get_db_session", session)
    monkeypatch.setattr(query, "LOCAL_MCP_SERVER", None)
    service, _, _ = _tool_service([])
    _, inventory, _, _ = query.read_mcp_tools(
        service, tenant=None, start=day, end=day, groups=[], server_id=None, server_type=None,
        tool_name="search_docs", include_tool_directory=True,
    )
    assert {entry["mcp_server_id"]: entry["tool_names"] for entry in inventory} == {
        3: ("search_docs",), 4: (), 5: ("search_docs",), 6: ("search_docs",),
    }
    fallback = statements[1]
    sql = str(fallback)
    assert fallback.compile().params["mcp_id_1"] == [5]
    assert fallback.compile().params["source_1"] == "mcp"
    assert "ag_tool_info_t.author = nexent.mcp_record_t.tenant_id" in sql
    assert "ag_tool_info_t.usage = nexent.mcp_record_t.mcp_name" in sql
    assert "ag_tool_info_t.delete_flag !=" in sql
    assert "ag_tool_info_t.is_available IS NOT false" in sql


def test_mcp_server_rows_aggregate_tools_per_server():
    from ops.monitoring.query import mcp_server_rows

    def doc(**overrides):
        return {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
                "mcp_server_type": "container", "tool_name": "search_docs", "statistic_date": "2026-11-17",
                "request_count": 2, "error_count": 0, "error_eligible_count": 2,
                "duration_ms_sum": 20, "duration_ms_sample_count": 2, **overrides}

    rows = [
        doc(request_count=2, duration_ms_sum=20, duration_ms_sample_count=2),
        doc(tool_name="translate", request_count=3, error_count=1, error_eligible_count=3,
            duration_ms_sum=30, duration_ms_sample_count=1),
        doc(mcp_server_id=4, mcp_server_name="outer-apis", mcp_server_type="builtin",
            tool_name="local_tool", request_count=1, duration_ms_sum=5, duration_ms_sample_count=1),
        doc(mcp_server_id=None, mcp_server_name="outer-apis", mcp_server_type="unknown",
            tool_name="local_tool", request_count=4, duration_ms_sum=8, duration_ms_sample_count=4),
    ]
    servers = mcp_server_rows(rows, [], covered=True)
    assert len(servers) == 3
    by_server = {(s["tenant_id"], s.get("mcp_server_id")): s for s in servers}
    docs = by_server[("tenant-a", 3)]
    assert docs["mcp_server_name"] == "docs"
    assert docs["mcp_server_type"] == "container"
    assert docs["active_tools"] == 2
    assert docs["metrics"]["request_count"] == 5
    assert docs["metrics"]["error_count"] == 1
    assert docs["metrics"]["avg_duration_ms"] == 50 / 3
    local_db = by_server[("tenant-a", 4)]
    assert local_db["active_tools"] == 1
    assert local_db["mcp_server_type"] == "builtin"
    unattributed = by_server[("tenant-a", None)]
    assert unattributed["active_tools"] == 1
    assert unattributed["metrics"]["request_count"] == 4


def test_mcp_server_rows_merges_registered_inventory_with_published_rows():
    from ops.monitoring.query import mcp_server_rows

    inventory = [
        {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
         "mcp_server_type": "container"},
        {"tenant_id": "tenant-a", "mcp_server_id": 9, "mcp_server_name": "idle",
         "mcp_server_type": "remote"},
    ]
    rows = [
        {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
         "mcp_server_type": "container", "tool_name": "search_docs", "request_count": 2,
         "error_count": 0, "error_eligible_count": 2, "duration_ms_sum": 20,
         "duration_ms_sample_count": 2},
        # History of a server whose registration is no longer current is kept.
        {"tenant_id": "tenant-a", "mcp_server_id": 4, "mcp_server_name": "removed",
         "mcp_server_type": "remote", "tool_name": "gone_tool", "request_count": 1,
         "error_count": 0, "error_eligible_count": 1, "duration_ms_sum": 5,
         "duration_ms_sample_count": 1},
    ]

    covered = mcp_server_rows(rows, inventory, covered=True)
    by_server = {(s["tenant_id"], s.get("mcp_server_id")): s for s in covered}
    assert set(by_server) == {("tenant-a", 3), ("tenant-a", 4), ("tenant-a", 9)}
    assert by_server[("tenant-a", 3)]["metrics"]["request_count"] == 2
    # Covered never-called servers report definitive zero counters.
    idle = by_server[("tenant-a", 9)]
    assert idle["metrics"] == {"request_count": 0, "error_count": 0, "error_eligible_count": 0,
                               "error_rate": None, "avg_duration_ms": None}
    assert idle["active_tools"] == 0
    assert by_server[("tenant-a", 4)]["metrics"]["request_count"] == 1

    # Uncovered windows keep unknown metrics instead of zeroing them.
    uncovered = mcp_server_rows(rows, inventory, covered=False)
    idle = {(s["tenant_id"], s.get("mcp_server_id")): s for s in uncovered}[("tenant-a", 9)]
    assert idle["metrics"] == {"request_count": None, "error_count": None, "error_eligible_count": None,
                               "error_rate": None, "avg_duration_ms": None}


@contextmanager
def _fake_db_session(rows, statements):
    """Replace get_db_session with a session recording statements and returning rows."""
    def execute(statement):
        statements.append(statement)
        return SimpleNamespace(mappings=lambda: rows)

    yield SimpleNamespace(execute=execute)


def test_mcp_server_catalog_lists_registered_servers_with_coarse_types(monkeypatch):
    from ops.monitoring.query import mcp_server_catalog

    rows = [
        {"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None, "config_json": None,
         "group_ids": None},
        {"mcp_id": 4, "mcp_name": "boxed", "tenant_id": "tenant-a", "container_id": "abc", "config_json": None,
         "group_ids": "2"},
        {"mcp_id": 5, "mcp_name": "openapi", "tenant_id": "tenant-b", "container_id": None,
         "config_json": {"openapi": "3.0.0"}, "group_ids": "2, 3"},
    ]
    statements = []
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, statements))
    monkeypatch.setattr("ops.monitoring.query.LOCAL_MCP_SERVER", None)

    catalog = mcp_server_catalog("tenant-a")
    assert {entry["name"]: entry for entry in catalog} == {
        "docs": {"service_id": 3, "name": "docs", "type": "remote", "group_ids": None},
        "boxed": {"service_id": 4, "name": "boxed", "type": "container", "group_ids": [2]},
        "openapi": {"service_id": 5, "name": "openapi", "type": "remote", "group_ids": [2, 3]},
    }
    assert statements[0].compile().params["tenant_id_1"] == "tenant-a"

    # The whole-platform readers pass tenant=None and skip the tenant filter.
    assert mcp_server_catalog(None) == catalog
    assert "tenant_id_1" not in statements[1].compile().params


def test_mcp_server_catalog_appends_the_local_endpoint_when_configured(monkeypatch):
    """The tenant-local endpoint is synthesized without a database record."""
    from ops.monitoring.query import mcp_server_catalog

    rows = [{"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None,
             "config_json": None, "group_ids": None}]
    statements = []
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, statements))
    monkeypatch.setattr("ops.monitoring.query.LOCAL_MCP_SERVER", "http://mcp.internal:8080")

    catalog = mcp_server_catalog("tenant-a")
    assert catalog == [
        {"service_id": 3, "name": "docs", "type": "remote", "group_ids": None},
        {"service_id": None, "name": "outer-apis", "type": "builtin", "group_ids": None,
         "instance_count": 1},
    ]
    rows.append({**rows[0], "mcp_id": 4, "tenant_id": "tenant-b", "mcp_name": "files"})
    assert mcp_server_catalog(None) == [
        catalog[0],
        {"service_id": 4, "name": "files", "type": "remote", "group_ids": None},
        {**catalog[1], "instance_count": 2},
    ]


def test_mcp_server_catalog_filters_by_configured_access_groups(monkeypatch):
    """An active group filter keeps only explicitly configured servers selectable."""
    from ops.monitoring.query import mcp_server_catalog

    rows = [
        {"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": "5"},
        {"mcp_id": 4, "mcp_name": "public", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": None},
        {"mcp_id": 6, "mcp_name": "unassigned", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": " "},
    ]
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, []))
    monkeypatch.setattr("ops.monitoring.query.LOCAL_MCP_SERVER", "http://mcp.internal:8080")

    assert mcp_server_catalog("tenant-a") == [
        {"service_id": 3, "name": "docs", "type": "remote", "group_ids": [5]},
        {"service_id": 4, "name": "public", "type": "remote", "group_ids": None},
        {"service_id": 6, "name": "unassigned", "type": "remote", "group_ids": []},
        {"service_id": None, "name": "outer-apis", "type": "builtin", "group_ids": None,
         "instance_count": 1},
    ]
    # Public records, unassigned records and the local endpoint never match.
    assert mcp_server_catalog("tenant-a", [5]) == [
        {"service_id": 3, "name": "docs", "type": "remote", "group_ids": [5]},
    ]
    assert mcp_server_catalog("tenant-a", [9]) == []


def test_mcp_server_inventory_parses_access_groups_and_synthesizes_the_local_endpoint(monkeypatch):
    from ops.monitoring.query import mcp_server_inventory

    rows = [
        {"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None,
         "config_json": None, "group_ids": " 5, 7 ,5"},
        {"mcp_id": 4, "mcp_name": "boxed", "tenant_id": "tenant-a", "container_id": "abc",
         "config_json": None, "group_ids": None},
        {"mcp_id": 5, "mcp_name": "messy", "tenant_id": "tenant-b", "container_id": None,
         "config_json": {"openapi": "3.0.0"}, "group_ids": "9, ,x,2147483648"},
        {"mcp_id": 6, "mcp_name": "unassigned", "tenant_id": "tenant-b", "container_id": None,
         "config_json": None, "group_ids": " "},
    ]
    statements = []
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, statements))
    monkeypatch.setattr("ops.monitoring.query.LOCAL_MCP_SERVER", "http://mcp.internal:8080")

    inventory = mcp_server_inventory("tenant-a")
    # The fake session ignores the WHERE clause; the compiled params prove the tenant filter.
    assert {entry["mcp_server_id"]: entry for entry in inventory if entry["mcp_server_id"] is not None} == {
        3: {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
            "mcp_server_type": "remote", "group_ids": (5, 7), "tool_names": None},
        4: {"tenant_id": "tenant-a", "mcp_server_id": 4, "mcp_server_name": "boxed",
            "mcp_server_type": "container", "group_ids": None, "tool_names": None},
        5: {"tenant_id": "tenant-b", "mcp_server_id": 5, "mcp_server_name": "messy",
            "mcp_server_type": "remote", "group_ids": (9,), "tool_names": None},
        6: {"tenant_id": "tenant-b", "mcp_server_id": 6, "mcp_server_name": "unassigned",
            "mcp_server_type": "remote", "group_ids": (), "tool_names": None},
    }
    # The tenant-local endpoint is synthesized for the requested tenant only.
    assert [entry for entry in inventory if entry["mcp_server_id"] is None] == [
        {"tenant_id": "tenant-a", "mcp_server_id": None, "mcp_server_name": "outer-apis",
         "mcp_server_type": "builtin", "group_ids": None}]
    assert statements[0].compile().params["tenant_id_1"] == "tenant-a"

    # Whole-platform readers synthesize the local endpoint per observed tenant.
    platform = mcp_server_inventory(None)
    assert [entry for entry in platform if entry["mcp_server_type"] == "builtin"] == [
        {"tenant_id": "tenant-a", "mcp_server_id": None, "mcp_server_name": "outer-apis",
         "mcp_server_type": "builtin", "group_ids": None},
        {"tenant_id": "tenant-b", "mcp_server_id": None, "mcp_server_name": "outer-apis",
         "mcp_server_type": "builtin", "group_ids": None},
    ]
    assert "tenant_id_1" not in statements[1].compile().params


def test_mcp_services_by_tenant_counts_registered_servers(monkeypatch):
    from ops.monitoring.query import mcp_services_by_tenant

    rows = [{"tenant_id": "tenant-a", "service_count": 2}, {"tenant_id": "tenant-b", "service_count": 1}]
    statements = []
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, statements))

    assert mcp_services_by_tenant("tenant-a") == rows
    compiled = str(statements[0])
    assert "count" in compiled.lower() and "tenant_id" in compiled
    assert statements[0].compile().params["tenant_id_1"] == "tenant-a"

    assert mcp_services_by_tenant(None) == rows
    assert "tenant_id_1" not in statements[1].compile().params


def test_read_mcp_tools_reads_the_whole_platform_without_a_tenant(monkeypatch):
    from ops.monitoring.query import read_mcp_tools

    monkeypatch.setattr("ops.monitoring.query.mcp_server_inventory", lambda tenant: [])
    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": 1, "publish_id": "pub-1", "source_snapshot_at": None}]
    service, store, _ = _tool_service(states)
    store.coverage_starts.return_value = {"tenant-a": datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC"))}

    rows, inventory, available, status = read_mcp_tools(service, tenant=None, start=date(2026, 11, 17),
                                                        end=date(2026, 11, 17), groups=[], server_id=None,
                                                        server_type=None, tool_name=None)

    assert rows == [] and inventory == [] and available == [date(2026, 11, 17)]
    assert status["coverage_state"] == "covered"
    assert store.coverage_starts.call_args.args[0] == {"tenant-a"}
