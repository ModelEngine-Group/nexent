"""Prepare stable, non-secret D4 assets through current Nexent APIs.

This is an asset bootstrap, not a test executor.  It creates the external state
that fixed Playwright journeys need and writes only display names/version names
to a local shell environment file.  Product credentials remain in secrets.env.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from pathlib import Path
from uuid import uuid4

from d3.assets import configured_model, model_id, model_request
from shared.asset_registry import register_asset, resolve_asset, mark_asset_state
from shared.auth import sign_in
from shared.config import test_root
from shared.http import assert_status, client


def _data(response):
    body = response.json()
    return body.get("data") if isinstance(body, dict) else body


def _runtime_agent_name(display_name: str) -> str:
    return display_name.lower().replace(" ", "_")


async def _create_agent(
    identity,
    *,
    prefix: str,
    model_type: str,
    enabled_tool_ids: list[int] | None = None,
    related_agent_ids: list[int] | None = None,
    allow_chat_metadata: bool = False,
    duty_prompt: str | None = None,
    model_id_override: int | None = None,
) -> tuple[int, str, str]:
    token = uuid4().hex[:10]
    display_name = f"{prefix} {token}"
    variable_name = _runtime_agent_name(display_name)
    payload = {
        "name": variable_name,
        "display_name": display_name,
        "description": "Daily fixed Playwright shared asset",
        "author": "Nexent Test Suite",
        "business_description": "Prepared by the local D1-D5 asset bootstrap",
        "max_steps": 5,
        "provide_run_summary": False,
        "model_ids": [model_id_override or await model_id(model_type, identity)],
        "enabled_tool_ids": enabled_tool_ids or [],
        "enabled_skill_ids": [],
        "enabled": True,
        "version_no": 0,
        "allow_chat_metadata": allow_chat_metadata,
        "is_a2a": False,
        "related_agent_ids": related_agent_ids or [],
        "duty_prompt": duty_prompt or "Complete the assigned task accurately and preserve requested markers.",
    }
    # Current Nexent creates the draft through POST /agent/update when
    # agent_id is absent and returns the allocated ID in that response.
    # Register cleanup only after creation succeeds; the old GET-ID endpoint
    # no longer exists and cannot reserve an Agent for us.
    agent_id = None
    try:
        async with client("config", token=identity.access_token) as api:
            created = await api.post("/agent/update", json=payload)
            assert_status(created, 200)
            body = created.json()
            agent_id = int(body["agent_id"])
            register_asset('d4_owned_agents',str(agent_id),agent_id,owner_case_id='D4-PREP',cleanup={
                'service':'config','identity':identity.id,'method':'DELETE','path':'/agent',
                'json':{'agent_id':agent_id},'allowed_statuses':[200,404]})
            released = await api.put(f"/agent/clear_new/{agent_id}")
            assert_status(released, 200)
            published = await api.post(
                f"/agent/{agent_id}/publish",
                json={"version_name": "daily-baseline", "release_note": "D4 shared test asset"},
            )
            assert_status(published, 200)
            read_back = await api.post(
                "/agent/search_info", json={"agent_id": agent_id, "version_no": 0}
            )
            assert_status(read_back, 200)
            persisted = read_back.json().get("data") or read_back.json()
            if not str(persisted.get("author") or "").strip():
                raise AssertionError(
                    f"D4 shared Agent {agent_id} has no persisted author; Debug form validation would block"
                )
    except BaseException:
        if agent_id is not None:
            try:
                async with client("config", token=identity.access_token) as api:
                    removed=await api.request("DELETE", "/agent", json={"agent_id": agent_id})
                if removed.status_code in (200,404):
                    mark_asset_state('d4_owned_agents',str(agent_id),'DELETED')
            except Exception:
                # Preserve the original creation/publish failure. The
                # registered cleanup action remains available at case exit.
                pass
        raise
    return agent_id, display_name, "daily-baseline"


async def _ensure_controlled_mcp_service(identity) -> tuple[int, str]:
    """Create the batch-local MCP service when D4 runs without D2/D3.

    A complete Daily normally registers this service while exercising CTR-028.
    A D4-only run must not depend on a previous stage result, so the D4 asset
    bootstrap owns an equivalent run-scoped service and cleanup record.
    """
    existing_id = resolve_asset("mcp", "service_id", required=False)
    existing_name = resolve_asset("mcp", "service_name", required=False)
    if existing_id is not None and existing_name:
        return int(existing_id), str(existing_name)

    server_url = os.getenv("NEXENT_TEST_MCP_URL", "").strip()
    if not server_url:
        raise RuntimeError("NEXENT_TEST_MCP_URL is required for D4 controlled MCP preparation")
    service_name = f"d4-prep-mcp-{uuid4().hex[:10]}"
    async with client("config", token=identity.access_token) as api:
        created = await api.post("/mcp/add", json={
            "name": service_name,
            "server_url": server_url,
            "description": "D4 controlled MCP shared asset",
            "source": "local",
            "tags": ["automation", "d4"],
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
            (item for item in records
             if (item.get("remote_mcp_server_name") or item.get("name")) == service_name),
            None,
        )
        if not record:
            raise AssertionError(f"created D4 MCP service {service_name!r} was not returned by /mcp/list")
        service_id = int(record["mcp_id"])
        register_asset('mcp','service_id',service_id,owner_case_id='D4-PREP',cleanup={
            'service':'config','identity':identity.id,'method':'DELETE',
            'path':f'/mcp/{service_id}','allowed_statuses':[200,404]})
        register_asset('mcp','service_name',service_name,owner_case_id='D4-PREP')
        refreshed = await api.post("/mcp/refresh-tools", params={"mcp_id": service_id})
        assert_status(refreshed, 200)
        scanned = await api.get("/tool/scan_tool")
        assert_status(scanned, 200)

    return service_id, service_name


async def _controlled_tool_id(identity, origin_name: str) -> int:
    """Resolve one tool exposed by the batch-local controlled MCP service."""
    service_id, service_name = await _ensure_controlled_mcp_service(identity)
    async with client("config", token=identity.access_token) as api:
        response = await api.get("/tool/list")
    assert_status(response, 200)
    body = response.json()
    rows = body if isinstance(body, list) else body.get("data") or body.get("tools") or []
    matches = [
        row for row in rows
        if row.get("source") == "mcp"
        and row.get("origin_name") == origin_name
        and row.get("usage") == service_name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one controlled MCP tool {origin_name!r} "
            f"for service {service_name!r} (id={service_id}), found {len(matches)}"
        )
    return int(matches[0].get("tool_id") or matches[0]["id"])


def _register_agent(role: str, agent_id: int, display_name: str) -> None:
    owner = "D4-PREP"
    register_asset(
        "agents", f"{role}_id", agent_id, owner_case_id=owner,
    )
    register_asset("agents", f"{role}_display_name", display_name, owner_case_id=owner)


async def _resolve_multimodal_chat_model(identity) -> int:
    """Resolve the configured VLM name to the real chat-model record.

    Nexent Agents execute chat models from the LLM registry.  Creating a
    second VLM-typed record with a prefixed display name makes the runtime try
    to load that prefix as a model identifier.  The configured model name must
    therefore remain exact (for example, qwen3.7-plus).
    """
    configured = configured_model("vlm")
    expected_name = str(
        configured.get("preferred_model")
        or configured.get("model")
        or configured.get("model_name")
        or ""
    ).split(",")[0].strip()
    async with client("config", token=identity.access_token) as api:
        listed = await api.get("/model/list")
        assert_status(listed, 200)
        rows = listed.json().get("data") or []
        # Remove only the exact legacy record created by the old D4 bootstrap.
        legacy_display = f"d4-vlm-{expected_name}"
        legacy = [
            row for row in rows
            if str(row.get("model_type") or "").lower() == "vlm"
            and str(row.get("model_name") or row.get("name") or "") == expected_name
            and str(row.get("display_name") or "") == legacy_display
        ]
        for _ in legacy:
            deleted = await api.post(f"/model/delete?display_name={legacy_display}")
            assert_status(deleted, 200)
        if legacy:
            listed = await api.get("/model/list")
            assert_status(listed, 200)
            rows = listed.json().get("data") or []
        matches = [
            row for row in rows
            if str(row.get("model_type") or "").lower() == "llm"
            and str(row.get("model_name") or row.get("name") or "") == expected_name
            and str(row.get("display_name") or "") == expected_name
        ]
        if not matches:
            # The configured VLM is consumed by Agent chat as an LLM record.
            # Bootstrap it through the public API instead of treating an empty
            # database lookup as a dependency failure.
            payload = model_request("vlm", display_name=expected_name)
            payload["model_name"] = expected_name
            payload["model_type"] = "llm"
            created = await api.post("/model/create", json=payload)
            assert_status(created, 200)
            listed = await api.get("/model/list")
            assert_status(listed, 200)
            rows = listed.json().get("data") or []
            matches = [
                row for row in rows
                if str(row.get("model_type") or "").lower() == "llm"
                and str(row.get("model_name") or row.get("name") or "") == expected_name
                and str(row.get("display_name") or "") == expected_name
            ]
        if len(matches) != 1:
            raise AssertionError(f"expected one exact API-managed chat model {expected_name!r}, found {len(matches)}")
        from shared.model_health import ensure_model_health
        await ensure_model_health(identity, configured, matches[0])
        return int(matches[0].get("model_id") or matches[0]["id"])


async def _ensure_voice_config(identity, model_type: str) -> None:
    """Create and select the exact voice model declared in models.yaml."""
    configured = configured_model(model_type)
    expected_name = str(configured.get("model") or configured.get("model_name") or "").split(",")[0].strip()
    display_name = expected_name if model_type == "stt" else str(configured.get("id") or "daily-tts")
    payload = model_request(model_type, display_name=display_name)
    async with client("config", token=identity.access_token) as api:
        listed = await api.get("/model/list")
        assert_status(listed, 200)
        rows = listed.json().get("data") or []
        matches = [
            row for row in rows
            if str(row.get("model_type") or "").lower() == model_type
            and str(row.get("model_name") or row.get("name") or "") == expected_name
            and str(row.get("display_name") or "") == display_name
        ]
        if not matches:
            health = await api.post("/model/temporary_healthcheck", json=payload)
            assert_status(health, 200)
            health_data = health.json().get("data") or {}
            if not health_data.get("connectivity"):
                raise AssertionError(f"configured {model_type} model {expected_name!r} failed connectivity")
            created = await api.post("/model/create", json=payload)
            assert_status(created, 200)
            listed = await api.get("/model/list")
            assert_status(listed, 200)
            rows = listed.json().get("data") or []
            matches = [
                row for row in rows
                if str(row.get("model_type") or "").lower() == model_type
                and str(row.get("model_name") or row.get("name") or "") == expected_name
                and str(row.get("display_name") or "") == display_name
            ]
        if len(matches) != 1:
            raise AssertionError(f"expected one exact {model_type} model {expected_name!r}, found {len(matches)}")
        model_row = matches[0]
        health = await api.post(
            f"/model/healthcheck?display_name={display_name}&model_type={model_type}"
        )
        assert_status(health, 200)
        if not (health.json().get("data") or {}).get("connectivity"):
            raise AssertionError(f"configured {model_type} model {expected_name!r} failed saved-model healthcheck")
        loaded = await api.get("/config/load_config")
        assert_status(loaded, 200)
        backend_config = loaded.json().get("config") or {}
        raw_app = backend_config.get("app") or {}
        raw_icon = raw_app.get("icon") or {}
        product_config = {
            "app": {
                "appName": raw_app.get("name") or "",
                "appDescription": raw_app.get("description") or "",
                "iconType": raw_icon.get("type") or "preset",
                "iconKey": raw_icon.get("iconKey") or "search",
                "customIconUrl": raw_icon.get("customUrl"),
                "avatarUri": raw_icon.get("avatarUri"),
                "modelEngineEnabled": raw_app.get("modelEngineEnabled", False),
                "datamateUrl": raw_app.get("datamateUrl"),
            },
            "models": {},
        }
        raw_models = backend_config.get("models") or {}
        for key in ("llm", "embedding", "multiEmbedding", "rerank", "vlm", "vlm2", "vlm3", "vlm4", "stt", "tts"):
            raw = raw_models.get(key) or {}
            entry = {
                "id": raw.get("id") or 0,
                "modelName": raw.get("name") or "",
                "displayName": raw.get("displayName") or "",
                "apiConfig": raw.get("apiConfig") or {"apiKey": "", "modelUrl": ""},
            }
            if key in {"embedding", "multiEmbedding"}:
                entry["dimension"] = raw.get("dimension") or 0
            if key in {"stt", "tts"}:
                entry.update({
                    "modelFactory": raw.get("modelFactory") or "",
                    "modelAppid": raw.get("modelAppid") or "",
                    "accessToken": raw.get("accessToken") or "",
                })
            product_config["models"][key] = entry
        product_config["models"][model_type] = {
            "id": int(model_row.get("model_id") or model_row.get("id") or 0),
            "modelName": expected_name,
            "displayName": display_name,
            "apiConfig": {
                "apiKey": payload["api_key"],
                "modelUrl": payload["base_url"],
            },
            "modelFactory": payload["model_factory"],
            "modelAppid": payload.get("model_appid") or "",
            "accessToken": payload.get("access_token") or "",
        }
        saved = await api.post("/config/save_config", json=product_config)
        assert_status(saved, 200)


async def _ensure_stt_config(identity) -> None:
    await _ensure_voice_config(identity, "stt")


async def _ensure_tts_config(identity) -> None:
    await _ensure_voice_config(identity, "tts")



async def prepare_vlm(identity) -> dict:
    multimodal_model_id = await _resolve_multimodal_chat_model(identity)
    multimodal_config = configured_model("vlm")
    multimodal_model_name = str(
        multimodal_config.get("model") or multimodal_config.get("model_name") or ""
    ).split(",")[0].strip()
    vlm_agent_id, vlm_agent, _ = await _create_agent(
        identity, prefix="D4 VLM Agent", model_type="llm",
        model_id_override=multimodal_model_id,
    )
    _register_agent("d4_vlm", vlm_agent_id, vlm_agent)
    return {"NEXENT_TEST_VLM_AGENT": vlm_agent, "NEXENT_TEST_VLM_MODEL": multimodal_model_name}


async def prepare_stt(identity) -> dict:
    stt_ready = True
    stt_failure = ""
    try:
        await _ensure_stt_config(identity)
    except Exception as exc:
        stt_ready = False
        stt_failure = f"{type(exc).__name__}: {exc}"
    return {"NEXENT_TEST_STT_READY": "1" if stt_ready else "0", "NEXENT_TEST_STT_FAILURE": stt_failure}


async def prepare_chat(identity) -> dict:
    chat_agent_id, chat_agent, _ = await _create_agent(
        identity, prefix="D4 Chat Agent", model_type="llm"
    )
    _register_agent("d4_chat", chat_agent_id, chat_agent)

    return {"NEXENT_TEST_CHAT_AGENT": chat_agent}


async def prepare_tool_chat(identity) -> dict:
    get_test_code_id = await _controlled_tool_id(identity, "get_test_code")
    tool_chat_id, tool_chat_name, _ = await _create_agent(
        identity, prefix="D4 Tool Chat Agent", model_type="llm",
        enabled_tool_ids=[get_test_code_id],
        duty_prompt=(
            "When the user explicitly requests get_test_code, call that exact tool and "
            "return its result verbatim. Do not substitute another tool."
        ),
    )
    _register_agent("d4_tool_chat", tool_chat_id, tool_chat_name)
    return {"NEXENT_TEST_TOOL_CHAT_AGENT": tool_chat_name}


async def prepare_file_chat(identity) -> dict:
    """Own an attachment-capable Agent without changing the plain chat anchor."""
    async with client('config', token=identity.access_token) as api:
        response = await api.get('/tool/list')
    assert_status(response, 200)
    body = response.json()
    rows = body if isinstance(body, list) else body.get('data') or body.get('tools') or []
    matches = [row for row in rows if row.get('source') == 'local'
               and row.get('origin_name') == 'analyze_text_file']
    if len(matches) != 1:
        raise AssertionError('attachment test requires exactly one local analyze_text_file tool')
    tool_id = int(matches[0].get('tool_id') or matches[0]['id'])
    agent_id, name, _ = await _create_agent(
        identity, prefix='D4 File Agent', model_type='llm', enabled_tool_ids=[tool_id],
        duty_prompt='Use analyze_text_file to read attached documents before answering. Preserve requested markers.',
    )
    _register_agent('d4_file', agent_id, name)
    return {'NEXENT_TEST_FILE_AGENT': name}


async def prepare_multi(identity) -> dict:
    always_fail_id = await _controlled_tool_id(identity, "always_fail")
    child_a_id, child_a_name, _ = await _create_agent(
        identity, prefix="D4 Multi Child A", model_type="llm",
        duty_prompt="Complete every delegated task and include CHILD_A_OK in the result.",
    )
    _register_agent("d4_multi_child_a", child_a_id, child_a_name)
    register_asset("agents", "d4_multi_child_a_runtime_name", _runtime_agent_name(child_a_name), owner_case_id="D4-PREP")
    child_b_id, child_b_name, _ = await _create_agent(
        identity, prefix="D4 Multi Child B", model_type="llm",
        enabled_tool_ids=[always_fail_id],
        duty_prompt=(
            "Complete delegated tasks and include CHILD_B_OK. When the task explicitly "
            "requests a controlled failure, call always_fail and report its error verbatim."
        ),
    )
    _register_agent("d4_multi_child_b", child_b_id, child_b_name)
    register_asset("agents", "d4_multi_child_b_runtime_name", _runtime_agent_name(child_b_name), owner_case_id="D4-PREP")
    multi_id, multi_name, _ = await _create_agent(
        identity, prefix="D4 Multi Parent", model_type="llm",
        related_agent_ids=[child_a_id, child_b_id],
        duty_prompt=(
            "For every request, delegate one concrete subtask to each of the two configured "
            "related agents, wait for both, then summarize both results and preserve the "
            "exact marker requested by the user."
        ),
    )
    _register_agent("d4_multi", multi_id, multi_name)
    return {"NEXENT_TEST_MULTI_AGENT": multi_name, "NEXENT_TEST_MULTI_CHILD_A": child_a_name, "NEXENT_TEST_MULTI_CHILD_B": child_b_name}


async def prepare_scope(identity) -> dict:
    require_metadata_id = await _controlled_tool_id(identity, "require_metadata")
    scope_id, scope_name, _ = await _create_agent(
        identity, prefix="D4 Scope Agent", model_type="llm",
        enabled_tool_ids=[require_metadata_id], allow_chat_metadata=True,
    )
    _register_agent("d4_scope", scope_id, scope_name)

    return {"NEXENT_TEST_SCOPE_AGENT": scope_name}


async def prepare_evaluation(identity) -> dict:
    eval_agent_id, eval_agent, eval_version = await _create_agent(
        identity, prefix="D4 Eval Agent", model_type="llm"
    )
    _register_agent("d4_eval", eval_agent_id, eval_agent)
    set_name = f"D4 Eval Set {uuid4().hex[:10]}"
    evaluator_name = f"D4 Deterministic Evaluator {uuid4().hex[:10]}"
    async with client("config", token=identity.access_token) as api:
        created_set = await api.post(
            "/evaluation-sets", json={"name": set_name, "description": "D4 shared one-case set"}
        )
        assert_status(created_set, 200)
        set_body = _data(created_set) or {}
        set_id = int(set_body.get("evaluation_set_id") or set_body.get("id"))
        register_asset(
            "evaluation", "d4_set_id", set_id, owner_case_id="D4-PREP",
            cleanup={
                "service": "config", "identity": "tenant_a_admin", "method": "DELETE",
                "path": f"/evaluation-sets/{set_id}", "allowed_statuses": [200, 404],
            },
        )
        seeded = await api.post(
            f"/evaluation-sets/{set_id}/cases",
            json={
                "inputs": {"query": "Only reply NX-EVAL-92831"},
                "label": {"answer": "NX-EVAL-92831"},
                "session_id": "d4-shared",
                "turn_order": 1,
            },
        )
        assert_status(seeded, 200)
        evaluator = await api.post(
            "/evaluators",
            json={
                "name": evaluator_name,
                "description": "Deterministic D4 shared evaluator",
                "evaluator_type": "code",
                "code": "def evaluate(query, expected, actual, runtime_events, **kwargs):\n    return {'score': 1.0 if expected in actual else 0.0, 'reason': 'marker comparison'}",
                "score_range_min": 0,
                "score_range_max": 1,
                "pass_threshold": 0.8,
                "input_fields": [{"name": "output", "required": True}],
            },
        )
        assert_status(evaluator, 200)
        evaluator_body = _data(evaluator) or {}
        evaluator_id = int(evaluator_body.get("evaluator_id") or evaluator_body.get("id"))
        register_asset(
            "evaluation", "d4_evaluator_id", evaluator_id, owner_case_id="D4-PREP",
            cleanup={
                "service": "config", "identity": "tenant_a_admin", "method": "DELETE",
                "path": f"/evaluators/{evaluator_id}", "allowed_statuses": [200, 404],
            },
        )

    judge = configured_model("llm")
    judge_name = str(judge.get("preferred_model") or judge.get("display_name") or judge.get("model")).split(",")[0]
    return {"NEXENT_TEST_EVAL_AGENT": eval_agent, "NEXENT_TEST_EVAL_AGENT_VERSION": eval_version, "NEXENT_TEST_EVAL_JUDGE_MODEL": judge_name, "NEXENT_TEST_EVALUATOR": evaluator_name, "NEXENT_TEST_EVAL_SET": set_name}


async def prepare_basic_agent(identity) -> dict:
    agent,name,_=await _create_agent(identity,prefix='D4 Basic Prerequisite',model_type='llm')
    _register_agent('d4_basic',agent,name)
    return {'NEXENT_TEST_BASIC_AGENT':name}


async def prepare_llm_agent(identity) -> dict:
    agent,name,_=await _create_agent(identity,prefix='D4 LLM Prerequisite',model_type='llm')
    _register_agent('d4_llm_agent',agent,name)
    return {'NEXENT_TEST_LLM_AGENT':name}


async def _prepare_model_anchor(identity,kind,keys) -> dict:
    # Models are shared configured anchors, not disposable test resources.
    # Resolve real records; never invent a display name or copy credentials.
    async with client('config',token=identity.access_token) as api:
        response=await api.get('/model/list')
    assert_status(response,200)
    body=response.json()
    rows=body if isinstance(body,list) else body.get('data') or body.get('models') or []
    for kind,keys in [(kind,keys)]:
        numeric=await model_id(kind,identity)
        matches=[row for row in rows if str(row.get('model_id') or row.get('id'))==str(numeric)]
        if len(matches)!=1: raise AssertionError(f'configured {kind} model is not uniquely readable')
        name=matches[0].get('display_name') or matches[0].get('model_name')
        if not name: raise AssertionError('configured model has no display name')
        for key in keys:
            register_asset('models',key,name,owner_case_id='LOCAL-D4-ANCHOR',source='anchor')
    return {f'NEXENT_TEST_{kind.upper()}_MODEL':name}


async def prepare_llm_model(identity):
    return await _prepare_model_anchor(identity,'llm',['d4_llm_display_name','d4_basic_model_display_name'])


async def prepare_embedding_model(identity):
    return await _prepare_model_anchor(identity,'embedding',['d4_embedding_display_name'])


async def prepare_mcp(identity) -> dict:
    service,name=await _ensure_controlled_mcp_service(identity)
    return {'NEXENT_TEST_MCP_SERVICE_NAME':name}


async def prepare_knowledge(identity) -> dict:
    from d3.assets import create_registered_knowledge_base
    from shared.factories.files import _upload_kb_file
    from shared.factories.readiness import wait_ready
    path=test_root()/'assets/knowledge/alpha-nx-92831.txt'
    content=path.read_text(encoding='utf-8-sig')
    if 'NX-92831' not in content: raise AssertionError('canonical alpha asset has no expected marker')
    kb=await create_registered_knowledge_base(identity,owner_case_id='LOCAL-D4-KB',role='d4_local',prefix='d4-local-prerequisite')
    index=kb['index_name']
    register_asset('files','d4_alpha_source',str(path),owner_case_id='LOCAL-D4-KB',source='static')
    uploaded=await _upload_kb_file(identity,index,'d4_alpha_source')
    from shared.factories.knowledge import create_kb_chunk
    await create_kb_chunk(identity,index,content,title='alpha knowledge fixture',filename=path.name,
                          path_or_url=uploaded['object_name'])
    async def read():
        async with client('config',token=identity.access_token) as api:
            response=await api.post(f'/indices/{index}/chunks')
        assert_status(response,200)
        return ('READY' if 'NX-92831' in response.text else 'PENDING'),response
    await wait_ready(read,ready={'READY'},failed={'FAILED'},timeout=30,interval=1,section='knowledge',key='d4_local_name')
    register_asset('knowledge','d4_local_name',kb['display_name'],owner_case_id='LOCAL-D4-KB')
    return {'NEXENT_TEST_LOCAL_KB':kb['display_name']}


DEFAULT_GROUP_NAMES = ("vlm", "stt", "chat", "tool_chat", "multi", "scope", "evaluation")
GROUP_NAMES = DEFAULT_GROUP_NAMES + ('basic_agent','llm_agent','llm_model','embedding_model','knowledge','mcp','file_chat')


def full_suite_groups() -> list[str]:
    """Require reviewed groups instead of reading the retired central manifest."""
    raise RuntimeError("Pass explicit --group values from the case prerequisite review")


async def prepare_selected(identity, groups):
    # Validate the entire selection before any side effect.
    unknown = set(groups) - set(GROUP_NAMES)
    if unknown:
        raise ValueError(f"unknown D4 asset groups: {sorted(unknown)}")
    values, errors = {}, {}
    for name in dict.fromkeys(groups):
        try:
            values.update(await globals()[f"prepare_{name}"](identity))
        except Exception as exc:
            # No raw HTTP payloads/credentials in summary files.
            errors[name] = type(exc).__name__
    return values, errors


async def main() -> None:
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", action="append", choices=GROUP_NAMES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        parser.error("--output must be a case-local runtime file")
    target = args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    identity = await sign_in("tenant_a_admin")
    groups = args.group if args.group is not None else full_suite_groups()
    values, errors = await prepare_selected(identity, groups)
    target.write_text("".join(f"export {key}={shlex.quote(str(value))}\n" for key, value in values.items()), encoding="utf-8")
    target.chmod(0o600)
    target.with_suffix(".status.json").write_text(json.dumps({"groups": groups, "errors": errors}, indent=2), encoding="utf-8")
    if errors:
        raise RuntimeError(f"D4 asset groups failed: {errors}; successful group assets remain registered")
    print(f"environment={target}")


if __name__ == "__main__":
    asyncio.run(main())
