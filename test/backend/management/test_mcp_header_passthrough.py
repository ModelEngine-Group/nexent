# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for Phase 1 northbound MCP header passthrough.

Covers the ``mcp_passthrough`` engine and the reserved-field validation
contract documented in
``nexent-doc/nexent/northbound-mcp-header-passthrough``.

Case map: UT-BE-PASS-001/002/003/006/008/009/010/011/012.
UT-BE-PASS-004/005 (validation whitelist + size limits) live next to the
validator in ``test_runtime_metadata_utils.py``; UT-BE-PASS-007 (prompt
filter) lives with the SDK agent tests.
"""

import json
import logging

import pytest

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.agent.mcp_passthrough import (
    apply_mcp_header_passthrough,
    extract_passthrough_headers,
    merge_static_priority,
    resolve_placeholders,
    route_passthrough_headers,
)

TENANT = "tenant-1"
RUN = "run-1"


def _agent_record(**overrides):
    record = {
        "allow_mcp_header_passthrough": True,
        "strict_mcp_placeholder_resolution": False,
    }
    record.update(overrides)
    return record


@pytest.fixture
def agent_switch(monkeypatch):
    """Control what the per-agent switch lookup returns for one test."""
    state = {"record": _agent_record()}

    def _lookup(**_kwargs):
        record = state["record"]
        if isinstance(record, Exception):
            raise record
        return record

    from management.db.agent import repository

    monkeypatch.setattr(repository, "search_agent_info_by_agent_id", _lookup)
    return state


def _apply(hosts, metadata, *, version_no=4):
    apply_mcp_header_passthrough(
        hosts,
        metadata,
        agent_id=1,
        tenant_id=TENANT,
        version_no=version_no,
        run_id=RUN,
    )


# ---------------------------------------------------------------------------
# UT-BE-PASS-001 — global headers fan out to every MCP server
# ---------------------------------------------------------------------------

def test_ut_be_pass_001_global_headers_inject_into_every_server(agent_switch):
    hosts = [
        {"url": "http://a/mcp", "transport": "streamable-http",
         "headers": {"X-Tenant-ID": "t-1"}},
        {"url": "http://b/mcp", "transport": "streamable-http",
         "headers": {"Authorization": "Bearer server-token"}},
    ]

    _apply(hosts, {"_mcp_headers": {"Cookie": "sid=1", "X-User-Id": "u1"}})

    assert hosts[0]["headers"] == {
        "X-Tenant-ID": "t-1",
        "cookie": "sid=1",
        "x-user-id": "u1",
    }
    assert hosts[1]["headers"] == {
        "Authorization": "Bearer server-token",
        "cookie": "sid=1",
        "x-user-id": "u1",
    }


def test_ut_be_pass_001_extra_metadata_keys_do_not_leak_into_headers(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {}}]

    _apply(hosts, {"project_id": "P001", "_mcp_headers": {"Cookie": "sid=1"}})

    assert hosts[0]["headers"] == {"cookie": "sid=1"}


# ---------------------------------------------------------------------------
# UT-BE-PASS-002 — per-server URL routing
# ---------------------------------------------------------------------------

def test_ut_be_pass_002_by_server_headers_route_by_exact_url(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {}}, {"url": "http://b/mcp", "headers": {}}]

    _apply(hosts, {
        "_mcp_headers_by_server": {
            "http://a/mcp": {"Cookie": "sid=a"},
            "http://b/mcp": {"X-Trace-Id": "trace-9"},
        }
    })

    assert hosts[0]["headers"] == {"cookie": "sid=a"}
    assert hosts[1]["headers"] == {"x-trace-id": "trace-9"}


def test_ut_be_pass_002_by_server_wins_over_global_form(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {}}]

    _apply(hosts, {
        "_mcp_headers": {"Cookie": "global"},
        "_mcp_headers_by_server": {"http://a/mcp": {"Cookie": "routed"}},
    })

    assert hosts[0]["headers"] == {"cookie": "routed"}


def test_ut_be_pass_002_unmatched_server_url_raises_route_not_found(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {}}]

    with pytest.raises(AppException) as exc_info:
        _apply(hosts, {"_mcp_headers_by_server": {"http://other/mcp": {"Cookie": "s"}}})

    assert exc_info.value.error_code == ErrorCode.CHAT_MCP_HEADER_ROUTE_NOT_FOUND
    assert exc_info.value.details == {"unmatched_server_urls": ["http://other/mcp"]}
    assert exc_info.value.http_status == 400


def test_extract_and_route_helpers_normalize_header_keys():
    mode, headers = extract_passthrough_headers({"_mcp_headers": {"Cookie": "sid=1"}})
    assert mode == "global"
    assert route_passthrough_headers(mode, headers, "http://a/mcp") == {"cookie": "sid=1"}

    mode, headers = extract_passthrough_headers(
        {"_mcp_headers_by_server": {"http://a/mcp": {"X-User-Id": "u1"}}}
    )
    assert mode == "by_server"
    assert route_passthrough_headers(mode, headers, "http://b/mcp") == {}


# ---------------------------------------------------------------------------
# UT-BE-PASS-003 — agent switch OFF is a silent no-op
# ---------------------------------------------------------------------------

def test_ut_be_pass_003_switch_off_ignores_supplied_headers(agent_switch):
    agent_switch["record"] = _agent_record(allow_mcp_header_passthrough=False)
    hosts = [{"url": "http://a/mcp", "headers": {"X-Tenant-ID": "t-1"}}]

    _apply(hosts, {"_mcp_headers": {"Cookie": "sid=1"}})

    assert hosts[0]["headers"] == {"X-Tenant-ID": "t-1"}


def test_ut_be_pass_003_agent_lookup_failure_disables_passthrough(agent_switch):
    agent_switch["record"] = RuntimeError("database unavailable")
    hosts = [{"url": "http://a/mcp", "headers": {"X-Tenant-ID": "t-1"}}]

    _apply(hosts, {"_mcp_headers": {"Cookie": "sid=1"}})

    assert hosts[0]["headers"] == {"X-Tenant-ID": "t-1"}


# ---------------------------------------------------------------------------
# UT-BE-PASS-006 — static preset headers always win
# ---------------------------------------------------------------------------

def test_ut_be_pass_006_static_headers_win_case_insensitively(agent_switch):
    hosts = [{
        "url": "http://a/mcp",
        "headers": {"Cookie": "static-cookie", "Authorization": "Bearer static"},
    }]

    _apply(hosts, {"_mcp_headers": {
        "cookie": "dynamic-cookie",
        "Authorization": "Bearer dynamic",
        "X-User-Id": "u1",
    }})

    assert hosts[0]["headers"] == {
        "Cookie": "static-cookie",
        "Authorization": "Bearer static",
        "x-user-id": "u1",
    }


def test_merge_static_priority_never_emits_duplicate_case_variants():
    merged = merge_static_priority({"Cookie": "static"}, {"cookie": "dynamic", "X-New": "v"})

    assert merged == {"Cookie": "static", "X-New": "v"}
    assert len({key.lower() for key in merged}) == len(merged)


# ---------------------------------------------------------------------------
# UT-BE-PASS-008 — audit logs carry key names only, never values
# ---------------------------------------------------------------------------

def test_ut_be_pass_008_audit_logs_keys_without_values(agent_switch, caplog):
    caplog.set_level(logging.INFO, logger="northbound-mcp-passthrough")
    hosts = [{"url": "http://a/mcp", "headers": {"Cookie": "sid=${Cookie}"}}]

    _apply(hosts, {"_mcp_headers": {
        "Cookie": "sid=super-secret-value",
        "X-User-Id": "user-secret-value",
    }})

    text = caplog.text
    assert "event=passthrough_injected" in text
    assert "event=placeholder_resolved" in text
    assert "cookie" in text and "x-user-id" in text
    assert "super-secret-value" not in text
    assert "user-secret-value" not in text


def test_ut_be_pass_008_switch_off_audit_lists_raw_keys(agent_switch, caplog):
    caplog.set_level(logging.WARNING, logger="northbound-mcp-passthrough")
    agent_switch["record"] = _agent_record(allow_mcp_header_passthrough=False)
    hosts = [{"url": "http://a/mcp", "headers": {}}]

    _apply(hosts, {"_mcp_headers": {"Cookie": "sid=secret-cookie-value"}})

    text = caplog.text
    assert "reason=agent_switch_off" in text
    assert "cookie" in text
    assert "secret-cookie-value" not in text


# ---------------------------------------------------------------------------
# UT-BE-PASS-009 — backward compatibility when no reserved fields are sent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metadata", [None, {}, {"project_id": "P001"}])
def test_ut_be_pass_009_no_reserved_fields_leaves_mcp_host_untouched(agent_switch, metadata):
    hosts = [{"url": "http://a/mcp", "headers": {"X-Tenant-ID": "t-1"}}]

    _apply(hosts, metadata)

    assert hosts[0]["headers"] == {"X-Tenant-ID": "t-1"}


@pytest.mark.parametrize("mcp_host", [[], None, ["http://a/mcp"]])
def test_ut_be_pass_009_non_dict_or_empty_mcp_host_is_ignored(agent_switch, mcp_host):
    # Fallback string URLs carry no headers and must not raise.
    _apply(mcp_host, {"_mcp_headers": {"Cookie": "sid=1"}})


# ---------------------------------------------------------------------------
# UT-BE-PASS-010 — placeholder resolution (mixed literals + case folding)
# ---------------------------------------------------------------------------

def test_ut_be_pass_010_resolves_placeholders_and_keeps_literal_values():
    resolved, names, unresolved = resolve_placeholders(
        {
            "Cookie": "sid=${COOKIE}",
            "X-Mix": "Bearer ${X-User-Id}-v2",
            "X-Plain": "plain",
        },
        {"cookie": "abc", "x-user-id": "u1"},
        passthrough_allowed=True,
        run_id=RUN,
        agent_id=1,
        server_url="http://a/mcp",
    )

    assert resolved == {
        "Cookie": "sid=abc",
        "X-Mix": "Bearer u1-v2",
        "X-Plain": "plain",
    }
    assert names == ["cookie", "x-user-id"]
    assert unresolved == []


def test_ut_be_pass_010_passthrough_headers_feed_placeholder_context(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {"Authorization": "Bearer ${X-User-Id}"}}]

    _apply(hosts, {"_mcp_headers": {"X-User-Id": "u1"}})

    assert hosts[0]["headers"]["Authorization"] == "Bearer u1"


# ---------------------------------------------------------------------------
# UT-BE-PASS-011 — unresolved placeholders fail closed
# ---------------------------------------------------------------------------

def test_ut_be_pass_011_unresolved_placeholder_drops_the_whole_header():
    resolved, names, unresolved = resolve_placeholders(
        {"Cookie": "sid=${Cookie}", "X-Ok": "keep"},
        {},
        passthrough_allowed=True,
        run_id=RUN,
        agent_id=1,
        server_url="http://a/mcp",
    )

    assert resolved == {"X-Ok": "keep"}
    assert names == []
    assert unresolved == ["cookie"]
    assert "${" not in json.dumps(resolved)


def test_ut_be_pass_011_strict_mode_raises_placeholder_unresolved(agent_switch):
    agent_switch["record"] = _agent_record(strict_mcp_placeholder_resolution=True)
    hosts = [{"url": "http://a/mcp", "headers": {"Cookie": "sid=${Cookie}"}}]

    with pytest.raises(AppException) as exc_info:
        _apply(hosts, {"_mcp_headers": {"X-Request-Id": "req-1"}})

    assert exc_info.value.error_code == ErrorCode.CHAT_MCP_PLACEHOLDER_UNRESOLVED
    assert exc_info.value.details == {"unresolved_placeholders": ["cookie"]}
    assert exc_info.value.http_status == 400


def test_ut_be_pass_011_lenient_mode_keeps_running_without_the_header(agent_switch):
    hosts = [{"url": "http://a/mcp", "headers": {"Cookie": "sid=${Cookie}", "X-Keep": "v"}}]

    _apply(hosts, {})

    assert hosts[0]["headers"] == {"X-Keep": "v"}


# ---------------------------------------------------------------------------
# UT-BE-PASS-012 — $${Name} escapes to a literal, never resolves
# ---------------------------------------------------------------------------

def test_ut_be_pass_012_double_dollar_escapes_to_literal():
    resolved, names, unresolved = resolve_placeholders(
        {"X-Literal": "$${Cookie}"},
        {"cookie": "abc"},
        passthrough_allowed=True,
        run_id=RUN,
        agent_id=1,
        server_url="http://a/mcp",
    )

    assert resolved == {"X-Literal": "${Cookie}"}
    assert names == []
    assert unresolved == []


def test_ut_be_pass_012_switch_off_drops_real_placeholder_but_keeps_escapes():
    resolved, names, unresolved = resolve_placeholders(
        {"Cookie": "sid=${Cookie}", "X-Literal": "$${Cookie}", "X-Plain": "plain"},
        {"cookie": "abc"},
        passthrough_allowed=False,
        run_id=RUN,
        agent_id=1,
        server_url="http://a/mcp",
    )

    assert resolved == {"X-Literal": "${Cookie}", "X-Plain": "plain"}
    assert names == []
    assert unresolved == []
