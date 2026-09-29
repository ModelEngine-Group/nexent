"""D3 Agent configuration, NL2Agent, prompt, tool, skill and import scenarios."""

from __future__ import annotations
from shared.factories.agent import _llm_id, _draft_agent
from shared.resource_ids import absent_numeric_id

import json
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from d3.assets import model_id as configured_model_id, model_request
from shared.cases import case_params
from shared.asset_registry import register_asset, register_asset_failure, resolve_asset, mark_asset_state
from shared.factories.ownership import register_owned_http
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.http import config_save_payload
from shared.factories.tenant import isolated_accounts
from shared.sse import assert_terminal_event, read_sse


AGENT_CONFIG_CASES = [
    "API-055", "API-056", "API-057", "API-058",
    "AGT-001", "AGT-002", "AGT-003", "AGT-004", "AGT-005",
    "AGT-006", "AGT-007", "AGT-008", "AGT-009", "AGT-010", "AGT-011", "AGT-012",
    "API-059", "API-060", "API-061", "API-062", "API-063", "API-064", "API-065", "API-066",
]




def _find_nested_int(data, keys: set[str]) -> int | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
            found = _find_nested_int(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_nested_int(value, keys)
            if found is not None:
                return found
    return None


@asynccontextmanager
async def _controlled_regeneration_model(identity, *, force_failure: bool):
    """Install a batch-scoped LLM whose responses are served by test-assets."""
    controlled_url = (
        os.getenv("NEXENT_TEST_ASSETS_URL")
        or os.getenv("NEXENT_TEST_ASSETS_CONTAINER_URL")
    )
    if not controlled_url:
        pytest.skip("NEXENT_TEST_ASSETS_URL is required for regenerate_name fault injection")

    display_name = f"d3-regenerate-name-{uuid.uuid4().hex[:8]}"
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        config = await api.get("/config/load_config")
        assert_status(config, 200)

        payload = model_request("llm", display_name=display_name)
        payload.update({
            "model_name": "controlled-fault-model",
            "api_key": "controlled-test-key",
            "base_url": f"{controlled_url.rstrip('/')}/{'unavailable' if force_failure else 'fault'}/v1",
        })
        created = await api.post("/model/create", json=payload)
        assert_status(created, 200)
        listed = await api.get("/model/list")
        assert_status(listed, 200)
        rows = listed.json().get("data") or []
        model = next((row for row in rows if row.get("display_name") == display_name), None)
        assert model, f"controlled regeneration model {display_name} was not listed"
        model_id = int(model.get("model_id") or model["id"])

        selection = config_save_payload(config.json())
        selection["models"]["llm"].update({
            "modelName": payload["model_name"], "displayName": display_name,
            "apiConfig": {"apiKey": payload["api_key"], "modelUrl": payload["base_url"]},
        })
        selected = await api.post("/config/save_config", json=selection)
        assert_status(selected, 200)
        try:
            yield model_id
        finally:
            deleted = await api.post("/model/delete", params={"display_name": display_name})
            assert_status(deleted, (200, 404))


def _response_items(response, *keys: str) -> list:
    body = response.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in keys:
            value = body.get(key)
            if isinstance(value, list):
                return value
        data = body.get("data")
        if isinstance(data, list):
            return data
    return []




async def _agent_discovery(identity) -> None:
    try:
        async with _draft_agent(
            identity, retain_for_batch=True, owner_case_id="API-055", registry_role="basic",
        ) as (agent_id, payload):
            async with client("config", token=identity.access_token) as api:
                listed = await api.get("/agent/list")
                searched = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
                by_name = await api.get(f"/agent/by-name/{payload['name']}")
            for response in (listed, searched, by_name):
                assert_status(response, 200)
            assert any(int(item["agent_id"]) == agent_id for item in listed.json())
    except Exception as exc:
        # Do not overwrite a READY asset when creation succeeded but a later
        # discovery assertion exposed a product defect.
        from shared.asset_registry import resolve_asset
        if resolve_asset("agents", "basic_id", required=False) is None:
            register_asset_failure("agents", "basic_id", owner_case_id="API-055", reason=str(exc))
            register_asset_failure("agents", "basic_name", owner_case_id="API-055", reason=str(exc))
        raise


async def _agent_discovery_negative(identity, other) -> None:
    assert identity.tenant_id != other.tenant_id, "cross-tenant probe requires distinct tenants"
    async with _draft_agent(identity) as (agent_id, payload):
        async with client("config", token=other.access_token) as api:
            isolated = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
        async with client("config", token=identity.access_token) as api:
            missing = await api.get("/agent/by-name/not-present")
        assert isolated.status_code in {403, 404}
        assert_status(missing, 404)


async def _agent_crud(identity) -> None:
    async with _draft_agent(identity) as (agent_id, payload):
        renamed = f"renamed-{uuid.uuid4().hex[:8]}"
        async with client("config", token=identity.access_token) as api:
            checked = await api.post("/agent/check_name", json={"items": [{
                "name": renamed.replace("-", "_"), "display_name": renamed, "agent_id": agent_id,
            }]})
            assert_status(checked, 200)
            updated = await api.post("/agent/update", json={
                **payload, "name": renamed.replace("-", "_"), "display_name": renamed,
            })
            assert_status(updated, 200)
            fetched = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
        assert_status(fetched, 200)
        assert fetched.json()["display_name"] == renamed


async def _agent_crud_negative(identity) -> None:
    async with _draft_agent(identity) as (agent_id, payload):
        async with client("config", token=identity.access_token) as api:
            duplicate = await api.post("/agent/update", json={**payload, "agent_id": None})
            invalid = await api.post("/agent/update", json={"agent_id": agent_id, "max_steps": 0})
            missing = await api.request("DELETE", "/agent", json={"agent_id": absent_numeric_id(__name__)})
        assert duplicate.status_code in {400, 409}
        assert_status(invalid, 422)
        assert_status(missing, 404)


async def _regenerate_name(identity, model_admin, *, force_failure: bool) -> None:
    """Verify LLM naming and the suffix fallback against a real name conflict."""
    async with _controlled_regeneration_model(model_admin, force_failure=force_failure) as model_id:
        async with _draft_agent(identity, model_ids=[model_id]) as (_, payload):
            task_description = (
                "force-regenerate-name-failure"
                if force_failure
                else "Generate a unique concise financial-summary agent name"
            )
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                response = await api.post(
                    "/agent/regenerate_name",
                    json={"items": [{
                        "name": payload["name"],
                        "display_name": payload["display_name"],
                        "task_description": task_description,
                    }]},
                )
            assert_status(response, 200)
            items = _response_items(response, "items")
            assert len(items) == 1
            result = items[0]
            assert result["name"] and result["name"] != payload["name"]
            assert result["display_name"] and result["display_name"] != payload["display_name"]
            if force_failure:
                assert result["name"] == f'{payload["name"]}_1'
                assert result["display_name"] == f'{payload["display_name"]}_1'
            else:
                assert result["name"] == "CONTROLLED_PROVIDER_RECOVERED_AFTER_RATE_LIMIT"
                assert result["display_name"] == "CONTROLLED_PROVIDER_RECOVERED_AFTER_RATE_LIMIT"


async def _regenerate_name_isolated(*, force_failure: bool) -> None:
    async with isolated_accounts(["tenant_a_admin", "tenant_a_user"]) as accounts:
        await _regenerate_name(
            accounts["tenant_a_user"], accounts["tenant_a_admin"],
            force_failure=force_failure,
        )


async def _nl2agent(identity, mode: str) -> None:
    async with _draft_agent(identity, name_prefix="nl2agent") as (agent_id, _):
        query = {
            "core": "Create an assistant that summarizes a supplied paragraph and asks when text is missing.",
            "boundary": "",
            "failure": "Create an assistant using a nonexistent external capability named d3-missing-tool.",
        }[mode]
        payload = {"query": query, "agent_id": agent_id, "history": [], "complexity": "complicated"}
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/agent/nl2agent/run", json=payload) as response:
                if mode == "boundary":
                    assert_status(response, 422)
                    return
                assert_status(response, 200)
                events = await read_sse(response)
        # NL2Agent pauses at a structured clarification card; that protocol
        # turn ends at EOF without a final_answer (the user must answer first).
        if mode == "failure":
            cards = []
            for event in events:
                data = event.get("data")
                if isinstance(data, dict) and data.get("type") == "nl2a":
                    content = data.get("content")
                    card = json.loads(content) if isinstance(content, str) else content
                    if isinstance(card, dict) and card.get("subtype") == "requirement_clarification":
                        cards.append(card)
            if cards:
                assert all(card.get("questions") for card in cards)
                assert "d3-missing-tool" in json.dumps(cards, ensure_ascii=False)
                return
        assert_terminal_event(events)
        text = json.dumps(events, ensure_ascii=False)
        if mode == "core":
            assert "proposal" in text.lower() or "agent" in text.lower()
        else:
            assert "missing" in text.lower() or "error" in text.lower() or "clar" in text.lower()


async def _prompt_generate(identity, mode: str) -> None:
    model_id = await _llm_id(identity)
    async with _draft_agent(identity, name_prefix="prompt") as (agent_id, _):
        payload = {
            "task_description": "Answer questions using concise factual language",
            "agent_id": agent_id,
            "model_id": model_id if mode != "failure" else absent_numeric_id(__name__),
            "tool_ids": [], "sub_agent_ids": [], "knowledge_base_display_names": [],
            "has_selected_resources": False,
        }
        if mode == "boundary":
            payload["task_description"] = ""
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/prompt/generate", json=payload) as response:
                if mode == "boundary":
                    assert response.status_code in {400, 404, 422}
                    return
                assert_status(response, 200)
                events = await read_sse(response)
        if mode == "failure":
            payloads = [event.get("data") for event in events]
            assert payloads and all(isinstance(item, dict) for item in payloads)
            assert any(item.get("success") is False and
                       item.get("error", {}).get("code") and
                       item.get("error", {}).get("message") for item in payloads), "missing structured SSE model error"
            assert not any(item.get("success") is True for item in payloads), "failed model generated partial success"
            async with client("config", token=identity.access_token) as api:
                fetched = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
            assert_status(fetched, 200)
            saved = fetched.json().get("data") or fetched.json()
            assert not any(saved.get(field) for field in ("duty_prompt", "constraint_prompt", "few_shots_prompt")), "failed generation persisted prompt fields"
            return
        assert_terminal_event(events)
        assert any(str(item.get("data") or "").strip() for item in events)


async def _prompt_section(identity, valid: bool) -> None:
    model_id = await _llm_id(identity)
    async with _draft_agent(identity) as (agent_id, _):
        payload = {
            "task_description": "Answer safely", "agent_id": agent_id, "model_id": model_id,
            "section_type": "duty", "section_title": "Duty", "current_content": "Answer questions.",
            "feedback": "Make it concise.", "mode": "select" if valid else "insert",
            "start_pos": 0, "end_pos": 6 if valid else -1,
            "tool_ids": [], "sub_agent_ids": [], "knowledge_base_display_names": [],
        }
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post("/prompt/optimize", json=payload)
        assert_status(response, 200 if valid else (400, 422))
        if valid:
            assert response.json()["data"]["optimized_content"]


async def _prompt_badcase(identity, debug: bool, failure: bool) -> None:
    model_id = await _llm_id(identity)
    async with _draft_agent(identity) as (agent_id, _):
        if debug:
            path = "/prompt/optimize/from_debug"
            payload = {
                "agent_id": agent_id, "model_id": absent_numeric_id(__name__) if failure else model_id,
                "feedback": "Do not invent facts",
                "selected": {"user_question": "What is X?", "assistant_answer": "Unverified answer"},
                "history": [{"role": "user", "content": "What is X?"}],
            }
        else:
            path = "/prompt/optimize/badcase"
            payload = {
                "agent_id": agent_id, "model_id": absent_numeric_id(__name__) if failure else model_id,
                "current_content": "Always answer.",
                "bad_cases": [{"question": "Unknown?", "answer": "invented", "reason": "hallucination"}],
                "section_type": "constraint", "section_title": "Constraints",
                "tool_ids": [], "sub_agent_ids": [], "knowledge_base_display_names": [],
            }
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post(path, json=payload)
        assert_status(response, (400, 404) if failure else 200)


def _template_content() -> dict:
    return {
        "duty_system_prompt": "Generate duty", "constraint_system_prompt": "Generate constraints",
        "few_shots_system_prompt": "Generate examples", "agent_variable_name_system_prompt": "Generate name",
        "agent_display_name_system_prompt": "Generate display name",
        "agent_description_system_prompt": "Generate description", "user_prompt": "{task_description}",
        "agent_name_regenerate_system_prompt": "Regenerate name",
        "agent_name_regenerate_user_prompt": "{task_description}",
        "agent_display_name_regenerate_system_prompt": "Regenerate display",
        "agent_display_name_regenerate_user_prompt": "{task_description}",
    }


async def _template_crud(identity) -> None:
    name = f"d3-template-{uuid.uuid4().hex[:8]}"
    payload = {"template_name": name, "description": "D3", "template_content_zh": _template_content()}
    template_id = None
    async with client("config", token=identity.access_token) as api:
        created = await api.post("/prompt_templates", json=payload)
        assert_status(created, 200)
        template_id = int(created.json().get("template_id") or created.json()["id"])
        register_owned_http(identity, 'owned_prompt_templates', template_id, f'/prompt_templates/{template_id}')
        try:
            listed = await api.get("/prompt_templates")
            detail = await api.get(f"/prompt_templates/{template_id}")
            updated = await api.put(f"/prompt_templates/{template_id}", json={**payload, "description": "updated"})
            for response in (listed, detail, updated):
                assert_status(response, 200)
            duplicate = await api.post("/prompt_templates", json=payload)
            assert_status(duplicate, 400)
        finally:
            if template_id is not None:
                deleted = await api.delete(f"/prompt_templates/{template_id}")
                assert_status(deleted, 200)
                mark_asset_state('owned_prompt_templates', str(template_id), 'DELETED')


async def _tool_binding(identity, valid: bool) -> None:
    if valid:
        server_url = os.getenv("NEXENT_TEST_MCP_URL", "").strip()
        if not server_url:
            from shared.asset_registry import AssetDependencyError
            raise AssetDependencyError(
                "services", "controlled_mcp_url", "API-060", "D0-MCP",
                detail="NEXENT_TEST_MCP_URL is required for MCP deletion/unbind coverage",
            )
        service_name = f"d3-tool-unbind-{uuid.uuid4().hex[:8]}"
        service_id = 0
        try:
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                created = await api.post("/mcp/add", json={
                    "name": service_name,
                    "server_url": server_url,
                    "description": "D3 MCP deletion/unbind contract",
                    "source": "local",
                    "tags": ["automation", "d3", "unbind"],
                    "enabled": True,
                    "ingroup_permission": "PRIVATE",
                    "shared_fields": {"server_url": False, "authorization_token": False},
                    "skip_health_check": False,
                })
                assert_status(created, 200)
                listed = await api.get("/mcp/list")
                assert_status(listed, 200)
                records = listed.json().get("remote_mcp_server_list") or []
                record = next(
                    item for item in records
                    if (item.get("remote_mcp_server_name") or item.get("name")) == service_name
                )
                service_id = int(record["mcp_id"])
                register_asset('owned_mcp_services', str(service_id), service_id,
                               owner_case_id='API-060', cleanup={
                                   'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                   'path': f'/mcp/{service_id}', 'allowed_statuses': [200, 404],
                               })
                assert_status(await api.post("/mcp/refresh-tools", params={"mcp_id": service_id}), 200)
                assert_status(await api.get("/tool/scan_tool"), 200)
                tools = await api.get("/tool/list")
                assert_status(tools, 200)
                item = next(
                    row for row in _response_items(tools, "tools")
                    if row.get("source") == "mcp" and row.get("usage") == service_name
                )
                tool_id = int(item.get("tool_id") or item["id"])

            async with _draft_agent(identity) as (agent_id, payload):
                async with client("config", token=identity.access_token) as api:
                    bound = await api.post(
                        "/agent/update", json={**payload, "enabled_tool_ids": [tool_id]},
                    )
                    assert_status(bound, 200)
                    before = await api.post(
                        "/agent/search_info", json={"agent_id": agent_id, "version_no": 0},
                    )
                    assert_status(before, 200)
                    before_data = before.json().get("data") or before.json()
                    # The write payload uses enabled_tool_ids; Agent detail
                    # exposes the persisted enabled instances as tools.
                    assert isinstance(before_data.get("tools"), list)
                    assert tool_id in {int(tool["tool_id"]) for tool in before_data["tools"]}

                    deleted = await api.delete(f"/mcp/{service_id}")
                    assert_status(deleted, 200)
                    mark_asset_state('owned_mcp_services', str(service_id), 'DELETED')
                    service_id = 0

                    after = await api.post(
                        "/agent/search_info", json={"agent_id": agent_id, "version_no": 0},
                    )
                    assert_status(after, 200)
                    after_data = after.json().get("data") or after.json()
                    assert isinstance(after_data.get("tools"), list)
                    assert tool_id not in {int(tool["tool_id"]) for tool in after_data["tools"]}
            return
        finally:
            if service_id:
                async with client("config", token=identity.access_token) as api:
                    cleanup = await api.delete(f"/mcp/{service_id}")
                assert cleanup.status_code in {200, 404}
                mark_asset_state('owned_mcp_services', str(service_id), 'DELETED')

    async with _draft_agent(
        identity,
        retain_for_batch=False,
    ) as (agent_id, payload):
        async with client("config", token=identity.access_token) as api:
            # Invalid-ID coverage does not require borrowing any existing tool.
            selected = absent_numeric_id(__name__)
            before = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
            assert_status(before, 200)
            before_data = before.json().get("data") or before.json()
            assert isinstance(before_data.get("tools"), list), "Agent detail must expose tool bindings"
            for _ in range(2):
                updated = await api.post("/agent/update", json={**payload, "enabled_tool_ids": [selected]})
                assert_status(updated, 200)
                fetched = await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0})
                assert_status(fetched, 200)
                current = fetched.json().get("data") or fetched.json()
                assert current.get("tools") == before_data["tools"], "unknown tool mapping polluted the draft"
                for field in ("name", "display_name", "description", "max_steps"):
                    assert current.get(field) == before_data.get(field), f"unknown mapping changed {field}"


async def _skill_binding(identity, valid: bool) -> None:
    async with _draft_agent(
        identity,
        retain_for_batch=valid,
        owner_case_id="API-062" if valid else "",
        registry_role="skill" if valid else "",
    ) as (agent_id, payload):
        async with client("config", token=identity.access_token) as api:
            skills = await api.get("/skills")
            assert_status(skills, 200)
            items = skills.json()["skills"]
            if valid:
                registered = resolve_asset(
                    "skills", "configurable_id", required=False,
                    consumer_case_id="API-062", dependency_case_id="API-077",
                )
                if registered is None:
                    from shared.asset_registry import AssetDependencyError
                    raise AssetDependencyError(
                        "skills", "configurable_id", "API-062", "API-077",
                        detail="D2 did not create a reusable Skill",
                    )
                selected = int(registered)
                assert any(int(item.get("skill_id") or item.get("id")) == selected for item in items), (
                    "the Skill created by API-077 is not visible to the owning test user"
                )
            else:
                selected = absent_numeric_id(__name__)
            updated = await api.post("/agent/update", json={
                **payload, "enabled_skill_ids": [selected],
                "skill_instances": [{"skill_id": selected, "enabled": True, "config_values": {}}],
            })
            assert_status(updated, 200 if valid else (400, 404))
            if valid:
                listed = await api.get("/skills/instance/list", params={"agent_id": agent_id, "version_no": 0})
                assert_status(listed, 200)


async def _relationship(identity, valid: bool) -> None:
    if not valid:
        async with _draft_agent(identity, name_prefix="parent") as (parent_id, parent):
            related = [parent_id, absent_numeric_id(__name__)]
            async with client("config", token=identity.access_token) as api:
                updated = await api.post("/agent/update", json={**parent, "related_agent_ids": related})
            assert updated.status_code in {400, 404, 409}
        return

    async with _draft_agent(
        identity, name_prefix="parent", retain_for_batch=True,
        owner_case_id="API-064", registry_role="nested_pending",
    ) as (parent_id, parent):
        async with _draft_agent(
            identity, name_prefix="child-a", retain_for_batch=True,
            owner_case_id="API-064", registry_role="nested_child_a",
        ) as (child_a_id, _):
            async with _draft_agent(
                identity, name_prefix="child-b", retain_for_batch=True,
                owner_case_id="API-064", registry_role="nested_child_b",
            ) as (child_b_id, _):
                async with client("config", token=identity.access_token) as api:
                    updated = await api.post(
                        "/agent/update", json={**parent, "related_agent_ids": [child_a_id, child_b_id]},
                    )
                    assert_status(updated, 200)
                    tree = await api.get(f"/agent/call_relationship/{parent_id}")
                assert_status(tree, 200)
                assert str(child_a_id) in tree.text and str(child_b_id) in tree.text
                register_asset("agents", "nested_id", parent_id, owner_case_id="API-064")
                register_asset("agents", "parallel_id", parent_id, owner_case_id="API-064")


async def _export_import(identity) -> None:
    async with _draft_agent(identity, name_prefix="export") as (agent_id, _):
        async with client("config", token=identity.access_token) as api:
            exported = await api.post("/agent/export", json={"agent_id": agent_id})
            assert_status(exported, 200)
            assert exported.headers["content-type"].startswith(("application/json", "application/zip"))
            if exported.headers["content-type"].startswith("application/json"):
                data = exported.json().get("data") or exported.json()
                imported = await api.post("/agent/import", json={"agent_info": data, "force_import": True})
                assert_status(imported, 200)
                imported_id = imported.json().get("agent_id")
                if imported_id:
                    register_asset('owned_agents', str(imported_id), int(imported_id),
                        owner_case_id='IMPORT-FACTORY', cleanup={
                            'service':'config', 'identity':identity.id, 'method':'DELETE',
                            'path':'/agent', 'json':{'agent_id':int(imported_id)}, 'allowed_statuses':[200,404]})
                    removed = await api.request("DELETE", "/agent", json={"agent_id": imported_id})
                    assert_status(removed, (200,404))
                    mark_asset_state('owned_agents', str(imported_id), 'DELETED')
            invalid = await api.post("/agent/import", json={"agent_info": {"agent_id": -1}})
            assert invalid.status_code in {400, 409, 422}


@pytest.mark.asyncio
async def execute_agent_configuration_scenario(case: dict, tenant_a_admin, tenant_a_user, tenant_b_user) -> None:
    case_id = case["id"]
    handlers = {
        "API-055": lambda: _agent_discovery(tenant_a_user),
        "API-056": lambda: _agent_discovery_negative(tenant_a_user, tenant_b_user),
        "API-057": lambda: _agent_crud(tenant_a_user),
        "API-058": lambda: _agent_crud_negative(tenant_a_user),
        "AGT-001": lambda: _regenerate_name_isolated(force_failure=False),
        "AGT-002": lambda: _regenerate_name_isolated(force_failure=True),
        "AGT-003": lambda: _nl2agent(tenant_a_user, "core"),
        "AGT-004": lambda: _nl2agent(tenant_a_user, "boundary"),
        "AGT-005": lambda: _nl2agent(tenant_a_user, "failure"),
        "AGT-006": lambda: _prompt_generate(tenant_a_user, "core"),
        "AGT-007": lambda: _prompt_generate(tenant_a_user, "boundary"),
        "AGT-008": lambda: _prompt_generate(tenant_a_user, "failure"),
        "AGT-009": lambda: _prompt_section(tenant_a_user, True),
        "AGT-010": lambda: _prompt_section(tenant_a_user, False),
        "AGT-011": lambda: _prompt_badcase(tenant_a_user, False, False),
        "AGT-012": lambda: _prompt_badcase(tenant_a_user, True, True),
        "API-059": lambda: _template_crud(tenant_a_user),
        "API-060": lambda: _tool_binding(tenant_a_user, True),
        "API-061": lambda: _tool_binding(tenant_a_user, False),
        "API-062": lambda: _skill_binding(tenant_a_user, True),
        "API-063": lambda: _skill_binding(tenant_a_user, False),
        "API-064": lambda: _relationship(tenant_a_user, True),
        "API-065": lambda: _relationship(tenant_a_user, False),
        "API-066": lambda: _export_import(tenant_a_user),
    }
    await handlers[case_id]()
