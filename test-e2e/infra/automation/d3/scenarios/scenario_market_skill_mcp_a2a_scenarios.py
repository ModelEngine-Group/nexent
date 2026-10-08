"""D3 marketplace, NL2Skill, MCP-Agent and local/external A2A scenarios."""

from __future__ import annotations
from shared.factories.mcp import _ensure_mcp_agent
from shared.resource_ids import absent_numeric_id

import json
import os
import uuid

import pytest

from d3.assets import get_test_asset
from shared.factories.agent import _draft_agent
from shared.asset_registry import AssetDependencyError, register_asset, resolve_asset
from shared.cases import case_params
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event, read_sse


CASES = [
    "CTR-018", "CTR-019", "API-071", "API-074", "API-075", "API-081", "API-082",
    "AGT-040", "AGT-041", "CTR-028", "CTR-029", "CTR-030",
    "CTR-031", "CTR-032", "CTR-033", "CTR-036", "CTR-037", "CTR-038",
    "API-094", "API-095", "API-096",
]


def _policy_skip(case_id: str) -> None:
    pytest.skip(f"SKIPPED_BY_POLICY: {case_id}: external A2A service Journey is excluded by the declared daily policy")


async def _a2a_card(valid: bool) -> None:
    endpoint_id = str(get_test_asset("a2a", "local_endpoint_id"))
    async with client("northbound", timeout=MODEL_TIMEOUT) as api:
        response = await api.get(f"/nb/a2a/{endpoint_id}/.well-known/agent-card.json")
    if valid:
        assert_status(response, 200)
        card = response.json()
        assert card.get("name") and card.get("url")
        assert card.get("version") or card.get("protocolVersion")
    else:
        async with client("northbound") as api:
            missing = await api.get("/nb/a2a/not-present/.well-known/agent-card.json")
        assert_status(missing, 404)




async def _repository_list(identity) -> None:
    async with client("config", token=identity.access_token) as api:
        listing = await api.get("/repository/agent", params={"page": 1, "page_size": 20, "search": ""})
        mine = await api.get("/repository/agent/mine", params={"ownership": "all", "page": 1, "page_size": 20})
    assert_status(listing, 200)
    assert_status(mine, 200)
    assert isinstance(listing.json(), dict) and isinstance(mine.json(), dict)


async def _repository_import(identity, valid: bool) -> None:
    async with client("config", token=identity.access_token) as api:
        if not valid:
            precheck = await api.get(f"/repository/agent/{absent_numeric_id(__name__)}/import_precheck")
            imported = await api.post(f"/repository/agent/{absent_numeric_id(__name__)}/import", json=[])
            assert_status(precheck, 400)
            assert_status(imported, 404)
            return
        repository_id=resolve_asset('repository','agent_listing_id',required=False,consumer_case_id='API-074')
        if repository_id is None:
            from shared.factories.repository import prepare_agent_listing
            from shared.auth import sign_in
            repository_id=await prepare_agent_listing(await sign_in('tenant_a_dev'),await sign_in('tenant_a_admin'))
        repository_id=int(repository_id)
        precheck = await api.get(f"/repository/agent/{repository_id}/import_precheck")
        assert_status(precheck, 200)
        resolutions = precheck.json().get("skill_resolutions") or []
        imported = await api.post(f"/repository/agent/{repository_id}/import", json=resolutions)
        assert_status(imported, 200)
        imported_id = imported.json().get("agent_id")
        if imported_id:
            cleanup = await api.request("DELETE", "/agent", json={"agent_id": imported_id})
            assert_status(cleanup, 200)


async def _skill_instance(identity, valid: bool) -> None:
    agent_id = int(get_test_asset("agents", "skill_id"))
    skill_id = int(get_test_asset("skills", "configurable_id"))
    async with client("config", token=identity.access_token) as api:
        if valid:
            before = await api.get("/skills/instance", params={
                "agent_id": agent_id, "skill_id": skill_id, "version_no": 0,
            })
            original = before.json().get("config_values", {}) if before.status_code == 200 else {}
            updated = await api.post("/skills/instance/update", json={
                "agent_id": agent_id, "skill_id": skill_id, "enabled": True,
                "config_values": {**original, "d3_marker": "configured"}, "version_no": 0,
            })
            assert_status(updated, 200)
            listed = await api.get("/skills/instance/list", params={"agent_id": agent_id, "version_no": 0})
            assert_status(listed, 200)
            restored = await api.post("/skills/instance/update", json={
                "agent_id": agent_id, "skill_id": skill_id, "enabled": True,
                "config_values": original, "version_no": 0,
            })
            assert_status(restored, 200)
        else:
            missing = await api.post("/skills/instance/update", json={
                "agent_id": absent_numeric_id(__name__), "skill_id": absent_numeric_id(__name__),
                "enabled": True, "config_values": {}, "version_no": 1,
            })
            assert missing.status_code in {400, 404}


def _assert_nl2skill_done(events: list[dict]) -> None:
    """NL2Skill emits JSON ``type=done`` inside ordinary SSE messages."""
    assert events, "NL2Skill returned no SSE events"
    assert not any(
        str(event.get("event", "")).lower() == "error"
        or (
            isinstance(event.get("data"), dict)
            and str(event["data"].get("type", "")).lower() == "error"
        )
        for event in events
    ), "NL2Skill emitted an error event"
    assert any(
        str(event.get("event", "")).lower() == "done"
        or (
            isinstance(event.get("data"), dict)
            and str(event["data"].get("type", "")).lower() == "done"
        )
        for event in events
    ), "NL2Skill stream ended without a done event"


async def _nl2skill(valid: bool) -> None:
    from shared.auth import sign_in

    # The product route requires skill:create; the ordinary tenant user does
    # not have that permission, so use the configured creator account.
    identity = await sign_in("tenant_a_admin")
    payload = {
        "query": "Create a skill that extracts uppercase words from text." if valid else "",
        "history": [], "draft_snapshot": None, "complexity": "simple", "language": "en",
    }
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream("POST", "/skills/nl2skill/run", json=payload) as response:
            if not valid:
                assert_status(response, 422)
                return
            assert_status(response, 200)
            events = await read_sse(response, limit=2000)
    _assert_nl2skill_done(events)
    assert "skill" in json.dumps(events, ensure_ascii=False).lower()


async def _mcp_agent(identity, mode: str) -> None:
    await _ensure_mcp_agent(identity)
    agent_key = "mcp_id" if mode != "outage" else "mcp_outage_id"
    agent_id = int(get_test_asset("agents", agent_key))
    payload = {
        "query": "Call deterministic_add with left=19 and right=23, then return MCP-D3-42 and the result 42.",
        "agent_id": agent_id, "history": [], "is_debug": True,
        "metadata": {"trace_marker": "MCP-D3-42"},
    }
    if mode == "invalid":
        payload["tool_params"] = {"agents": {"mcp_agent": {"tools": {"echo": {"unknown": True}}}}}
    service_id = int(get_test_asset("mcp", "service_id"))
    if mode == "outage":
        async with client("config", token=identity.access_token) as config_api:
            disabled = await config_api.post("/mcp/disable", json={"mcp_id": service_id})
        assert_status(disabled, 200)
    try:
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/agent/run", json=payload) as response:
                assert_status(response, 200)
                events = await read_sse(response, limit=2000)
    finally:
        if mode == "outage":
            async with client("config", token=identity.access_token) as config_api:
                enabled = await config_api.post("/mcp/enable", json={"mcp_id": service_id})
            assert_status(enabled, 200)
    assert_terminal_event(events)
    text = json.dumps(events, ensure_ascii=False).lower()
    if mode == "core":
        assert "mcp-d3-42" in text and ("tool" in text or "observation" in text)
    elif mode == "outage":
        event_kinds = [
            (event.get("event"),
             event.get("data", {}).get("type") if isinstance(event.get("data"), dict) else None,
             event.get("data", {}).get("tool_name") if isinstance(event.get("data"), dict) else None)
            for event in events
        ]
        assert "error" in text or "unavailable" in text or "timeout" in text, (
            f"disabled MCP service produced no failure event; event kinds={event_kinds}"
        )
    else:
        # Current runtime contract ignores unknown nested tool mappings and
        # continues with the known MCP schema; it does not reject them as 4xx.
        assert_terminal_event(events)


async def _local_a2a_settings(identity) -> None:
    agent_id = int(get_test_asset("agents", "local_a2a_id"))
    async with client("config", token=identity.access_token) as api:
        before = await api.get(f"/a2a/management/agents/{agent_id}/settings")
        assert_status(before, 200)
        original = before.json().get("data") or {}
        enabled = await api.post(f"/a2a/management/agents/{agent_id}/enable", json={})
        assert_status(enabled, 200)
        changed = await api.put(f"/a2a/management/agents/{agent_id}/settings", json={
            "card_overrides": {"description": "D3 local A2A contract"},
        })
        assert_status(changed, 200)
        listed = await api.get("/a2a/management/agents")
        assert_status(listed, 200)
        if original.get("is_enabled"):
            restored = await api.put(f"/a2a/management/agents/{agent_id}/settings", json={
                "is_enabled": True, "card_overrides": original.get("card_overrides") or {},
            })
        else:
            restored = await api.post(f"/a2a/management/agents/{agent_id}/disable")
        assert_status(restored, 200)


@pytest.mark.asyncio
async def execute_market_skill_mcp_a2a_scenario(case: dict, tenant_a_user) -> None:
    case_id = case["id"]
    if case_id in {"CTR-031", "CTR-032", "CTR-033", "CTR-036", "CTR-037", "CTR-038", "API-094", "API-095"}:
        _policy_skip(case_id)
    handlers = {
        "CTR-018": lambda: _a2a_card(True),
        "CTR-019": lambda: _a2a_card(False),
        "API-071": lambda: _repository_list(tenant_a_user),
        "API-074": lambda: _repository_import(tenant_a_user, True),
        "API-075": lambda: _repository_import(tenant_a_user, False),
        "API-081": lambda: _skill_instance(tenant_a_user, True),
        "API-082": lambda: _skill_instance(tenant_a_user, False),
        "AGT-040": lambda: _nl2skill(True),
        "AGT-041": lambda: _nl2skill(False),
        "CTR-028": lambda: _mcp_agent(tenant_a_user, "core"),
        "CTR-029": lambda: _mcp_agent(tenant_a_user, "invalid"),
        "CTR-030": lambda: _mcp_agent(tenant_a_user, "outage"),
        "API-096": lambda: _local_a2a_settings(tenant_a_user),
    }
    await handlers[case_id]()
