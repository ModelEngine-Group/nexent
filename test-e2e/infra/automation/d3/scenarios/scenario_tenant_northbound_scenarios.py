"""D3 tenant deletion and Northbound API end-to-end scenarios."""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import json
from uuid import uuid4

import pytest

from d3.assets import model_id, get_test_asset, temporary_conversation
from shared.cases import case_params
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event, read_sse
from shared.postgres import postgres_scalar, postgres_sql
from shared.factories.ownership import register_owned_http
from shared.asset_registry import mark_asset_state


CASES = [
    "API-024", "API-025", "AGT-064", "AGT-065", "AGT-066", "AGT-067",
    "AGT-068", "AGT-069", "AGT-070", "API-153", "API-154", "API-158",
]


def _event_type(event: dict) -> str | None:
    data = event.get("data")
    return str(data.get("type")) if isinstance(data, dict) else None


def _payload(response):
    body = response.json()
    return body.get("data") if isinstance(body, dict) else None


async def _tenant_delete(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            missing = await api.delete("/tenants/not-a-real-tenant")
        # Never probe deletion safeguards against the live fixture tenant with an
        # authorized admin token: a regression there would destroy the test realm.
        async with client("config") as anonymous:
            protected = await anonymous.delete(f"/tenants/{identity.tenant_id}")
        assert_status(missing, (403, 404))
        assert_status(protected, 401)
        return
    async with client("config", token=identity.access_token) as api:
        created = await api.post(
            "/tenants",
            json={"tenant_name": f"d3-delete-{uuid4().hex[:8]}", "skill_ids": [], "skill_names": [], "locale": "zh"},
        )
    assert_status(created, 201)
    tenant = _payload(created) or {}
    tenant_id = str(tenant.get("tenant_id") or "")
    assert tenant_id
    register_owned_http(identity, 'owned_tenants', tenant_id, f'/tenants/{tenant_id}')
    async with client("config", token=identity.access_token) as api:
        deleted = await api.delete(f"/tenants/{tenant_id}")
        fetched = await api.get(f"/tenants/{tenant_id}")
        second_delete = await api.delete(f"/tenants/{tenant_id}")
    assert_status(deleted, 200)
    mark_asset_state('owned_tenants', tenant_id, 'DELETED')
    assert_status(fetched, (403, 404))
    assert_status(second_delete, (403, 404))


def _find_conversation_id(value) -> int | None:
    if isinstance(value, dict):
        for key in ("conversation_id", "conversationId"):
            if value.get(key) is not None:
                return int(value[key])
        for child in value.values():
            found = _find_conversation_id(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_conversation_id(child)
            if found is not None:
                return found
    return None


async def _nb_run(api_key: str, *, query: str, conversation_id: int | None = None,
                  model_override: int | None = None, headers: dict | None = None,
                  expected: int = 200, **extra) -> tuple[list[dict], int | None]:
    payload = {
        "conversation_id": conversation_id,
        "agent_name": str(get_test_asset("agents", "basic_name")),
        "query": query,
        "model_id": model_override,
        **extra,
    }
    async with client("northbound", api_key=api_key, timeout=MODEL_TIMEOUT, headers=headers or {}) as api:
        async with api.stream("POST", "/nb/v1/chat/run", json=payload) as response:
            if response.status_code != 200:
                await response.aread()
            assert_status(response, expected)
            if expected != 200:
                return [], None
            response_conversation_id = response.headers.get("conversation_id")
            events = await read_sse(response, limit=2000)
    conversation_id_from_events = _find_conversation_id(events)
    return events, (
        int(response_conversation_id)
        if response_conversation_id not in (None, "")
        else conversation_id_from_events
    )


async def _northbound_chat(api_key: str, identity, mode: str) -> None:
    if mode == "boundary":
        missing_id = absent_numeric_id(__name__ + ":AGT-065:rejected-chat")
        marker = "NB_REJECTED_" + uuid4().hex
        async with client("northbound", api_key="invalid-key") as api:
            denied = await api.get("/nb/v1/agents")
        assert_status(denied, 401)
        try:
            # The runtime masks inaccessible conversation IDs with HTTP 403.
            # Rejection must happen before persistence, not just before streaming.
            await _nb_run(api_key, query=marker, expected=403, conversation_id=missing_id)
            rows = int(postgres_scalar(
                f"SELECT count(*) FROM nexent.conversation_message_t WHERE conversation_id={missing_id}"
            ))
            assert rows == 0, f"Rejected chat persisted {rows} message(s) for a nonexistent conversation"
        finally:
            # This ID was proven globally absent before the request. Remove only
            # this probe's orphan marker, never any existing conversation data.
            postgres_sql(
                f"DELETE FROM nexent.conversation_message_t WHERE conversation_id={missing_id} "
                f"AND message_content='{marker}' AND NOT EXISTS "
                f"(SELECT 1 FROM nexent.conversation_record_t WHERE conversation_id={missing_id})"
            )
        return
    if mode == "dependency":
        events, _ = await _nb_run(
            api_key, query="Provider dependency failure probe", model_override=absent_numeric_id(__name__),
        )
        text = json.dumps(events, ensure_ascii=False).lower()
        assert "error" in text or "fail" in text
        return
    events, conversation_id = await _nb_run(
        api_key, query="Reply with the exact marker NB_D3_OK.", model_override=await model_id("llm", identity),
    )
    assert_terminal_event(events)
    assert "nb_d3_ok" in json.dumps(events, ensure_ascii=False).lower()
    assert conversation_id

    # Candidate V5 assertion 7: a NEW conversation run opens with the
    # conversation_created chunk and the header value must agree with it.
    assert events and _event_type(events[0]) == "conversation_created", (
        f"first SSE chunk of a new-conversation run must be conversation_created, got {_event_type(events[0])!r}"
    )
    created_payload = events[0]["data"].get("content") or {}
    assert int(created_payload.get("conversation_id")) == conversation_id, (
        f"conversation_created payload {created_payload} disagrees with header id {conversation_id}"
    )

    resumed, resumed_id = await _nb_run(
        api_key, query="Reply with NB_D3_RESUMED.", conversation_id=conversation_id,
    )
    assert_terminal_event(resumed)
    assert resumed_id in {None, conversation_id}
    # An EXISTING-conversation run must not repeat the conversation_created chunk.
    assert not any(_event_type(event) == "conversation_created" for event in resumed), (
        "existing-conversation run must not emit a conversation_created chunk"
    )


async def _northbound_metadata(api_key: str, valid: bool, owner) -> None:
    async with temporary_conversation(owner, "Northbound metadata probe") as conversation_id:
        await _northbound_metadata_in_conversation(api_key, valid, conversation_id)


async def _northbound_metadata_in_conversation(api_key: str, valid: bool, conversation_id: int) -> None:
    if not valid:
        events, _ = await _nb_run(
            api_key,
            conversation_id=conversation_id,
            query="metadata boundary",
            metadata={"nested": {"secret": "must-not-be-promoted"}},
            meta_data={"source": ["invalid-structure"]},
        )
        assert_terminal_event(events)
        return
    marker = uuid4().hex
    events, _ = await _nb_run(
        api_key,
        conversation_id=conversation_id,
        query="Reply NB_METADATA_OK.",
        headers={"Idempotency-Key": f"d3-{marker}"},
        metadata={"project_id": f"runtime-{marker}", "scope": "agent"},
        meta_data={"source": "d3", "audit_marker": marker},
    )
    assert_terminal_event(events)
    text = json.dumps(events, ensure_ascii=False).lower()
    assert "nb_metadata_ok" in text


async def _northbound_tool_params(api_key: str, valid: bool) -> None:
    agent_name = str(get_test_asset("agents", "basic_name"))
    if not valid:
        events, _ = await _nb_run(
            api_key,
            query="Reply NB_UNKNOWN_MAPPING_IGNORED.",
            tool_params={"agents": {agent_name: {"tools": {"not-a-real-tool": {"not_a_param": True}}}}},
        )
        assert_terminal_event(events)
        assert "nb_unknown_mapping_ignored" in json.dumps(events, ensure_ascii=False).lower()
        return
    events, _ = await _nb_run(
        api_key,
        query="Reply NB_TOOL_PARAMS_OK.",
        tool_params={"agents": {agent_name: {"tools": {}}}},
    )
    assert_terminal_event(events)
    assert "nb_tool_params_ok" in json.dumps(events, ensure_ascii=False).lower()


async def _northbound_queries(api_key: str, valid: bool, owner=None, outsider=None) -> None:
    async with client("northbound", api_key=api_key, timeout=MODEL_TIMEOUT) as api:
        health = await api.get("/nb/v1/health")
        if not valid:
            missing_agent = await api.get("/nb/v1/agents/not-a-real-agent")
            missing_id = absent_numeric_id(__name__ + ":API-154:missing-history")
            missing_history = await api.get(f"/nb/v1/conversations/{missing_id}")
            assert_status(health, 200)
            assert_status(missing_agent, 404)
            # Missing history is a successful empty collection. Do not reuse
            # another case's cached missing ID after a mutation probe.
            assert_status(missing_history, 200)
            assert missing_history.json()["data"] == {"conversation_id": missing_id, "history": []}
            marker = "NB_PRIVATE_" + uuid4().hex
            async with temporary_conversation(owner, "API-154 isolation") as conversation_id:
                events, _ = await _nb_run(api_key, query=f"Reply {marker}", conversation_id=conversation_id)
                assert_terminal_event(events)
                visible = await api.get(f"/nb/v1/conversations/{conversation_id}")
                assert_status(visible, 200)
                assert any(marker in row.get("content", "") for row in visible.json()["data"]["history"])
                async with client("config", token=outsider.access_token) as config:
                    created = await config.post("/user/tokens")
                    assert_status(created, 200)
                    credentials = created.json().get("data") or created.json()
                    try:
                        async with client("northbound", api_key=credentials["access_key"]) as foreign:
                            isolated = await foreign.get(f"/nb/v1/conversations/{conversation_id}")
                        assert_status(isolated, (200, 403, 404))
                        if isolated.status_code == 200:
                            assert isolated.json()["data"]["history"] == [], (
                                "Northbound history exposed the owner's messages to another tenant"
                            )
                    finally:
                        revoked = await config.delete(f"/user/tokens/{credentials['token_id']}")
                        assert_status(revoked, 200)
            return
        agents = await api.get("/nb/v1/agents")
        detail = await api.get(f"/nb/v1/agents/{get_test_asset('agents', 'basic_name')}")
        knowledge = await api.get(f"/nb/v1/agents/{get_test_asset('agents', 'basic_name')}/knowledge-bases")
        conversations = await api.get("/nb/v1/conversations")
        models = await api.get("/nb/v1/models")
    for response in (health, agents, detail, knowledge, conversations, models):
        assert_status(response, 200)
    assert str(get_test_asset("agents", "basic_name")) in agents.text
    assert isinstance(models.json(), (dict, list))


async def _monitoring(identity) -> None:
    async with client("config", token=identity.access_token) as api:
        status = await api.get("/monitoring/status")
        windows = [
            await api.get("/monitoring/models", params={"time_range": value, "page": 1, "page_size": 20})
            for value in ("24h", "7d", "30d")
        ]
        invalid = await api.get("/monitoring/models", params={"page": 0, "page_size": 101})
    assert_status(status, 200)
    for response in windows:
        assert_status(response, 200)
        assert isinstance(response.json().get("data"), list)
    assert_status(invalid, 422)
    assert {"telemetry_enabled", "provider", "dashboard_url"}.issubset(status.json().get("data") or {})


@pytest.mark.asyncio
async def execute_d3_tenant_northbound(case, tenant_a_admin, northbound_key, tenant_a_user, tenant_b_user):
    case_id = case["id"]
    if case_id in {"API-024", "API-025"}:
        await _tenant_delete(tenant_a_admin, case_id == "API-024")
    elif case_id in {"AGT-064", "AGT-065", "AGT-066"}:
        await _northbound_chat(
            northbound_key,
            tenant_a_admin,
            {"AGT-064": "core", "AGT-065": "boundary", "AGT-066": "dependency"}[case_id],
        )
    elif case_id in {"AGT-067", "AGT-068"}:
        await _northbound_metadata(northbound_key, case_id == "AGT-067", tenant_a_user)
    elif case_id in {"AGT-069", "AGT-070"}:
        await _northbound_tool_params(northbound_key, case_id == "AGT-069")
    elif case_id in {"API-153", "API-154"}:
        await _northbound_queries(northbound_key, case_id == "API-153", tenant_a_user, tenant_b_user)
    elif case_id == "API-158":
        await _monitoring(tenant_a_admin)
    else:
        raise AssertionError(f"unmapped D3 case {case_id}")
