# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The per-run MCP monitoring catalog maps used URLs to normalized server identities."""

from types import SimpleNamespace

from infrastructure.monitoring import catalog as pure_catalog
from management.services.agent import monitoring_catalog as catalog_mod
from management.services.agent.monitoring_catalog import (
    build_mcp_server_catalog,
    build_run_monitoring_catalog,
)

LOCAL = "http://local.invalid/mcp/tenant-1/sse"


def _record(url, **overrides):
    record = {
        "remote_mcp_server_name": url.rsplit("/", 1)[-1],
        "remote_mcp_server": url,
        "status": True,
        "mcp_id": 11,
        "container_id": None,
        "config_json": None,
    }
    record.update(overrides)
    return record


def test_catalog_maps_container_and_remote_records():
    records = [
        _record("http://container.invalid/mcp", container_id="abc123"),
        _record("http://container-config.invalid/mcp", config_json={"image": "mcp:latest"}),
        _record("http://empty-config.invalid/mcp", config_json={}),
        _record("http://api-docs.invalid/mcp", config_json={"openapi": "3.0.0"}),
    ]
    catalog = build_mcp_server_catalog(
        [
            "http://container.invalid/mcp",
            "http://container-config.invalid/mcp",
            "http://empty-config.invalid/mcp",
            "http://api-docs.invalid/mcp",
        ],
        records,
        LOCAL,
        set(),
    )
    assert {entry["url"]: entry["mcp_server_type"] for entry in catalog} == {
        "http://container.invalid/mcp": "container",
        "http://container-config.invalid/mcp": "container",
        "http://empty-config.invalid/mcp": "remote",
        "http://api-docs.invalid/mcp": "remote",
    }
    assert all(entry["mcp_server_id"] == 11 and "tool_types" not in entry for entry in catalog)


def test_catalog_local_endpoint_splits_builtin_and_api_convert():
    records = [_record(LOCAL, mcp_id=None, remote_mcp_server_name="outer-apis")]
    catalog = build_mcp_server_catalog([LOCAL], records, LOCAL, {"search_docs", "list_pets"})
    assert len(catalog) == 1
    entry = catalog[0]
    assert entry["url"] == LOCAL
    assert entry["mcp_server_type"] == "builtin"
    assert entry["mcp_server_id"] is None
    assert entry["mcp_server_name"] == "outer-apis"
    assert entry["tool_types"] == {"search_docs": "api_convert", "list_pets": "api_convert"}


def test_catalog_local_endpoint_without_converted_tools_has_no_overrides():
    records = [_record(LOCAL, mcp_id=None, remote_mcp_server_name="outer-apis")]
    catalog = build_mcp_server_catalog([LOCAL], records, LOCAL, set())
    assert catalog[0]["mcp_server_type"] == "builtin"
    assert "tool_types" not in catalog[0]


def test_catalog_skips_urls_without_records():
    assert build_mcp_server_catalog(["http://missing.invalid/mcp"], [], LOCAL, set()) == []


def test_run_catalog_omitted_when_disabled_or_debug_or_empty():
    records = [_record(LOCAL)]
    assert build_run_monitoring_catalog("tenant-1", [LOCAL], records, LOCAL,
                                        enabled=False, is_debug=False) is None
    assert build_run_monitoring_catalog("tenant-1", [LOCAL], records, LOCAL,
                                        enabled=True, is_debug=True) is None
    assert build_run_monitoring_catalog("tenant-1", [], records, LOCAL,
                                        enabled=True, is_debug=False) is None


def test_run_catalog_degrades_to_none_on_lookup_failure(monkeypatch):
    def broken_query(tenant_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog_mod, "query_converted_tool_names", broken_query)
    assert build_run_monitoring_catalog("tenant-1", [LOCAL], [_record(LOCAL)], LOCAL,
                                        enabled=True, is_debug=False) is None


def test_run_catalog_builds_with_converted_names(monkeypatch):
    seen = {}

    def fake_query(tenant_id):
        seen["tenant_id"] = tenant_id
        return {"list_pets"}

    monkeypatch.setattr(catalog_mod, "query_converted_tool_names", fake_query)
    catalog = build_run_monitoring_catalog("tenant-1", [LOCAL], [_record(LOCAL, mcp_id=None)], LOCAL,
                                           enabled=True, is_debug=False)
    assert seen["tenant_id"] == "tenant-1"
    assert catalog and catalog[0]["tool_types"] == {"list_pets": "api_convert"}


def _fastmcp_default_name(method, path, operation_id=None, summary=None):
    """Call the real FastMCP naming rule (its method body never touches ``self``)."""
    from fastmcp.server.openapi import server as server_mod

    for value in vars(server_mod).values():
        function = getattr(value, "_generate_default_name", None) if isinstance(value, type) else None
        if function is not None:
            route = SimpleNamespace(operation_id=operation_id, summary=summary, method=method, path=path)
            return function(None, route, None)
    raise AssertionError("fastmcp _generate_default_name not found")


def test_query_converted_tool_names_reads_tenant_openapi_services(monkeypatch):
    services = [{"config_json": {"openapi": "3.0.0"}}]
    seen = {}

    def fake_convert(converted):
        seen["services"] = converted
        return {"list_pets"}

    def fake_query(tenant_id):
        seen["tenant_id"] = tenant_id
        return services

    from management.db.tool import outer_api

    monkeypatch.setattr(outer_api, "query_available_openapi_services", fake_query)
    monkeypatch.setattr(catalog_mod, "converted_tool_names_from_services", fake_convert)
    assert catalog_mod.query_converted_tool_names("tenant-1") == {"list_pets"}
    assert seen == {"tenant_id": "tenant-1", "services": services}


def test_query_converted_tool_names_degrades_to_empty_on_failure(monkeypatch):
    from management.db.tool import outer_api

    def broken_query(tenant_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(outer_api, "query_available_openapi_services", broken_query)
    assert catalog_mod.query_converted_tool_names("tenant-1") == set()


def test_mcp_records_for_tenant_reads_and_degrades(monkeypatch):
    from management.db.mcp import remote

    seen = {}
    records = [_record("http://remote.invalid/mcp")]

    def fake_records(tenant_id, **_kwargs):
        seen["tenant_id"] = tenant_id
        return records

    monkeypatch.setattr(remote, "get_mcp_records_by_tenant", fake_records)
    assert catalog_mod._mcp_records_for_tenant("tenant-1") == records
    assert seen == {"tenant_id": "tenant-1"}

    def broken_records(tenant_id, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(remote, "get_mcp_records_by_tenant", broken_records)
    assert catalog_mod._mcp_records_for_tenant("tenant-1") == []


def test_run_catalog_from_db_maps_persistence_rows_and_skips_non_dicts(monkeypatch):
    monkeypatch.setattr(catalog_mod, "query_converted_tool_names", lambda tenant_id: set())
    rows = [
        {"mcp_server": "http://remote.invalid/mcp", "mcp_name": "docs", "status": True, "mcp_id": 5,
         "container_id": None, "config_json": None},
        {"mcp_server": "http://container.invalid/mcp", "mcp_name": "boxed", "status": True, "mcp_id": 6,
         "container_id": "abc123", "config_json": None},
        "not-a-dict",
    ]

    assert catalog_mod.build_run_monitoring_catalog_from_db(
        "tenant-1", [], rows, LOCAL, enabled=True, is_debug=False) is None

    catalog = catalog_mod.build_run_monitoring_catalog_from_db(
        "tenant-1", ["http://remote.invalid/mcp", "http://container.invalid/mcp"], rows, LOCAL,
        enabled=True, is_debug=False)
    assert {entry["url"]: entry["mcp_server_type"] for entry in catalog} == {
        "http://remote.invalid/mcp": "remote",
        "http://container.invalid/mcp": "container",
    }
    assert {entry["url"]: entry["mcp_server_id"] for entry in catalog} == {
        "http://remote.invalid/mcp": 5,
        "http://container.invalid/mcp": 6,
    }

    assert catalog_mod.build_run_monitoring_catalog_from_db(
        "tenant-1", ["http://remote.invalid/mcp"], rows, LOCAL, enabled=False, is_debug=False) is None
    assert catalog_mod.build_run_monitoring_catalog_from_db(
        "tenant-1", ["http://remote.invalid/mcp"], rows, LOCAL, enabled=True, is_debug=True) is None


def test_prepare_tenant_monitoring_catalog_assembles_and_degrades(monkeypatch):
    records = [_record("http://remote.invalid/mcp", mcp_id=9, remote_mcp_server_name="docs")]
    monkeypatch.setattr(catalog_mod, "_mcp_records_for_tenant", lambda tenant_id: records)
    monkeypatch.setattr(catalog_mod, "query_converted_tool_names", lambda tenant_id: set())

    assert catalog_mod.prepare_tenant_monitoring_catalog("tenant-1", LOCAL, enabled=False) is None

    # An empty local endpoint must not classify tenant records as the builtin local server.
    local_records = [_record(LOCAL, mcp_id=None, remote_mcp_server_name="outer-apis")]
    monkeypatch.setattr(catalog_mod, "_mcp_records_for_tenant", lambda tenant_id: local_records)
    assert catalog_mod.prepare_tenant_monitoring_catalog("tenant-1", "")[0]["mcp_server_type"] == "remote"

    monkeypatch.setattr(catalog_mod, "_mcp_records_for_tenant", lambda tenant_id: [])
    assert catalog_mod.prepare_tenant_monitoring_catalog("tenant-1", LOCAL) is None

    monkeypatch.setattr(catalog_mod, "_mcp_records_for_tenant", lambda tenant_id: records)
    catalog = catalog_mod.prepare_tenant_monitoring_catalog("tenant-1", LOCAL)
    assert catalog and catalog[0]["url"] == "http://remote.invalid/mcp"
    assert catalog[0]["mcp_server_type"] == "remote"

    def broken_records(tenant_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog_mod, "_mcp_records_for_tenant", broken_records)
    assert catalog_mod.prepare_tenant_monitoring_catalog("tenant-1", LOCAL) is None


def test_openapi_tool_names_match_fastmcp_default_naming():
    spec = {"paths": {
        "/pets": {
            "get": {"operationId": "listPets"},
            "post": {"operationId": "admin__createPet"},
        },
        "/pets/{petId}": {
            "get": {"summary": "Find Pet By Id!"},
            "delete": {},
        },
        "/spaces in path": {"get": {}},
        "/long": {"get": {"operationId": "x" * 80}},
    }}
    names = pure_catalog._openapi_tool_names(spec)
    expected = {
        _fastmcp_default_name("GET", "/pets", operation_id="listPets"),
        _fastmcp_default_name("POST", "/pets", operation_id="admin__createPet"),
        _fastmcp_default_name("GET", "/pets/{petId}", summary="Find Pet By Id!"),
        _fastmcp_default_name("DELETE", "/pets/{petId}"),
        _fastmcp_default_name("GET", "/spaces in path"),
        _fastmcp_default_name("GET", "/long", operation_id="x" * 80),
    }
    assert names == expected
    assert "admin" in names
    # Path placeholders/slashes are stripped (not underscored) by the FastMCP slug rule.
    assert "DELETE_petspetId" in names
    assert "x" * 56 in names


def test_openapi_tool_names_ignores_malformed_specs():
    assert pure_catalog._openapi_tool_names(None) == set()
    assert pure_catalog._openapi_tool_names({"paths": None}) == set()
    assert pure_catalog._openapi_tool_names({"paths": {"a": "not-a-dict", "b": {"get": "not-a-dict"}}}) == set()
