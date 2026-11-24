# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP tool monitoring read surface: published documents, grouping and tenant catalogs."""

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


def test_read_mcp_tools_scopes_the_query_to_the_requested_tenant_and_kind():
    from ops.monitoring.query import read_mcp_tools

    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 2,
               "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": "t1"}]
    documents = [{"tenant_id": "tenant-a", "statistic_date": "2026-11-17", "mcp_server_id": 3,
                  "mcp_server_name": "docs", "mcp_server_type": "container", "tool_name": "search_docs",
                  "request_count": 5, "error_count": 0, "error_eligible_count": 5,
                  "duration_ms_sum": 100, "duration_ms_sample_count": 5}]
    service, store, captured = _tool_service(states, documents)
    store.coverage_starts.return_value = {"tenant-a": datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC"))}

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                             end=date(2026, 11, 17), groups=[1], server_id=3,
                                             server_type=None, tool_name=None)

    assert captured["snapshot_args"] == ("tenant-a", "mcp_tool", date(2026, 11, 17), date(2026, 11, 17))
    assert store.has_failed_batches.call_args.args[1] == "mcp_tool"
    assert store.coverage_starts.call_args.args[1] == "mcp_tool"
    constraints = captured["constraints"]["bool"]["filter"]
    assert {"term": {"fact_kind": "mcp_tool"}} in constraints
    selection = json.dumps(constraints[-1])
    assert "tenant-a" in selection and "tenant-b" not in selection and "pub-1" in selection
    assert rows == documents
    assert available == [date(2026, 11, 17)]
    assert status["coverage_state"] == "covered"


def test_read_mcp_tools_reports_uncovered_days_and_staleness():
    from ops.monitoring.query import read_mcp_tools

    states = [
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 3,
         "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": None},
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 16), "source_revision": 1,
         "published_source_revision": None, "publish_id": None, "source_snapshot_at": None},
    ]
    service, store, _ = _tool_service(states)
    store.has_failed_batches.return_value = True

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 16),
                                             end=date(2026, 11, 17), groups=[], server_id=None,
                                             server_type=None, tool_name=None)

    assert rows == []
    assert available == [date(2026, 11, 17)]
    assert status == {"data_as_of": None, "coverage_state": "partial", "is_stale": True}


def test_read_mcp_tools_reports_uncovered_window_without_zeroing():
    from ops.monitoring.query import read_mcp_tools

    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": None, "publish_id": None, "source_snapshot_at": None}]
    service, _, _ = _tool_service(states)

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                             end=date(2026, 11, 17), groups=[], server_id=None,
                                             server_type=None, tool_name=None)

    assert rows == [] and available == []
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
    servers = mcp_server_rows(rows)
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
        {"mcp_id": 3, "mcp_name": "docs", "tenant_id": "tenant-a", "container_id": None, "config_json": None},
        {"mcp_id": 4, "mcp_name": "boxed", "tenant_id": "tenant-a", "container_id": "abc", "config_json": None},
        {"mcp_id": 5, "mcp_name": "openapi", "tenant_id": "tenant-b", "container_id": None,
         "config_json": {"openapi": "3.0.0"}},
    ]
    statements = []
    monkeypatch.setattr("ops.monitoring.query.get_db_session", lambda: _fake_db_session(rows, statements))

    catalog = mcp_server_catalog("tenant-a")
    assert {entry["name"]: entry for entry in catalog} == {
        "docs": {"service_id": 3, "name": "docs", "type": "remote"},
        "boxed": {"service_id": 4, "name": "boxed", "type": "container"},
        "openapi": {"service_id": 5, "name": "openapi", "type": "remote"},
    }
    assert statements[0].compile().params["tenant_id_1"] == "tenant-a"

    # The whole-platform readers pass tenant=None and skip the tenant filter.
    assert mcp_server_catalog(None) == catalog
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


def test_read_mcp_tools_reads_the_whole_platform_without_a_tenant():
    from ops.monitoring.query import read_mcp_tools

    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": 1, "publish_id": "pub-1", "source_snapshot_at": None}]
    service, store, _ = _tool_service(states)
    store.coverage_starts.return_value = {"tenant-a": datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC"))}

    rows, available, status = read_mcp_tools(service, tenant=None, start=date(2026, 11, 17),
                                             end=date(2026, 11, 17), groups=[], server_id=None,
                                             server_type=None, tool_name=None)

    assert rows == [] and available == [date(2026, 11, 17)]
    assert status["coverage_state"] == "covered"
    assert store.coverage_starts.call_args.args[0] == {"tenant-a"}
