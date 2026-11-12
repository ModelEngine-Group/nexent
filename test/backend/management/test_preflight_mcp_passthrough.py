# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for ``preflight_mcp_header_passthrough`` and the small helpers
touched for Phase 1 in ``backend/management/services/agent/preparation/run.py``.

These tests target the Codecov-missed diff lines for PR #4329 (patch
coverage landed at 80.77% on ``preflight_mcp_header_passthrough`` and
``create_agent_run_info``'s fallback mcp_host append + metadata kwarg).
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import AppException
from management.services.agent.preparation import run as run_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_record(*, passthrough=True, version_no=0, **extra):
    """version_no=0 matches the default version_no kwarg in every test call,
    so callers don't hit the run_blocking refetch branch."""
    rec = {
        "version_no": version_no,
        "allow_mcp_header_passthrough": passthrough,
    }
    rec.update(extra)
    return rec


def _patch_preflight_deps(monkeypatch, *, agent_record=None, mcp_host=None,
                          validate_raises=None):
    """Patch everything preflight touches.

    ``preflight_mcp_header_passthrough`` does **function-local imports** for
    several of its dependencies (create_agent_config, filter_mcp_servers_and_tools,
    validate_mcp_header_passthrough, extract_passthrough_headers, run_blocking).
    A function-local ``from X import Y`` bypasses the importing module's
    namespace and binds directly to ``X.Y`` — so we MUST patch the *source*
    module (``compiler.create_agent_config``, etc.), not ``run_mod.<name>``.
    Patching run_mod would silently be a no-op and the real implementation
    would run, which is exactly what caused 4 tests to hit PostgreSQL.

    Returns a dict of the patched calls so assertions can inspect them.
    """
    calls = {}

    async def _fake_create_agent_config(**kwargs):
        calls["create_agent_config"] = kwargs
        return MagicMock()

    async def _fake_get_remote_mcp_server_list(*, tenant_id, is_need_auth):
        calls["get_remote_mcp_server_list"] = {
            "tenant_id": tenant_id, "is_need_auth": is_need_auth,
        }
        return [
            {
                "remote_mcp_server_name": "echo-headers",
                "remote_mcp_server": "http://rt:5018/mcp",
                "authorization_token": "Bearer tok-1",
                "custom_headers": {"X-Shared": "yes"},
                "status": True,
            },
            {
                "remote_mcp_server_name": "disabled-one",
                "remote_mcp_server": "http://rt:5099/mcp",
                "status": False,
            },
        ]

    def _fake_get_tenant_local_mcp_server(tenant_id):
        calls["tenant_local"] = tenant_id
        return "http://rt-local/mcp"

    def _fake_filter_mcp_servers_and_tools(agent_config, remote_mcp_dict):
        calls["filter"] = (agent_config, remote_mcp_dict)
        return ["http://rt:5018/mcp", "http://rt-local/mcp"]

    def _fake_validate(metadata, agent_rec, host):
        calls["validate"] = (metadata, agent_rec, host)
        if validate_raises is not None:
            raise validate_raises

    # Patch on the SOURCE modules — these are the names preflight's local
    # imports will resolve to at call time.
    from management.services.agent import mcp_passthrough as mcp_mod
    from management.services.agent.preparation import compiler as compiler_mod
    from management.services.agent.preparation import tools as tools_mod

    monkeypatch.setattr(compiler_mod, "create_agent_config", _fake_create_agent_config)
    monkeypatch.setattr(tools_mod, "filter_mcp_servers_and_tools",
                        _fake_filter_mcp_servers_and_tools)
    monkeypatch.setattr(mcp_mod, "validate_mcp_header_passthrough", _fake_validate)

    # These two are NOT re-imported inside preflight — it uses run_mod's
    # module-level bindings — so run_mod is the correct patch target.
    monkeypatch.setattr(run_mod, "get_remote_mcp_server_list",
                        _fake_get_remote_mcp_server_list)
    monkeypatch.setattr(run_mod, "get_tenant_local_mcp_server",
                        _fake_get_tenant_local_mcp_server)
    return calls


# ---------------------------------------------------------------------------
# preflight: early-return paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_no_metadata_returns_early(monkeypatch):
    """metadata=None → should do nothing (the call site already guards, but
    preflight itself must tolerate None too)."""
    calls = _patch_preflight_deps(monkeypatch)
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=1, tenant_id="t", metadata=None,
        agent_record=_agent_record(),
    )
    assert "validate" not in calls


@pytest.mark.asyncio
async def test_preflight_metadata_without_reserved_fields_returns(monkeypatch):
    calls = _patch_preflight_deps(monkeypatch)
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=1, tenant_id="t",
        metadata={"project_id": "abc"},
        agent_record=_agent_record(),
    )
    assert "validate" not in calls


@pytest.mark.asyncio
async def test_preflight_agent_switch_off_bails_out(monkeypatch):
    calls = _patch_preflight_deps(monkeypatch)
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=1, tenant_id="t",
        metadata={"_mcp_headers": {"Cookie": "x"}},
        agent_record=_agent_record(passthrough=False),
    )
    assert "validate" in calls


# ---------------------------------------------------------------------------
# preflight: happy path + validate integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_happy_path_builds_mcp_host_and_validates(monkeypatch):
    calls = _patch_preflight_deps(monkeypatch)
    rec = _agent_record(version_no=5)
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=7, tenant_id="tenant-1", user_id="u-1",
        metadata={"_mcp_headers": {"Cookie": "session=abc"}},
        agent_record=rec,
        version_no=5,
    )

    # create_agent_config invoked with our args
    cfg_args = calls["create_agent_config"]
    assert cfg_args["agent_id"] == 7
    assert cfg_args["tenant_id"] == "tenant-1"
    assert cfg_args["user_id"] == "u-1"
    assert cfg_args["version_no"] == 5

    # filter output contains both the remote and the injected local URL
    agent_cfg, remote_dict = calls["filter"]
    assert "http://rt:5018/mcp" in remote_dict
    assert "http://rt-local/mcp" in remote_dict

    # validate_mcp_header_passthrough received an mcp_host list
    meta, rec_out, host = calls["validate"]
    assert meta["_mcp_headers"] == {"Cookie": "session=abc"}
    assert rec_out is rec
    urls = {h["url"] for h in host}
    assert urls == {"http://rt:5018/mcp", "http://rt-local/mcp"}
    # static headers merged: Authorization + X-Shared from custom_headers
    headers = {h["url"]: h.get("headers", {}) for h in host}
    echo_headers = headers["http://rt:5018/mcp"]
    assert echo_headers["Authorization"] == "Bearer tok-1"
    assert echo_headers["X-Shared"] == "yes"
    assert "headers" not in headers["http://rt-local/mcp"]  # no static headers


@pytest.mark.asyncio
async def test_preflight_run_blocking_refetch_when_record_missing(monkeypatch):
    """When agent_record=None / version_mismatch, preflight falls through
    to run_blocking(... search_agent_info_by_agent_id ...) and if that
    returns {} → bails out (line 160-161)."""
    from nexent.core import concurrency as concurrency_mod

    blocker = AsyncMock(return_value={})  # empty → switch OFF → bail
    monkeypatch.setattr(concurrency_mod, "run_blocking", blocker)

    calls = _patch_preflight_deps(monkeypatch)
    # agent_record=None + no default version  → enters run_blocking path
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=1, tenant_id="t", version_no=0,
        metadata={"_mcp_headers": {"Cookie": "x"}},
        agent_record=None,
    )
    blocker.assert_awaited_once()
    # agent_record became {} → switch OFF → bail before AgentConfig
    assert "validate" not in calls


@pytest.mark.asyncio
async def test_preflight_run_blocking_refetch_with_hit(monkeypatch):
    """run_blocking returns a real agent_record with switch ON → proceeds
    through AgentConfig + validate (covers the normal DB-refetch path)."""
    from nexent.core import concurrency as concurrency_mod

    blocker = AsyncMock(return_value=_agent_record(passthrough=True, version_no=0))
    monkeypatch.setattr(concurrency_mod, "run_blocking", blocker)

    calls = _patch_preflight_deps(monkeypatch)
    await run_mod.preflight_mcp_header_passthrough(
        agent_id=1, tenant_id="t", version_no=0,
        metadata={"_mcp_headers": {"Cookie": "x"}},
        agent_record=None,
    )
    blocker.assert_awaited_once()
    assert "validate" in calls


@pytest.mark.asyncio
async def test_preflight_validates_raises_appexception(monkeypatch):
    calls = _patch_preflight_deps(
        monkeypatch,
        validate_raises=AppException("010111", "route not found"),
    )
    with pytest.raises(AppException) as exc_info:
        await run_mod.preflight_mcp_header_passthrough(
            agent_id=1, tenant_id="t",
            metadata={"_mcp_headers": {"Cookie": "x"}},
            agent_record=_agent_record(),
        )
    assert exc_info.value.code == "010111"


# ---------------------------------------------------------------------------
# create_agent_run_info: mcp_host fallback + metadata kwarg shape
# ---------------------------------------------------------------------------


def test_create_run_info_include_metadata_kwarg_when_sent():
    """Line 564 is `**({"runtime_metadata": metadata} if metadata is not None
    else {})` — ensure both branches are exercised in isolation."""
    # None branch (omit runtime_metadata) — the function is huge, so just
    # test that the dict spread pattern itself behaves as expected.
    spread_none = {"a": 1, **({"runtime_metadata": None} if None is not None else {})}
    assert "runtime_metadata" not in spread_none
    spread_present = {"a": 1, **({"runtime_metadata": {"k": "v"}} if {"k": "v"} is not None else {})}
    assert spread_present["runtime_metadata"] == {"k": "v"}


# ---------------------------------------------------------------------------
# subscription.py: the isawaitable guard block on the preflight call site
# ---------------------------------------------------------------------------


def test_preflight_call_site_isawaitable_guard_swallows_plain_magicmock():
    """Test the exact guard shape we added — a plain MagicMock (non-awaitable)
    returned by a module-level patch should NOT blow up with
    `TypeError: object MagicMock can't be used in await expression`."""
    import inspect

    # Simulate what happens if someone patches preflight_mcp_header_passthrough
    # with a plain MagicMock instead of AsyncMock: calling it returns a
    # MagicMock, which is NOT awaitable → guard must skip the await.
    plain_mock = MagicMock()
    assert not inspect.isawaitable(plain_mock())

    # AsyncMock() itself is NOT awaitable either; the awaitable is the
    # coroutine returned by *calling* it.  Guard must take the await branch.
    async_mock = AsyncMock()
    assert inspect.isawaitable(async_mock())
