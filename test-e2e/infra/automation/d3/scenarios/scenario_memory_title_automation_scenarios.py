"""D3 conversation title, Memory and natural-language automation scenarios."""

from __future__ import annotations
from shared.factories.memory import _create_agent_memory
from shared.resource_ids import absent_numeric_id

import asyncio
import json
from uuid import uuid4

import pytest

from d3.assets import model_id, temporary_conversation, get_test_asset
from shared.cases import case_params
from shared.asset_registry import register_asset
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.factories.tenant import isolated_accounts
from shared.sse import assert_terminal_event, read_sse


CASES = [
    "AGT-047", "AGT-048", "API-118", "API-119", "API-120", "API-121",
    "API-122", "API-123", "AGT-049", "AGT-050", "AGT-051", "AGT-052",
    "AGT-053", "AGT-054", "AGT-055", "AGT-056",
]


async def _conversation_title(identity, dependency_failure: bool) -> None:
    async with temporary_conversation(identity, "D3 title before generation") as conversation_id:
        question = "" if dependency_failure else "How can I configure a private knowledge base?"
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            generated = await api.post(
                "/conversation/generate_title", json={"conversation_id": conversation_id, "question": question},
            )
            history = await api.get(f"/conversation/{conversation_id}")
        assert_status(generated, 200)
        title = generated.json().get("data")
        assert isinstance(title, str) and title.strip()
        assert_status(history, 200)
        serialized = json.dumps(history.json().get("data"), ensure_ascii=False)
        assert title in serialized


async def _memory_config(identity, valid: bool) -> None:
    marker = f"d3-agent-{uuid4().hex[:8]}"
    async with client("config", token=identity.access_token) as api:
        if not valid:
            unsupported = await api.post("/memory/config/set", json={"key": "NOT_A_MEMORY_KEY", "value": True})
            share = await api.post("/memory/config/set", json={"key": "MEMORY_AGENT_SHARE", "value": "invalid"})
            assert_status(unsupported, 406)
            assert_status(share, 406)
            return
        before = await api.get("/memory/config/load")
        embedding = await api.get("/memory/config/embedding-status")
        enabled = await api.post("/memory/config/set", json={"key": "MEMORY_SWITCH", "value": True})
        dreaming = await api.post("/memory/config/dreaming", json={"enabled": True, "delete_history": False})
        disabled = await api.post("/memory/config/disable_agent", json={"agent_id": marker})
        disabled_useragent = await api.post("/memory/config/disable_useragent", json={"agent_id": marker})
        after = await api.get("/memory/config/load")
        restored = await api.delete(f"/memory/config/disable_agent/{marker}")
        restored_useragent = await api.delete(f"/memory/config/disable_useragent/{marker}")
        restore_responses = []
        for key in ("MEMORY_SWITCH", "DREAMING_SWITCH"):
            if key in before.json():
                restore_responses.append(await api.post("/memory/config/set", json={"key": key, "value": before.json()[key]}))
    for response in (before, embedding, enabled, dreaming, disabled, disabled_useragent, after, restored, restored_useragent):
        assert_status(response, 200)
    assert isinstance(before.json(), dict) and isinstance(after.json(), dict)
    assert "configured" in embedding.json()
    for response in restore_responses:
        assert_status(response, 200)


async def _memory_config_isolated() -> None:
    async with isolated_accounts(["tenant_a_user"]) as accounts:
        await _memory_config(accounts["tenant_a_user"], True)




async def _memory_records(identity, valid: bool) -> None:
    if not valid:
        async with client("runtime", token=identity.access_token) as api:
            gone = await api.post("/memory/records", json={"layer": "user", "content": "legacy path"})
        async with client("config", token=identity.access_token) as api:
            missing = await api.get(f"/memory/records/{absent_numeric_id(__name__)}")
            invalid = await api.post("/memory/records", json={"layer": "agent", "content": ""})
        assert_status(gone, (404, 410))
        assert_status(missing, 404)
        assert_status(invalid, 422)
        return
    marker = f"MEMORY-{uuid4().hex[:10]}"
    memory_id_value = await _create_agent_memory(identity, marker)
    try:
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            fetched = await api.get(f"/memory/records/{memory_id_value}")
            listed = await api.get("/memory/records", params={"layer": "agent", "agent_id": get_test_asset("agents", "basic_id")})
            updated = await api.patch(f"/memory/records/{memory_id_value}", json={"content": f"Updated {marker}", "concept_tags": ["d3", "updated"]})
            searched = await api.post(
                "/memory/records/search",
                json={"query": marker, "agent_id": str(get_test_asset("agents", "basic_id")), "layers": ["agent"], "top_k": 10, "threshold": 0.0, "hybrid": True},
            )
        for response in (fetched, listed, updated, searched):
            assert_status(response, 200)
        assert str(memory_id_value) in json.dumps(listed.json())
        assert marker.lower() in json.dumps(searched.json(), ensure_ascii=False).lower()
    finally:
        async with client("config", token=identity.access_token) as api:
            deleted = await api.delete(f"/memory/records/{memory_id_value}")
        assert_status(deleted, (200, 400))


async def _long_term_memory(admin, user, valid: bool) -> None:
    if not valid:
        async with client("config", token=user.access_token) as api:
            forbidden = await api.post("/memory/long-term/tenant/versions", json={"content": "not allowed"})
            missing = await api.get(f"/memory/long-term/user/versions/{absent_numeric_id(__name__)}")
            invalid_scope = await api.get("/memory/long-term/invalid")
        assert_status(forbidden, 403)
        assert_status(missing, 404)
        assert_status(invalid_scope, 422)
        return
    marker = f"# D3 long-term {uuid4().hex[:10]}"
    async with client("config", token=admin.access_token) as api:
        active = await api.get("/memory/long-term/tenant")
        versions = await api.get("/memory/long-term/tenant/versions")
        prior = active.json().get("version") or {}
        prior_version_id = prior.get("version_id")
        if not prior_version_id:
            pytest.skip("tenant long-term mutation requires an existing baseline version that can be restored")
        created = await api.post(
            "/memory/long-term/tenant/versions",
            json={"content": marker, "expected_active_version_id": prior_version_id},
        )
        assert_status(created, 201)
        version_id = created.json().get("version_id") or created.json().get("id")
        try:
            fetched = await api.get(f"/memory/long-term/tenant/versions/{version_id}")
            activated = await api.post(
                f"/memory/long-term/tenant/versions/{version_id}/activate",
                json={"expected_active_version_id": version_id},
            )
        finally:
            restored = await api.post(
                f"/memory/long-term/tenant/versions/{prior_version_id}/activate",
                json={"expected_active_version_id": version_id},
            )
            assert_status(restored, 200)
    for response in (active, versions, fetched, activated):
        assert_status(response, 200)
    assert marker in json.dumps(fetched.json(), ensure_ascii=False)
    assert active.headers.get("cache-control") == "no-store, no-cache, must-revalidate"


async def _long_term_memory_isolated() -> None:
    async with isolated_accounts(["tenant_a_admin", "tenant_a_user"]) as accounts:
        await _long_term_memory(accounts["tenant_a_admin"], accounts["tenant_a_user"], True)


async def _dreaming(identity, dependency_failure: bool) -> None:
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        if dependency_failure:
            invalid = await api.put(
                "/memory/dreaming/schedule",
                json={"enabled": True, "rule_type": "CRON", "timezone": "Invalid/Timezone", "cron_expr": "not cron"},
            )
            assert_status(invalid, 422)
            return
        params = await api.get("/memory/dreaming/parameters")
        schedule = await api.get("/memory/dreaming/schedule")
        updated = await api.put(
            "/memory/dreaming/schedule",
            json={"enabled": False, "rule_type": "CRON", "timezone": "Asia/Shanghai", "cron_expr": "0 3 * * *"},
        )
        run = await api.post("/memory/dreaming/run", json={})
        assert_status(run, 202)
        run_id = run.json().get("run_id")
        audit = await api.get("/memory/dreaming/audit", params={"run_id": run_id, "limit": 20})
        original = schedule.json()
        restore_payload = {
            "enabled": bool(original.get("enabled", False)),
            "rule_type": original.get("rule_type") or "CRON",
            "timezone": original.get("timezone") or "Asia/Shanghai",
            "cron_expr": original.get("cron_expr"),
            "interval_seconds": original.get("interval_seconds"),
            "start_at": original.get("start_at"),
            "min_score": original.get("min_score"),
            "min_recall_count": original.get("min_recall_count"),
            "min_unique_queries": original.get("min_unique_queries"),
            "source_limit": original.get("source_limit"),
            "long_term_max_chars": original.get("long_term_max_chars"),
            "summarization_max_attempts": original.get("summarization_max_attempts"),
        }
        restore_payload = {key: value for key, value in restore_payload.items() if value is not None}
        restored = await api.put("/memory/dreaming/schedule", json=restore_payload)
    for response in (params, schedule, updated, audit):
        assert_status(response, 200)
    assert run_id and str(run_id) in json.dumps(audit.json())
    assert_status(restored, 200)
    return int(run_id)


async def _dreaming_isolated() -> None:
    # A real manual run writes schedule/audit records.  Give it a fresh tenant
    # and user so it cannot reuse or change another test's Dreaming state.
    async with isolated_accounts(["tenant_a_admin", "tenant_a_user"]) as accounts:
        identity = accounts["tenant_a_user"]
        try:
            run_id = await _dreaming(identity, False)
            for _ in range(60):
                async with client("config", token=identity.access_token) as api:
                    audit = await api.get("/memory/dreaming/audit", params={"run_id": run_id, "limit": 1})
                assert_status(audit, 200)
                rows = audit.json()
                if rows and str(rows[0].get("status", "")).lower() in {"completed", "failed", "skipped"}:
                    break
                await asyncio.sleep(2)
            else:
                raise AssertionError("owned Dreaming run did not reach a terminal state before cleanup")
        finally:
            async with client("config", token=identity.access_token) as api:
                disabled = await api.post(
                    "/memory/config/dreaming",
                    json={"enabled": False, "delete_history": True},
                )
            assert_status(disabled, 200)


async def _memory_agent_context(identity, mode: str) -> None:
    if mode == "boundary":
        async with client("config", token=identity.access_token) as api:
            invalid = await api.get("/memory/context", params={"top_k": 0, "threshold": 2})
        assert_status(invalid, 422)
        return
    if mode == "dependency":
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post(
                "/memory/records/search",
                json={"query": "embedding failure probe", "layers": ["agent"], "top_k": 5, "threshold": 0.0},
            )
        assert_status(response, (200, 409, 500, 502, 503, 504))
        return
    marker = f"CTXMEM{uuid4().hex[:10]}"
    memory_id_value = await _create_agent_memory(identity, marker, require_indexed=True)
    try:
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            for attempt in range(10):
                context = await api.get(
                    "/memory/context",
                    params={"query": f"Remember exact marker {marker}", "agent_id": str(get_test_asset("agents", "basic_id")), "layers": "agent", "top_k": 10, "threshold": 0.0},
                )
                assert_status(context, 200)
                if marker.lower() in context.json().get("prompt_text", "").lower():
                    break
                if attempt < 9:
                    await asyncio.sleep(1)
        assert marker.lower() in context.json().get("prompt_text", "").lower(), context.json()
        async with temporary_conversation(identity, "D3 memory context") as conversation_id:
            async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                async with api.stream(
                    "POST", "/agent/run",
                    json={"query": f"Repeat memory marker {marker}", "agent_id": int(get_test_asset("agents", "basic_id")), "conversation_id": conversation_id, "history": [], "is_debug": True},
                ) as response:
                    assert_status(response, 200)
                    events = await read_sse(response, limit=2000)
            assert_terminal_event(events)
            assert marker.lower() in json.dumps(events, ensure_ascii=False).lower()
    finally:
        async with client("config", token=identity.access_token) as api:
            await api.delete(f"/memory/records/{memory_id_value}")


async def _automation(identity, mode: str) -> None:
    if mode == "boundary":
        async with client("runtime", token=identity.access_token) as api:
            invalid = await api.post("/agent/automations/proposals", json={"agent_id": 0, "message": "", "timezone": "Invalid/Timezone"})
            missing = await api.post(f"/agent/automations/proposals/{absent_numeric_id(__name__)}/confirm", json={})
        assert_status(invalid, 422)
        assert_status(missing, 404)
        return
    if mode == "dependency":
        async with temporary_conversation(identity, "D3 automation failure") as conversation_id:
            async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                response = await api.post(
                    "/agent/automations/proposals",
                    json={"conversation_id": conversation_id, "agent_id": int(get_test_asset("agents", "basic_id")), "message": "Every day at 03:00 do a health check", "timezone": "Asia/Shanghai", "model_id": absent_numeric_id(__name__)},
                )
            assert_status(response, (200, 400, 404, 500, 502, 503, 504))
        return
    # The task is linked to its conversation.  A temporary conversation would
    # cascade-delete the task before D2 can consume it, so retain both assets
    # for the whole batch and let the registry clean them in reverse order.
    async with client("runtime", token=identity.access_token) as api:
        created = await api.put("/conversation/create", json={"title": "D3 automation"})
    assert_status(created, 200)
    conversation_id = int(created.json()["data"]["conversation_id"])
    register_asset(
        "automation", "conversation_id", conversation_id, owner_case_id="AGT-054",
        cleanup={
            "service": "runtime", "identity": "tenant_a_user", "method": "DELETE",
            "path": f"/conversation/{conversation_id}", "allowed_statuses": [200, 404],
        },
    )

    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        proposal = await api.post(
            "/agent/automations/proposals",
            json={
                "conversation_id": conversation_id, "agent_id": int(get_test_asset("agents", "basic_id")),
                "message": "Every day at 03:00 reply with the exact marker D3_AUTOMATION_OK.",
                "timezone": "Asia/Shanghai", "model_id": await model_id("llm", identity),
            },
        )
        assert_status(proposal, 200)
        data = proposal.json().get("data") or {}
        proposal_id = data.get("proposal_id")
        assert proposal_id and data.get("executable") is True
        confirmed = await api.post(f"/agent/automations/proposals/{proposal_id}/confirm", json={})
        assert_status(confirmed, 200)
        task_id = (confirmed.json().get("data") or {}).get("task_id")
        assert task_id
        listing = await api.get("/agent/automations", params={"page": 1, "page_size": 20})
        linked = await api.get(f"/conversation/{conversation_id}/automation")
    assert_status(listing, 200)
    assert_status(linked, 200)
    detail = None
    for _ in range(20):
        async with client("runtime", token=identity.access_token) as api:
            detail = await api.get(f"/agent/automations/{task_id}")
        if detail.status_code == 200:
            break
        assert_status(detail, (200, 404))
        await asyncio.sleep(1)
    assert detail is not None
    assert_status(detail, 200)
    register_asset(
        "automation", "seeded_task_id", int(task_id), owner_case_id="AGT-054",
        cleanup={
            "service": "runtime", "identity": "tenant_a_user", "method": "DELETE",
            "path": f"/agent/automations/{task_id}", "allowed_statuses": [200, 404],
        },
    )
    register_asset(
        "reliability", "scheduler_task_id", int(task_id), owner_case_id="AGT-054",
    )


@pytest.mark.asyncio
async def execute_d3_memory_title_automation(case, tenant_a_admin, tenant_a_user):
    case_id = case["id"]
    if case_id in {"AGT-047", "AGT-048"}:
        await _conversation_title(tenant_a_user, case_id == "AGT-048")
    elif case_id in {"API-118", "API-119"}:
        if case_id == "API-118":
            await _memory_config_isolated()
        else:
            await _memory_config(tenant_a_user, False)
    elif case_id in {"API-120", "API-121"}:
        await _memory_records(tenant_a_user, case_id == "API-120")
    elif case_id in {"API-122", "API-123"}:
        if case_id == "API-122":
            await _long_term_memory_isolated()
        else:
            await _long_term_memory(tenant_a_admin, tenant_a_user, False)
    elif case_id in {"AGT-049", "AGT-050"}:
        if case_id == "AGT-049":
            await _dreaming_isolated()
        else:
            await _dreaming(tenant_a_user, True)
    elif case_id in {"AGT-051", "AGT-052", "AGT-053"}:
        await _memory_agent_context(tenant_a_user, {"AGT-051": "core", "AGT-052": "boundary", "AGT-053": "dependency"}[case_id])
    elif case_id in {"AGT-054", "AGT-055", "AGT-056"}:
        await _automation(tenant_a_user, {"AGT-054": "core", "AGT-055": "boundary", "AGT-056": "dependency"}[case_id])
    else:
        raise AssertionError(f"unmapped D3 case {case_id}")
