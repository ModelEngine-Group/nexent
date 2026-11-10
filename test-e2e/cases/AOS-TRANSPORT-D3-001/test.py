# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise real AgentOS HTTP boundaries with a recording execution adapter."""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from contracts.agentos import (
    AgentOperation, AgentResume, AgentRunReference, AgentRunningState, AgentStop, BackgroundAgentResult, BackgroundRun, CompatibilityOperation, CompatibilityRun,
    EvaluationAgentResult, EvaluationAgentRun, PreparedAgentRun, PreparedEvaluationRun,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from gateway.downstream.middleware import GatewayIdentityMiddleware
from gateway.security.context import trusted_identity
from infrastructure import agentos_identity
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.clients.agentos import AgentOSClient
from runtime.agentos.compatibility import create_background_router, create_compatibility_router
from runtime.agentos import prepared_evaluation
from runtime.agentos.evaluation import create_evaluation_router
from runtime.agentos.middleware import AgentOSMiddleware

_EVENTS = b"id: 1\ndata: first\n\nid: 2\ndata: done\n\n"


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not worker.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("AgentOS verification server did not start")
                time.sleep(0.02)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive(), "AgentOS verification leaked a server"


@pytest.mark.stage("D3")
@pytest.mark.case_id("AOS-TRANSPORT-D3-001")
@pytest.mark.asyncio
async def test_signed_agentos_transport(monkeypatch, tmp_path):
    key = "synthetic-agentos-transport-fixture-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    principal = ServicePrincipal("user-a", "tenant-a")
    calls = []

    async def run(payload, actor):
        async def events():
            assert trusted_identity("internal") == {
                "user_id": actor.user_id, "tenant_id": actor.tenant_id, "kind": "internal",
            }
            yield _EVENTS

        calls.append(("run", payload, actor))
        return StreamingResponse(events(), media_type="text/event-stream")

    async def stop(conversation_id, actor):
        calls.append(("stop", conversation_id, actor))
        return {"message": "stopped"}

    case_events = [{"type": "thought", "content": "step"}, {"type": "final_answer", "content": "answer"}]

    async def evaluate(payload, actor):
        calls.append(("evaluate", payload.conversation_id, actor))
        return EvaluationAgentResult(answer="answer", events=case_events)

    started = threading.Event()
    canceled = threading.Event()

    async def background(payload, actor):
        calls.append(("background", payload["conversation_id"], actor))
        if payload["conversation_id"] == 43:
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                canceled.set()
        return BackgroundAgentResult(conversation_id=42, assistant_message_id=17, chunks=3)

    async def inspect(conversation_id, actor):
        calls.append(("inspect", conversation_id, actor))
        return AgentRunningState(running=True)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_compatibility_router(run, stop))
    runtime.include_router(create_evaluation_router())
    runtime.include_router(create_background_router(background, inspect))

    with monkeypatch.context() as evaluation_stub, serve(runtime) as runtime_url:
        evaluation_stub.setattr(prepared_evaluation, "execute_prepared_evaluation", evaluate)

        def client_factory(**kwargs):
            return httpx.AsyncClient(trust_env=False, **kwargs)

        agentos = AgentOSClient(runtime_url, client_factory)
        management = FastAPI()

        @management.post("/run")
        async def management_run():
            return await agentos.run({"conversation_id": 42}, principal.user_id, principal.tenant_id)

        @management.post("/stop")
        async def management_stop():
            return await agentos.stop(42, principal.user_id, principal.tenant_id)

        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            with serve(management) as management_url:
                response = await client.post(f"{management_url}/run")
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.content == _EVENTS
                response = await client.post(f"{management_url}/stop")
                assert response.status_code == 200
                assert response.json() == {"message": "stopped"}

            run_url = f"{runtime_url}/api{CompatibilityOperation.RUN.value}"
            stop_url = f"{runtime_url}/api{CompatibilityOperation.STOP.value}"
            body = CompatibilityRun(request={"conversation_id": 42}).model_dump_json().encode()
            token = sign_call(CompatibilityOperation.RUN, body, principal)
            with monkeypatch.context() as expired_time:
                expired_time.setattr(agentos_identity, "time", SimpleNamespace(time=lambda: time.time() - 120))
                expired = sign_call(CompatibilityOperation.RUN, body, principal)

            for url, payload, credential, status in (
                (run_url, body, None, 401),
                (run_url, body.replace(b"42", b"43"), token, 401),
                (stop_url, body, token, 401),
                (run_url, body, expired, 401),
                (run_url.replace("/v1/", "/v2/"), body, token, 404),
            ):
                headers = {"Authorization": f"Bearer {credential}"} if credential else {}
                result = await client.post(url, content=payload, headers=headers)
                assert result.status_code == status
                assert "conversation_id" not in result.text

            case = PreparedEvaluationRun.model_validate({
                "mode": "nexent",
                "resource": {
                    "agent_id": 7, "version_no": 3, "name": "agent",
                    "description": "agent", "prompt_templates": {},
                },
                "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
                "input": {"query": "question"},
                "conversation_id": -12,
            })
            result = await agentos.run_prepared_evaluation(case, principal.user_id, principal.tenant_id)
            assert result.answer == "answer"
            assert result.events == case_events
            invalid = json.dumps(case.model_dump() | {"conversation_id": 42}).encode()
            signed = sign_call(AgentOperation.EVALUATION_CASE, invalid, principal)
            response = await client.post(
                f"{runtime_url}/api{AgentOperation.EVALUATION_CASE.value}",
                content=invalid,
                headers={"Authorization": f"Bearer {signed}"},
            )
            assert response.status_code == 422

            retired = CompatibilityOperation.EVALUATION_CASE
            old_case = EvaluationAgentRun(agent_id=7, version_no=3, query="question", conversation_id=-12)
            old_body = old_case.model_dump_json().encode()
            invalid_old_body = json.dumps(old_case.model_dump() | {"conversation_id": 42}).encode()
            retired_url = f"{runtime_url}/api{retired.value}"
            for content, credential, status, code in (
                (old_body, None, 401, "AGENTOS_UNAUTHORIZED"),
                (invalid_old_body, sign_call(retired, invalid_old_body, principal), 422, "AGENTOS_INVALID_REQUEST"),
                (old_body, sign_call(retired, old_body, principal), 410, "AGENTOS_EVALUATION_PREPARED_REQUIRED"),
            ):
                headers = {"Authorization": f"Bearer {credential}"} if credential else {}
                response = await client.post(retired_url, content=content, headers=headers)
                assert response.status_code == status
                assert response.json() == {"code": code}

            background_result = await agentos.run_background({"conversation_id": 42}, principal.user_id, principal.tenant_id)
            assert background_result.model_dump() == {"conversation_id": 42, "assistant_message_id": 17, "chunks": 3}
            state = await agentos.inspect(42, principal.user_id, principal.tenant_id)
            assert state.running is True
            pending = asyncio.create_task(agentos.run_background(
                {"conversation_id": 43}, principal.user_id, principal.tenant_id,
            ))
            try:
                assert await asyncio.to_thread(started.wait, 5)
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            assert await asyncio.to_thread(canceled.wait, 5)

    assert calls == [
        ("run", {"conversation_id": 42}, principal),
        ("stop", 42, principal),
        ("evaluate", -12, principal),
        ("background", 42, principal),
        ("inspect", 42, principal),
        ("background", 43, principal),
    ]
    await _assert_prepared_evaluation_over_signed_http(monkeypatch, tmp_path)
    with monkeypatch.context() as tool_patches:
        await _assert_stored_local_tool_over_signed_http(tool_patches, tmp_path)
    with monkeypatch.context() as aidp_patches:
        await _assert_shared_aidp_over_signed_http(aidp_patches, tmp_path)
    await _assert_resume_over_signed_http(monkeypatch)
    await _assert_run_lifecycle_over_signed_http(monkeypatch)
    with monkeypatch.context() as submission_patches:
        await _assert_public_conversation_over_signed_http(submission_patches)
    with monkeypatch.context() as lifecycle_patches:
        await _assert_public_stop_and_background(lifecycle_patches)
    await _assert_runtime_legacy_ingress_and_lifecycle(monkeypatch)
    with monkeypatch.context() as run_patches:
        await _assert_prepared_run_over_signed_http(run_patches, tmp_path)
    with monkeypatch.context() as planning_patches:
        await _assert_prepared_planning_over_signed_http(planning_patches, tmp_path)
    with monkeypatch.context() as turn_patches:
        await _assert_public_prepared_turn_over_signed_http(turn_patches)
    with monkeypatch.context() as clarification_patches:
        await _assert_public_prepared_turn_over_signed_http(clarification_patches, clarification=True)
    with monkeypatch.context() as new_turn_patches:
        await _assert_public_prepared_turn_over_signed_http(new_turn_patches, new_conversation=True)
    with monkeypatch.context() as northbound_patches:
        await _assert_public_prepared_turn_over_signed_http(northbound_patches, northbound=True)
    with monkeypatch.context() as metadata_patches:
        await _assert_public_prepared_turn_over_signed_http(
            metadata_patches, northbound=True, metadata={"project": "replacement"},
        )
    with monkeypatch.context() as workbench_patches:
        await _assert_public_prepared_turn_over_signed_http(workbench_patches, use_workbench=True)
    with monkeypatch.context() as joint_metadata_patches:
        await _assert_public_prepared_turn_over_signed_http(
            joint_metadata_patches, use_workbench=True, metadata={"project": "replacement"},
        )
    with monkeypatch.context() as knowledge_patches:
        await _assert_public_prepared_turn_over_signed_http(
            knowledge_patches, use_workbench=True, use_knowledge_scope=True,
        )
    with monkeypatch.context() as ephemeral_patches:
        await _assert_signed_ephemeral_stream(ephemeral_patches, tmp_path)
    with monkeypatch.context() as callback_patches:
        await _assert_automation_proposal_callback(callback_patches)


async def _assert_shared_aidp_over_signed_http(monkeypatch, tmp_path):
    from fastapi import Request

    from ext_components.aidp.database import aidp_permission_db
    from ext_components.aidp.services import aidp_service
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.local_tool_execution import build_local_tool
    from infrastructure.rdb import account_access
    from contracts.agentos import PreparedConversationScope
    from contracts.model import WorkbenchGenerationConfig
    from infrastructure.shared_aidp_tool import SCOPED_SHARED_AIDP_CATALOG_ID
    from management.services.agent.preparation import evaluation_snapshot, local_tool
    from management.services.agent.preparation.run import apply_root_generation_overlay
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from runtime.agentos import prepared_evaluation, prepared_local_tool, prepared_run
    from runtime.executions import LocalExecutionRegistry

    provider = FastAPI()
    searches = []
    retrieval_options = []
    catalog_calls = []
    groups = [17]
    acl = [
        {"kb_id": "group-kb", "kds_name": "Allowed", "tenant_id": "tenant-a",
         "owner_user_id": "owner", "group_ids": [17], "ingroup_permission": "READ_ONLY"},
        {"kb_id": "private-kb", "kds_name": "Private", "tenant_id": "tenant-a",
         "owner_user_id": "owner", "group_ids": [17], "ingroup_permission": "PRIVATE"},
    ]

    @provider.post("/KnowledgeBase/Tenants/shared-provider/KnowledgeBases/0/Count")
    async def count(request: Request):
        catalog_calls.append(request.headers.get("authorization"))
        return {"count": 2}

    @provider.get("/KnowledgeBase/Tenants/shared-provider/KnowledgeBases")
    async def catalog():
        return {"value": [{"kds_id": "group-kb"}, {"kds_id": "private-kb"}]}

    @provider.post("/KnowledgeBase/Tenants/shared-provider/Retrieval/FusionSearch")
    async def retrieve(request: Request):
        payload = await request.json()
        searches.append((request.headers.get("authorization"), payload["kds_list"]))
        retrieval_options.append((payload["search_method"], payload["top_k"]))
        return {"result": []}

    observed_whitelists = []

    async def run(info, thread_manager):
        configured, = info.agent_config.tools
        expected = ["group-kb"] if groups else []
        assert configured.metadata["allowed_kds_set"] == expected
        tool = NexentAgent.create_local_tool(SimpleNamespace(observer=None), configured)
        result = await asyncio.to_thread(tool.forward, "fixture query", ["Private", "Allowed"])
        assert "Private" in result
        observed_whitelists.append(expected)
        yield json.dumps({"type": "thought", "content": "scope checked"})
        yield json.dumps({"type": "final_answer", "content": "done"})

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_evaluation_router())
    runtime.include_router(prepared_run.create_prepared_run_router())
    monkeypatch.setattr(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path / "shared-aidp-runs"))
    monkeypatch.setattr(prepared_evaluation, "agent_run_manager", LocalExecutionRegistry())
    monkeypatch.setattr(prepared_evaluation, "agent_run", run)
    monkeypatch.setattr(account_access, "get_user_role_by_tenant",
                        lambda user, tenant: "DEV" if (user, tenant) == ("user-a", "tenant-a") else "")
    monkeypatch.setattr(account_access, "query_group_ids_by_user_in_tenant",
                        lambda user, tenant: groups if (user, tenant) == ("user-a", "tenant-a") else [])
    monkeypatch.setattr(aidp_permission_db, "list_all_permissions_by_tenant",
                        lambda tenant_id: acl if tenant_id == "tenant-a" else [])
    model = {
        "model_id": 49, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm",
        "model_name": "fixture-model", "model_repo": None, "display_name": "eval_llm",
        "api_key": "runtime-llm", "base_url": "https://fixture.invalid/v1", "update_time": "revision-1",
    }
    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", lambda _model, _tenant: model)
    monkeypatch.setattr(evaluation_snapshot, "get_model_records", lambda _filters, _tenant: [model])
    row = {
        "tool_id": 10, "tool_instance_id": 21, "name": "aidp_search", "class_name": "AidpSearchTool",
        "source": "local", "description": "Shared AIDP", "inputs": None, "usage": None, "output_type": "string",
        "instance_params": {}, "params": [{"name": "kds_list", "default": '["group-kb","private-kb"]'},
                                           {"name": "top_k", "default": 10},
                                           {"name": "search_method", "default": "hybrid_search"}],
    }
    for module in (evaluation_snapshot, prepared_local_tool):
        monkeypatch.setattr(module, "read_bound_local_tools", lambda *_: [row])
    for module in (local_tool, prepared_local_tool):
        monkeypatch.setattr(module, "read_shared_aidp_catalog_tool",
                            lambda tool_id, tenant: row if (tool_id, tenant) == (10, "tenant-a") else None)
    scoped_runs = []

    async def start_scoped(payload, actor):
        assert payload.workbench_config_version == 3
        assert payload.resource.tools[0].version == "3"
        info = await asyncio.to_thread(prepared_evaluation.prepare_run_snapshot, payload, actor)
        scoped_runs.append([json.loads(chunk) async for chunk in run(info, None)])
        return AgentRunReference(conversation_id=payload.conversation_id, run_id=payload.run_id)

    monkeypatch.setattr(prepared_run, "start_prepared_run", start_scoped)

    with serve(provider) as provider_url, serve(runtime) as runtime_url:
        agent = AgentConfig(
            agent_id=9, version_no=4, name="eval", description="Shared AIDP scope",
            prompt_templates={"system_prompt": "Evaluate the search"}, model_name="eval_llm",
            tools=[build_local_tool(row, "en", None, None)],
        )
        prepared = evaluation_snapshot.export_snapshot(
            agent, [create_model_config_from_record(model)], "question", None,
            tenant_id="tenant-a", conversation_id=-61, language="en",
        )
        assert isinstance(prepared, PreparedEvaluationRun)
        for secret in (provider_url, "synthetic-shared-aidp-key", "shared-provider", "private-kb", "group-kb"):
            assert secret not in prepared.model_dump_json()
        assert catalog_calls == []

        monkeypatch.setattr(environment, "AIDP_SERVER_URL", provider_url)
        monkeypatch.setattr(environment, "AIDP_API_KEY", "synthetic-shared-aidp-key")
        monkeypatch.setattr(environment, "AIDP_TENANT_ID", "shared-provider")
        monkeypatch.setattr(aidp_service, "AIDP_TENANT_ID", "shared-provider")
        client = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        result = await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert result.events == [
            {"type": "thought", "content": "scope checked"}, {"type": "final_answer", "content": "done"},
        ]
        groups.clear()
        assert (await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")).answer == "done"

        groups.append(17)
        scoped_tool = build_local_tool(row, "en", None, None)
        scoped_tool.params.update(kds_list=["group-kb"], search_method="full_text_search", top_k=7)
        scoped_tool.metadata = {SCOPED_SHARED_AIDP_CATALOG_ID: row["tool_id"]}
        workbench_agent = agent.model_copy(update={"tools": [scoped_tool]})
        generation = WorkbenchGenerationConfig()
        models = [create_model_config_from_record(model)]
        source_alias = apply_root_generation_overlay(models, workbench_agent, generation.model_dump())
        reference = AgentRunReference(conversation_id=61, run_id="e" * 32)
        scoped = evaluation_snapshot.export_snapshot(
            workbench_agent, models, "question", None, tenant_id="tenant-a", conversation_id=61, language="en",
            prepared_conversation=PreparedConversationScope(**reference.model_dump(), workbench_config_version=3),
            root_generation=generation, source_model_alias=source_alias,
        )
        assert isinstance(scoped, PreparedAgentRun)
        for private in (provider_url, "synthetic-shared-aidp-key", "shared-provider", "private-kb"):
            assert private not in scoped.model_dump_json()
        assert scoped.resource.tools[0].parameters["options"] == {
            "kds_list": ["group-kb"], "search_method": "full_text_search", "top_k": 7,
        }
        assert await client.start_prepared_run(scoped, "user-a", "tenant-a") == reference
        groups.clear()
        assert await client.start_prepared_run(scoped, "user-a", "tenant-a") == reference

    assert observed_whitelists == [["group-kb"], [], ["group-kb"], []]
    assert catalog_calls == ["Bearer synthetic-shared-aidp-key"]
    assert searches == [("Bearer synthetic-shared-aidp-key", ["group-kb"])] * 2
    assert retrieval_options == [("hybrid_search", 10), ("full_text_search", 7)]
    assert len(scoped_runs) == 2 and all(events[-1]["content"] == "done" for events in scoped_runs)


async def _assert_stored_local_tool_over_signed_http(monkeypatch, tmp_path):
    from fastapi import Request, Response

    from infrastructure import ind_aidp_images, langchain_plugins
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import evaluation_snapshot
    from management.services.knowledge_base.providers import aidp as independent_aidp_proxy
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import ProcessType
    from runtime.agentos import prepared_evaluation, prepared_langchain, prepared_local_tool
    from runtime.executions import LocalExecutionRegistry

    model_record = {
        "model_id": 18, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm",
        "model_name": "fixture-model", "model_repo": None, "display_name": "eval_llm",
        "api_key": "local-llm", "base_url": "https://provider.invalid/v1", "update_time": "revision-1",
    }
    provider = FastAPI()
    calls = []
    aidp_calls = []
    image_refs = []

    @provider.post("/v1/datasets/fixture-private-dataset/retrieve")
    async def retrieve(request: Request):
        payload = await request.json()
        calls.append((request.headers.get("authorization"), payload["query"], payload["retrieval_model"]["top_k"]))
        return {"records": [{"score": 0.8, "segment": {"content": "scoped Dify result"}}]}

    @provider.post("/KnowledgeBase/Tenants/provider-fixture/Retrieval/FusionSearch")
    async def retrieve_aidp(request: Request):
        payload = await request.json()
        aidp_calls.append(("search", request.headers.get("authorization"), payload["kds_list"]))
        return {"result": [{
            "id": "image-fixture", "chunk_type": "image", "title": "diagram",
            "text": "scoped AIDP result", "file_url": "private-aidp-kb/p.png", "score": 0.9,
        }]}

    @provider.get("/KnowledgeBase/Tenants/provider-fixture/KnowledgeBases/private-aidp-kb/p.png")
    async def get_aidp_image(request: Request):
        aidp_calls.append(("image", request.headers.get("authorization")))
        return Response(content=b"fixture-png", media_type="image/png")

    def capture_picture(_name, kind, content):
        if kind == ProcessType.PICTURE_WEB:
            image_refs.extend(json.loads(content)["images_url"])

    plugin_dir = tmp_path / "langchain"
    plugin_dir.mkdir()
    plugin = plugin_dir / "fixture.py"
    plugin.write_text(
        'from langchain_core.tools import tool\n@tool\n'
        'def fixture_double(value: int) -> int:\n    """Double the input."""\n    return value * 2\n',
        encoding="utf-8",
    )
    original_plugin = plugin.read_bytes()
    monkeypatch.setattr(langchain_plugins, "LANGCHAIN_PLUGIN_DIRECTORY", plugin_dir)
    tool_workspace = tmp_path / "configured-file-tool"
    model_overrides = {"18": {"extra_params": {"__custom__": {"provider_setting": "local-private-model-body"}}}}

    def read_model_override(agent_id, version_no, tenant_id):
        assert (agent_id, version_no, tenant_id) == (8, 4, "tenant-a")
        return model_overrides

    monkeypatch.setattr(prepared_evaluation, "read_agent_model_overrides", read_model_override)

    async def run(info, thread_manager):
        dify_config, plugin_config, aidp_config, workspace_config = info.agent_config.tools
        assert (dify_config.name, plugin_config.name, aidp_config.name, workspace_config.name) == (
            "dify_search", "fixture_double", "ind_aidp_search", "create_file",
        )
        assert info.model_config_list[0].extra_body == {"provider_setting": "local-private-model-body"}
        create_file = NexentAgent.create_local_tool(SimpleNamespace(observer=None), workspace_config)
        create_file.forward("agentos.txt", "workspace tool")
        assert (tool_workspace / "agentos.txt").read_text(encoding="utf-8") == "workspace tool"
        assert NexentAgent.create_langchain_tool(None, plugin_config).forward(value=7) == 14
        tool = NexentAgent.create_local_tool(SimpleNamespace(observer=None), dify_config)
        answer = await asyncio.to_thread(tool.forward, "fixture query")
        assert "scoped Dify result" in answer
        observer = SimpleNamespace(add_message=capture_picture)
        aidp = NexentAgent.create_local_tool(SimpleNamespace(observer=observer), aidp_config)
        aidp_answer = await asyncio.to_thread(aidp.forward, "fixture query")
        assert "scoped AIDP result" in aidp_answer and "/__aidp_image__/" in aidp_answer
        yield json.dumps({"type": "thought", "content": "lookup"})
        yield json.dumps({"type": "final_answer", "content": "scoped Dify result"})

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_evaluation_router())
    monkeypatch.setattr(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path / "local-tool-runs"))
    monkeypatch.setattr(prepared_evaluation, "agent_run_manager", LocalExecutionRegistry())
    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", lambda model_id, tenant_id: model_record)
    monkeypatch.setattr(prepared_evaluation, "agent_run", run)
    monkeypatch.setattr(evaluation_snapshot, "get_model_records", lambda _filters, _tenant: [model_record])
    monkeypatch.setattr(ind_aidp_images, "IND_AIDP_IMAGE_SIGNING_KEY", "synthetic-aidp-image-signing")

    with serve(provider) as provider_url, serve(runtime) as runtime_url:
        row = {
            "tool_instance_id": 23, "tool_id": 5, "name": "dify_search", "class_name": "DifySearchTool",
            "source": "local", "description": "Provider search", "usage": None, "inputs": None,
            "output_type": "string", "instance_params": {"top_k": 2},
            "params": [{"name": name, "default": value} for name, value in {
                "server_url": f"{provider_url}/v1", "api_key": "synthetic-runtime-dify-key",
                "dataset_ids": '["fixture-private-dataset"]', "top_k": 5,
                "search_method": "semantic_search", "rerank": False, "rerank_model_name": "",
            }.items()],
        }
        aidp_params = {
            "server_url": provider_url, "api_key": "synthetic-private-aidp-key",
            "tenant_id": "provider-fixture", "kds_list": ["private-aidp-kb"],
        }
        aidp_row = {
            **row, "tool_instance_id": 24, "tool_id": 6, "name": "ind_aidp_search",
            "class_name": "IndependentAidpSearchTool", "instance_params": aidp_params,
            "params": [{"name": name, "default": None} for name in aidp_params],
        }
        file_row = {
            **row, "tool_instance_id": 26, "tool_id": 8, "name": "create_file",
            "class_name": "CreateFileTool", "description": "Create a file",
            "instance_params": {}, "params": [{"name": "init_path", "default": str(tool_workspace)}],
        }
        enabled = [row, aidp_row, file_row]
        plugin_row = {
            **row, "tool_instance_id": 25, "tool_id": 7, "name": "fixture_double",
            "class_name": "fixture_double", "source": "langchain", "description": "Double the input",
            "instance_params": {}, "params": [], "output_type": "integer",
        }

        def read_plugin(agent_id, version_no, tenant_id, names):
            assert (agent_id, version_no, names) == (8, 4, ["fixture_double"])
            return [plugin_row] if tenant_id == "tenant-a" else []

        for module in (evaluation_snapshot, prepared_langchain):
            monkeypatch.setattr(module, "read_bound_langchain_tools", read_plugin)

        def read_image_tool(**scope):
            assert scope == {"agent_id": 8, "tool_id": 6, "tenant_id": "tenant-a", "version_no": 4}
            return {"params": aidp_params}

        monkeypatch.setattr(independent_aidp_proxy, "query_tool_instances_by_id", read_image_tool)
        monkeypatch.setattr(independent_aidp_proxy, "query_tools_by_ids", lambda ids: [aidp_row] if ids == [6] else [])

        def read_tools(agent_id, version_no, tenant_id, names):
            assert (agent_id, version_no, names) == (8, 4, ["dify_search", "ind_aidp_search", "create_file"])
            return enabled if tenant_id == "tenant-a" else []

        for module in (evaluation_snapshot, prepared_local_tool):
            monkeypatch.setattr(module, "read_bound_local_tools", read_tools)
        model = create_model_config_from_record(model_record).model_copy(update={
            "extra_body": {"provider_setting": "local-private-model-body"},
        })
        agent = AgentConfig(
            agent_id=8, version_no=4, name="eval", description="Scoped tool",
            prompt_templates={"system_prompt": "Evaluate the search"}, model_name=model.cite_name,
            tools=[
                build_local_tool(row, "en", None, None), langchain_plugins.build_langchain_tool(plugin_row),
                build_local_tool(aidp_row, "en", None, None), build_local_tool(file_row, "en", None, None),
            ],
        )
        prepared = evaluation_snapshot.export_snapshot(
            agent, [model], "question", None, tenant_id="tenant-a", conversation_id=-60, language="en",
            agent_model_overrides=model_overrides,
        )
        assert isinstance(prepared, PreparedEvaluationRun)
        for secret in (
            provider_url, "synthetic-runtime-dify-key", "fixture-private-dataset",
            "synthetic-private-aidp-key", "private-aidp-kb", "provider-fixture", "return value * 2",
            "local-private-model-body", "configured-file-tool",
        ):
            assert secret not in prepared.model_dump_json()

        client = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        result = await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert result.events == [
            {"type": "thought", "content": "lookup"}, {"type": "final_answer", "content": "scoped Dify result"},
        ]
        image_url, = image_refs
        assert image_url.startswith("/api/ind-aidp/images/")
        image = await independent_aidp_proxy.fetch_ind_aidp_image_impl(image_url.rsplit("/", 1)[-1])
        assert image == (b"fixture-png", "image/png")
        assert next(tool for tool in prepared.resource.tools if tool.tool_id == "langchain").version == "1"
        plugin.write_text('raise AssertionError("changed plugin must not execute")\n', encoding="utf-8")
        with pytest.raises(RuntimeUpstreamError) as changed_plugin:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_plugin.value.status_code == 409
        assert "AGENTOS_LANGCHAIN_REVISION_MISMATCH" in changed_plugin.value.content.decode()
        plugin.write_bytes(original_plugin)
        file_row["instance_params"]["init_path"] = str(tmp_path / "different-path")
        with pytest.raises(RuntimeUpstreamError) as changed_workspace:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_workspace.value.status_code == 409
        assert "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH" in changed_workspace.value.content.decode()
        file_row["instance_params"].clear()
        body = model_overrides["18"]["extra_params"]["__custom__"]
        body["provider_setting"] = "changed-provider-body"
        with pytest.raises(RuntimeUpstreamError) as changed_body:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_body.value.status_code == 409
        assert "AGENTOS_MODEL_BODY_REVISION_MISMATCH" in changed_body.value.content.decode()
        body["provider_setting"] = "local-private-model-body"
        row["instance_params"]["top_k"] = 4
        with pytest.raises(RuntimeUpstreamError) as changed:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed.value.status_code == 409
        assert "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH" in changed.value.content.decode()
        with pytest.raises(RuntimeUpstreamError) as other_tenant:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-b")
        assert other_tenant.value.status_code == 404
        enabled.clear()
        with pytest.raises(RuntimeUpstreamError) as disabled:
            await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert disabled.value.status_code == 404
        assert "AGENTOS_LOCAL_TOOL_NOT_FOUND" in disabled.value.content.decode()

    assert calls == [("Bearer synthetic-runtime-dify-key", "fixture query", 2)]
    assert aidp_calls == [
        ("search", "Bearer synthetic-private-aidp-key", ["private-aidp-kb"]),
        ("image", "Bearer synthetic-private-aidp-key"),
    ]


async def _assert_prepared_evaluation_over_signed_http(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from infrastructure import agent_attachments
    from infrastructure.object_storage.client import minio_client
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.agent_tool_config import build_parallel_executor_tool_config
    from infrastructure import ind_aidp_images
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.knowledge_base.providers import aidp as independent_aidp_proxy
    from management.services.agent import runtime_client
    from management.services.agent.preparation import analysis, evaluation_snapshot, knowledge_search
    from management.services.model import adapter as management_model_adapter
    from management.services.knowledge_base import permission as knowledge_permission
    from infrastructure.a2a_execution import build_external_agent_config
    from nexent.core.agents.agent_model import AgentConfig, ToolConfig
    from infrastructure.mcp_execution import build_mcp_tool
    from nexent.core.agents.nexent_agent import NexentAgent
    from runtime.agentos import (
        prepared_analysis, prepared_attachments, prepared_evaluation, prepared_knowledge,
        prepared_local_tool, prepared_mcp, prepared_skills,
    )
    from runtime.executions import LocalExecutionRegistry

    key = "synthetic-prepared-evaluation-fixture-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "docker")
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_DEFAULT_SCOPE", "session")
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS", False)
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_WORKSPACE_MODE", "legacy")

    monkeypatch.setattr(agent_attachments, "MINIO_DEFAULT_BUCKET", "bucket")
    monkeypatch.setattr(prepared_attachments, "NORTHBOUND_EXTERNAL_URL", "https://gateway.invalid")
    signed_files = []

    def get_file_url(key, bucket):
        signed_files.append((key, bucket))
        return True, "https://storage.invalid/fresh-evaluation-link"

    monkeypatch.setattr(minio_client, "get_file_url", get_file_url)
    lookups = []
    invocations = []
    skill_stages = []
    registry = LocalExecutionRegistry()
    monkeypatch.setattr(prepared_evaluation, "agent_run_manager", registry)

    def lookup(model_id, tenant_id):
        lookups.append((model_id, tenant_id))
        return record

    record = {
        "model_id": 11, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm", "model_name": "provider-model",
        "model_repo": None, "display_name": "evaluation_llm", "api_key": "only-in-runtime",
        "base_url": "https://provider.example/v1", "update_time": "revision-1",
    }

    external_row = {
        "external_agent_id": 19, "name": "External", "description": "Authorized peer",
        "agent_url": "https://external.example/private",
        "security_schemes": {"auth": {"scheme": "Bearer"}},
        "security_requirements": [{"schemes": {"auth": []}}],
        "security_credentials": {"auth": "local-peer-token"},
    }
    external = build_external_agent_config(external_row, external_row["agent_url"])
    external_reads = []

    def read_external(parent_id, tenant_id, ids):
        external_reads.append((parent_id, tenant_id, ids))
        return {19: external_row} if tenant_id == "tenant-a" else {}

    monkeypatch.setattr(prepared_evaluation, "read_external_agent_bindings", read_external)

    mcp_tool = {
        "tool_instance_id": 27, "name": "catalog_lookup", "class_name": "catalog_lookup",
        "origin_name": "catalog_lookup", "description": "Catalog", "inputs": None, "output_type": "object",
        "usage": "catalog", "params": [{"name": "scope", "default": "private-tool-default"}], "instance_params": {},
    }
    mcp_server = {
        "mcp_id": 32, "mcp_name": "catalog", "mcp_server": "https://mcp.example/private",
        "authorization_token": "runtime-mcp-token", "custom_headers": None, "enabled": True,
    }

    def read_mcp_tools(agent_id, version_no, tenant_id, names):
        assert (agent_id, version_no) == (7, 2)
        assert "catalog_lookup" in names
        return [mcp_tool] if tenant_id == "tenant-a" else []

    for module in (evaluation_snapshot, prepared_mcp):
        monkeypatch.setattr(module, "read_bound_mcp_tools", read_mcp_tools)
        monkeypatch.setattr(module, "read_mcp_execution_servers", lambda tenant_id: [mcp_server])

    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "tenant-a" / "summarize"
    (skill_dir / "config").mkdir(parents=True)
    guide = skill_dir / "SKILL.md"
    guide.write_text("---\nname: summarize\ndescription: Summarize\n---\nRuntime skill guide", encoding="utf-8")
    (skill_dir / "config" / "config.yaml").write_text("keep: true\nvalue: default", encoding="utf-8")
    skill = {"instance_id": 51, "name": "summarize", "description": "Summarize", "config": {"value": "local-secret"}}
    derived_tool = {
        **mcp_tool, "tool_id": 52, "skill_instance_ids": [51], "name": "skill_lookup",
        "class_name": "skill_lookup", "origin_name": "skill_lookup",
        "params": [{"name": "scope", "default": "private-skill-tool-value"}],
    }

    def read_derived(agent_id, version_no, tenant_id, names):
        assert (agent_id, version_no, names) == (7, 2, ["skill_lookup"])
        return [derived_tool] if tenant_id == "tenant-a" else []

    for module in (evaluation_snapshot, prepared_mcp):
        monkeypatch.setattr(module, "read_skill_derived_mcp_tools", read_derived)

    skill_metadata = {"agent_id": 7, "version_no": 2, "tenant_id": "tenant-a"}
    skill_tools = [
        ToolConfig(
            class_name=class_name, name=name, source="builtin", usage="builtin", metadata=skill_metadata,
            params={"local_skills_dir": str(skill_root), **params},
        )
        for class_name, name, params in [
            ("RunSkillScriptTool", "run_skill_script",
             {"workspace_path": None, "isolated_skills_root": False, "authorized_skill_names": ["summarize"]}),
            ("ReadSkillMdTool", "read_skill_md", {"isolated_skills_root": False}),
            ("ReadSkillConfigTool", "read_skill_config", {"config_overrides": {"summarize": skill["config"]}}),
        ]
    ]

    def read_skills(agent_id, version_no, tenant_id):
        assert (agent_id, version_no) == (7, 2)
        return [skill] if tenant_id == "tenant-a" else []

    monkeypatch.setattr(environment, "CONTAINER_SKILLS_PATH", str(skill_root))
    monkeypatch.setattr(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path / "runs"))
    monkeypatch.setattr(evaluation_snapshot, "read_bound_skills", read_skills)
    monkeypatch.setattr(prepared_skills, "read_bound_skills", read_skills)

    derived_local = {
        "tool_id": 54, "skill_instance_ids": [51], "name": "dify_search", "class_name": "DifySearchTool",
        "source": "local", "description": "Skill lookup", "inputs": None, "usage": None, "output_type": "string",
        "instance_params": {}, "params": [{"name": name, "default": value} for name, value in {
            "server_url": "https://derived-provider.invalid/v1", "api_key": "private-skill-local-key",
            "dataset_ids": '["derived-private-dataset"]', "top_k": 3,
        }.items()],
    }

    derived_aidp = {
        **derived_local, "tool_id": 55, "name": "ind_aidp_search", "class_name": "IndependentAidpSearchTool",
        "params": [{"name": name, "default": value} for name, value in {
            "server_url": "https://derived-aidp.invalid", "api_key": "private-derived-aidp-key",
            "tenant_id": "derived-provider", "kds_list": ["derived-image-kb"],
        }.items()],
    }

    def read_local_skill_tool(agent_id, version_no, tenant_id, names):
        assert (agent_id, version_no) == (7, 2)
        return [row for row in (derived_local, derived_aidp) if row["name"] in names and tenant_id == "tenant-a"]

    monkeypatch.setattr(ind_aidp_images, "IND_AIDP_IMAGE_SIGNING_KEY", "synthetic-derived-image-signing")
    monkeypatch.setattr(evaluation_snapshot, "read_bound_local_tools", lambda *_: [])
    for module in (evaluation_snapshot, prepared_local_tool, independent_aidp_proxy):
        monkeypatch.setattr(module, "read_skill_derived_local_tools", read_local_skill_tool)

    knowledge_row = {
        "knowledge_id": 90, "index_name": "kb-open", "knowledge_name": "Open", "tenant_id": "tenant-a",
        "created_by": "owner", "group_ids": "42", "ingroup_permission": "READ_ONLY", "embedding_model_id": 91,
    }
    blocked_knowledge = dict(knowledge_row, knowledge_id=92, index_name="kb-blocked", knowledge_name="Blocked", group_ids="43")
    embedding_row = dict(record, model_id=91, model_type="embedding", api_key="private-knowledge-embedding")
    groups = [42]
    knowledge_queries = []

    def read_knowledge(tenant_id, names):
        if tenant_id != "tenant-a":
            return []
        return [row for row in (knowledge_row, blocked_knowledge) if row["index_name"] in names]

    def accurate_search(**kwargs):
        knowledge_queries.append(kwargs)
        return [
            {"index": "kb-open", "score": 1, "document": {"content": content, "path_or_url": path}}
            for content, path in [("authorized-document", "reports/allowed.txt"), ("secret-document", "reports/hidden.txt")]
        ]

    membership = {"tenant_id": "tenant-a", "user_role": "DEV"}
    for module in (knowledge_search, prepared_knowledge):
        monkeypatch.setattr(module, "read_knowledge_search_records", read_knowledge)
        monkeypatch.setattr(module, "get_model_by_model_id", lambda model_id, tenant_id: embedding_row
                            if (model_id, tenant_id) == (91, "tenant-a") else None)
    monkeypatch.setattr(knowledge_permission, "get_user_tenant_by_user_id", lambda user_id: membership)
    monkeypatch.setattr(knowledge_permission, "query_group_ids_by_user", lambda user_id: list(groups))
    monkeypatch.setattr(prepared_knowledge, "read_knowledge_search_actor", lambda user_id: (membership, list(groups)))
    monkeypatch.setattr(prepared_knowledge, "build_adapter_fresh", lambda *args: object())
    monkeypatch.setattr(prepared_knowledge, "create_elasticsearch_core", lambda **kwargs: SimpleNamespace(accurate_search=accurate_search))
    kb_tool = ToolConfig(
        class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
        params={"index_names": ["kb-open", "kb-blocked"], "search_mode": "accurate", "top_k": 4},
    )
    assert knowledge_search.prepare_knowledge_search(kb_tool, "user-a", "tenant-a", ["reports/allowed.txt"])

    media_model = dict(record, model_id=93, model_type="vlm", api_key="private-image-model-key")
    media_adapter = object()
    media_assemblies = []

    def read_media_model(model_id, tenant_id):
        return media_model if (model_id, tenant_id) == (93, "tenant-a") else None

    def create_media_adapter(record, modality, slot, tenant_id):
        media_assemblies.append((record["model_id"], modality, slot, tenant_id))
        return media_adapter

    monkeypatch.setattr(management_model_adapter, "get_model_by_model_id", read_media_model)
    monkeypatch.setattr(prepared_analysis, "get_model_by_model_id", read_media_model)
    monkeypatch.setattr(prepared_analysis, "get_adapter_from_config", create_media_adapter)
    image_tool = ToolConfig(
        class_name="AnalyzeImageTool", name="analyze_image", source="local", params={"selected_model_id": "93"},
    )
    assert analysis.prepare_analysis_tool(image_tool, "tenant-a")

    async def run(info, thread_manager):
        assert registry.get_agent_run_info(-42, "user-a") is info
        assert info.sandbox_config.level.value == "docker"
        assert info.sandbox_config.scope.value == "session"
        assert info.sandbox_config.output_dir.endswith("outputs")
        guidance, = info.agent_config.context_items
        assert guidance.id == "system:sandbox_workspace_guidance"
        assert "management-local-executor" not in guidance.content["text"]
        assert info.model_config_list[0].api_key == "only-in-runtime"
        assert info.agent_config.model_name == "evaluation_llm"
        assert info.model_config_list[0].temperature == 0.17
        child, = info.agent_config.worker_agents
        assert (child.agent_id, child.version_no, child.invocation_name, child.model_name) == (
            8, 5, "child_lookup", "evaluation_llm",
        )
        peer, = child.external_a2a_agents
        assert peer.url == "https://external.example/private"
        assert peer.custom_headers == {"Authorization": "Bearer local-peer-token"}
        assert info.agent_config.tools[1].params == {"scope": "private-tool-default"}
        by_name = {tool.name: tool for tool in info.agent_config.tools}
        assert list(by_name) == [
            "download_from_s3", "catalog_lookup", "parallel_executor",
            "run_skill_script", "read_skill_md", "read_skill_config", "skill_lookup", "knowledge_base_search",
            "analyze_image", "dify_search", "ind_aidp_search",
        ]
        parallel = NexentAgent.create_local_tool(None, by_name["parallel_executor"])
        assert parallel.default_timeout_seconds == 47
        assert parallel.inputs["timeout"]["default"] == 47
        assert parallel.forward([]) == []
        assert by_name["skill_lookup"].params == {"scope": "private-skill-tool-value"}
        knowledge = NexentAgent.create_local_tool(SimpleNamespace(observer=None), by_name["knowledge_base_search"])
        result = knowledge.forward("facts", ["Blocked"])
        assert "authorized-document" in result and "secret-document" not in result
        assert "no read permission" in result
        assert knowledge_queries == [{"index_names": ["kb-open"], "query_text": "facts", "top_k": 4}]
        image = NexentAgent.create_local_tool(SimpleNamespace(observer=None), by_name["analyze_image"])
        assert image.selected_model_id == 93 and image.vlm_model is media_adapter
        skill_search = NexentAgent.create_local_tool(SimpleNamespace(observer=None), by_name["dify_search"])
        assert (skill_search.api_key, skill_search.dataset_ids, skill_search.top_k) == (
            "private-skill-local-key", ["derived-private-dataset"], 3,
        )
        aidp_tool = NexentAgent.create_local_tool(SimpleNamespace(observer=None), by_name["ind_aidp_search"])
        image_ref = aidp_tool.image_url_builder("derived-image-kb/p.png").rsplit("/", 1)[-1]
        image_payload = independent_aidp_proxy._decode_image_ref(image_ref)
        assert image_payload["skill_revision"]
        assert independent_aidp_proxy._resolve_image_credentials(image_payload) == (
            "https://derived-aidp.invalid", "private-derived-aidp-key", "derived-provider", "derived-image-kb/p.png",
        )
        derived_aidp["skill_instance_ids"] = [53]
        try:
            with pytest.raises(independent_aidp_proxy.IndependentAidpServiceError, match="changed"):
                independent_aidp_proxy._resolve_image_credentials(image_payload)
        finally:
            derived_aidp["skill_instance_ids"] = [51]
        with pytest.raises(PermissionError):
            image.forward(["s3:/bucket/attachments/user-b/denied.png"], "Inspect the image")
        reader = NexentAgent.create_builtin_tool(None, by_name["read_skill_md"])
        config_reader = NexentAgent.create_builtin_tool(None, by_name["read_skill_config"])
        stage = prepared_skills.skill_stage_path(info.workspace_path)
        assert stage.is_dir()
        assert not stage.is_relative_to(tmp_path / "runs")
        skill_stages.append(stage)
        assert "Runtime skill guide" in reader.forward("summarize")
        assert json.loads(config_reader.forward("summarize")) == {"keep": True, "value": "local-secret"}
        assert "not authorized" in config_reader.forward("other-skill").lower()
        host, = info.mcp_host
        assert host["headers"] == {"Authorization": "runtime-mcp-token"}
        assert host["allowed_tools"] == {"catalog_lookup": "catalog_lookup", "skill_lookup": "skill_lookup"}
        assert info.user_context["user_id"] == "user-a"
        assert "attachments/user-a/report.txt" in info.query
        assert "fresh-evaluation-link" in info.history[0].content
        assert "earlier" in info.history[0].content
        assert info.minio_files[0]["url"] == "s3://bucket/attachments/user-a/report.txt"
        access = info.agent_config.tools[0].metadata["validate_url_access"]
        access(["s3://bucket/attachments/user-a/allowed.txt"])
        with pytest.raises(PermissionError):
            access(["s3://bucket/attachments/user-b/denied.txt"])
        invocations.append((info.user_id, info.tenant_id, info.conversation_id))
        yield json.dumps({"type": "thought", "content": "step"})
        yield json.dumps({"type": "final_answer", "content": "answer"})

    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", lookup)
    monkeypatch.setattr(prepared_evaluation, "agent_run", run)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_evaluation_router())

    model = create_model_config_from_record(record).model_copy(update={"temperature": 0.17})
    agent = AgentConfig(
        agent_id=7, version_no=2, name="evaluation_agent", description="Prepared evaluation",
        prompt_templates={"system_prompt": "Answer the query"}, model_name=model.cite_name,
        context_items=[{
            "id": "system:restricted_python_execution", "type": "system",
            "content": {"text": "management-local-executor"},
        }],
        worker_agents=[AgentConfig(
            agent_id=8, version_no=5, name="child", invocation_name="child_lookup",
            description="Static child", model_name=model.cite_name, tools=[], external_a2a_agents=[external],
        )],
        tools=[ToolConfig(
            class_name="DownloadFromS3Tool", name="download_from_s3", source="builtin", usage="builtin",
            params={"workspace_path": "/management/workspace"},
            metadata={"validate_url_access": lambda _urls: None},
        ), build_mcp_tool(mcp_tool), build_parallel_executor_tool_config(47), *skill_tools,
               build_mcp_tool(derived_tool), kb_tool, image_tool, build_local_tool(derived_local, "zh", None, None),
               build_local_tool(derived_aidp, "zh", None, None)],
    )
    monkeypatch.setattr(evaluation_snapshot, "get_model_records", lambda _filters, _tenant: [record])
    case = EvaluationAgentRun(agent_id=7, version_no=2, query="question", conversation_id=-42)
    request_input = evaluation_snapshot.build_evaluation_input(
        case.query, None, [SimpleNamespace(role="user", content="earlier", minio_files=[{
            "name": "report.txt", "url": "s3://bucket/attachments/user-a/report.txt",
            "presigned_url": "previous-link-from-history",
        }])], "user-a", "tenant-a",
    )
    prepared = evaluation_snapshot.export_snapshot(
        agent, [model], case.query, None, tenant_id="tenant-a", conversation_id=-42, language="zh", run_input=request_input,
    )
    assert isinstance(prepared, PreparedEvaluationRun)
    assert "/management/workspace" not in prepared.model_dump_json()
    assert "only-in-runtime" not in prepared.model_dump_json()
    assert external_row["agent_url"] not in prepared.model_dump_json()
    assert "local-peer-token" not in prepared.model_dump_json()
    assert "management-local-executor" not in prepared.model_dump_json()
    assert prepared.resource.evaluation_options.render_executor_context
    assert "previous-link-from-history" not in prepared.model_dump_json()
    assert "runtime-mcp-token" not in prepared.model_dump_json()
    assert "private-tool-default" not in prepared.model_dump_json()
    assert "private-skill-tool-value" not in prepared.model_dump_json()
    assert next(tool for tool in prepared.resource.tools if tool.tool_id == "mcp" and tool.version == "2")
    assert "private-knowledge-embedding" not in prepared.model_dump_json()
    assert "private-image-model-key" not in prepared.model_dump_json()
    assert "private-skill-local-key" not in prepared.model_dump_json()
    assert "derived-private-dataset" not in prepared.model_dump_json()
    assert "private-derived-aidp-key" not in prepared.model_dump_json()
    assert next(tool for tool in prepared.resource.tools if tool.tool_id == "ind_aidp_search").version == "2"
    assert next(tool for tool in prepared.resource.tools if tool.tool_id == "dify_search").version == "2"
    assert mcp_server["mcp_server"] not in prepared.model_dump_json()
    assert "local-secret" not in prepared.model_dump_json()
    assert "Runtime skill guide" not in prepared.model_dump_json()

    async def prepare(payload, user_id, tenant_id):
        assert (payload, user_id, tenant_id) == (case, "user-a", "tenant-a")
        return prepared

    monkeypatch.setattr(evaluation_snapshot, "prepare_evaluation_snapshot", prepare)
    with serve(runtime) as runtime_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        monkeypatch.setattr(runtime_client, "_agentos_client", lambda: agentos)
        result = await runtime_client.forward_evaluation_case(case, "user-a", "tenant-a")
        assert result.answer == "answer"
        assert result.events == [
            {"type": "thought", "content": "step"}, {"type": "final_answer", "content": "answer"},
        ]
        assert "only-in-runtime" not in result.model_dump_json()
        assert signed_files == [("attachments/user-a/report.txt", "bucket")]
        invalid_parallel = prepared.model_copy(deep=True)
        parallel_binding = next(tool for tool in invalid_parallel.resource.tools if tool.tool_id == "parallel_executor")
        parallel_binding.parameters["default_timeout_seconds"] = 0
        with pytest.raises(RuntimeUpstreamError) as invalid:
            await agentos.run_prepared_evaluation(invalid_parallel, "user-a", "tenant-a")
        assert invalid.value.status_code == 422
        assert "AGENTOS_RESOURCE_UNSUPPORTED" in invalid.value.content.decode()
        assert invocations == [("user-a", "tenant-a", -42)]
        assert len(signed_files) == 2
        with pytest.raises(RuntimeUpstreamError) as foreign_attachment:
            await agentos.run_prepared_evaluation(prepared, "user-b", "tenant-a")
        assert foreign_attachment.value.status_code == 403
        assert "AGENTOS_ATTACHMENT_FORBIDDEN" in foreign_attachment.value.content.decode()
        assert len(signed_files) == 2
        with pytest.raises(RuntimeUpstreamError) as refused:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-b")
        assert refused.value.status_code == 404
        groups.clear()
        with pytest.raises(RuntimeUpstreamError) as revoked_knowledge:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert revoked_knowledge.value.status_code == 403
        assert "AGENTOS_KNOWLEDGE_FORBIDDEN" in revoked_knowledge.value.content.decode()
        groups.append(42)
        assert len(knowledge_queries) == 1
        mcp_server["authorization_token"] = "rotated-mcp-token"
        with pytest.raises(RuntimeUpstreamError) as changed_mcp:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_mcp.value.status_code == 409
        assert "AGENTOS_MCP_REVISION_MISMATCH" in changed_mcp.value.content.decode()
        mcp_server["authorization_token"] = "runtime-mcp-token"
        derived_tool["skill_instance_ids"] = [51, 53]
        with pytest.raises(RuntimeUpstreamError) as changed_derivation:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_derivation.value.status_code == 409
        assert "AGENTOS_MCP_REVISION_MISMATCH" in changed_derivation.value.content.decode()
        derived_tool["skill_instance_ids"] = [51]
        derived_local["skill_instance_ids"] = [51, 53]
        with pytest.raises(RuntimeUpstreamError) as changed_local_derivation:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_local_derivation.value.status_code == 409
        assert "AGENTOS_LOCAL_TOOL_REVISION_MISMATCH" in changed_local_derivation.value.content.decode()
        derived_local["skill_instance_ids"] = [51]
        original_guide = guide.read_bytes()
        guide.write_text("file revision changed", encoding="utf-8")
        with pytest.raises(RuntimeUpstreamError) as changed_skill:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_skill.value.status_code == 409
        assert "AGENTOS_SKILL_REVISION_MISMATCH" in changed_skill.value.content.decode()
        guide.write_bytes(original_guide)
        media_model["update_time"] = "revision-2"
        assemblies_before_rejection = list(media_assemblies)
        with pytest.raises(RuntimeUpstreamError) as changed_media:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed_media.value.status_code == 409
        assert "AGENTOS_ANALYSIS_MODEL_REVISION_MISMATCH" in changed_media.value.content.decode()
        assert media_assemblies == assemblies_before_rejection
        media_model["update_time"] = "revision-1"
        external_row["security_credentials"] = {"auth": "rotated-token"}
        with pytest.raises(RuntimeUpstreamError) as changed:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert changed.value.status_code == 409
        assert "AGENTOS_EXTERNAL_AGENT_REVISION_MISMATCH" in changed.value.content.decode()

        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            response = await client.post(
                f"{runtime_url}/api{AgentOperation.EVALUATION_CASE.value}", content=prepared.model_dump_json(),
            )
            assert response.status_code == 401

    assert lookups == [(11, "tenant-a")]
    assert media_assemblies and set(media_assemblies) == {(93, "vlm", "vlm", "tenant-a")}
    assert external_reads == [(8, "tenant-a", [19]), (8, "tenant-a", [19])]
    assert invocations == [("user-a", "tenant-a", -42)]
    assert registry.get_agent_run_info(-42, "user-a") is None
    assert skill_stages and not any(stage.exists() for stage in skill_stages)


async def _assert_resume_over_signed_http(monkeypatch):
    from runtime.agentos import resume

    run_id = "1" * 32
    reads = []

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    class Journal:
        def __init__(self, tenant_id, user_id, conversation_id, requested_run_id):
            assert (tenant_id, user_id, conversation_id, requested_run_id) == ("tenant-a", "user-a", 42, run_id)

        def replay(self, after_id):
            reads.append(after_id)
            return (
                [("1-0", {"kind": "chunk", "data": "data: earlier\n\n"})],
                [("2-0", {"kind": "chunk", "data": "data: replay\n\n"})],
                [("2-0", {"kind": "chunk", "data": "data: replay\n\n"})],
            )

        def wait(self, after_id):
            reads.append(after_id)
            return [
                ("3-0", {"kind": "chunk", "data": "data: live\n\n"}),
                ("4-0", {"kind": "terminal", "status": "completed"}),
            ]

    monkeypatch.setattr(resume, "_control_io", control_io)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=True))
    monkeypatch.setattr(resume, "RunJournal", Journal)
    monkeypatch.setattr(
        resume, "conversation_belongs_to",
        lambda conversation_id, *, user_id, tenant_id: (conversation_id, user_id, tenant_id) == (42, "user-a", "tenant-a"),
    )

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(resume.create_run_lifecycle_router())

    with serve(runtime) as runtime_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        request = AgentResume(conversation_id=42, run_id=run_id, after_event_id=f"{run_id}:1")
        response = await agentos.resume(request, "user-a", "tenant-a")
        output = b"".join([chunk async for chunk in response.body_iterator])
        assert response.status_code == 200
        assert output.decode() == (
            f"id: {run_id}:2\ndata: replay\n\n"
            f"id: {run_id}:3\ndata: live\n\n"
            f'id: {run_id}:4\nevent: agentos_terminal\ndata: {{"status": "completed"}}\n\n'
        )

        denied = await agentos.resume(request, "user-a", "tenant-b")
        assert denied.status_code == 404
        assert b"AGENTOS_RUN_NOT_FOUND" in b"".join([chunk async for chunk in denied.body_iterator])

    assert reads == ["1-0", "2-0"]



async def _assert_public_conversation_over_signed_http(monkeypatch):
    from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionRequestConflict
    from management.api.agent import conversation_run
    from management.services.agent import conversation_submission, prepared_turn, runtime_client
    from runtime.agentos import admission
    from runtime.api.agent import execution

    received = []
    executions = []
    run_id = "a" * 32
    claims = {}

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    def claim(scope, fingerprint, user_id, tenant_id):
        assert (user_id, tenant_id) == ("user-a", "tenant-a")
        if scope not in claims:
            claims[scope] = (fingerprint, "pending")
            return AdmissionClaim(run_id, "pending", None, False, True)
        expected, status = claims[scope]
        if fingerprint != expected:
            raise AdmissionRequestConflict
        return AdmissionClaim(run_id, status, 42, True, False)

    monkeypatch.setattr(conversation_submission, "_control_io", control_io)
    monkeypatch.setattr(prepared_turn, "find_pending_turn", lambda *_: asyncio.sleep(0, result=None))
    monkeypatch.setattr(prepared_turn, "start_turn", lambda *_: asyncio.sleep(0, result=None))
    monkeypatch.setattr(conversation_submission, "claim_conversation_run", claim)
    monkeypatch.setattr(
        conversation_submission, "conversation_belongs_to",
        lambda conversation_id, *, user_id, tenant_id: (conversation_id, user_id, tenant_id) == (42, "user-a", "tenant-a"),
    )

    def authorize(scope, fingerprint, claimed_run_id, user_id, tenant_id):
        assert (claimed_run_id, user_id, tenant_id) == (run_id, "user-a", "tenant-a")
        if claims.get(scope) != (fingerprint, "pending"):
            return False
        claims[scope] = (fingerprint, "dispatching")
        return True

    monkeypatch.setattr(admission, "_control_io", control_io)
    monkeypatch.setattr(admission, "authorize_conversation_dispatch", authorize)

    async def run_conversation(payload, actor):
        received.append((payload, actor))
        return await execution.run_agentos_conversation(payload, actor)

    async def run_public(request, _context, actor, resume):
        assert actor == ServicePrincipal("user-a", "tenant-a")
        if not resume:
            assert request._projection_run_id == run_id
            scope = request._run_admission_scope
            claims[scope] = (claims[scope][0], "admitted")
            executions.append(run_id)

        async def body():
            yield _EVENTS

        return StreamingResponse(
            body(), media_type="text/event-stream",
            headers={"X-AgentOS-Run-ID": run_id, "conversation_id": "42"},
        )

    monkeypatch.setattr(execution, "_run_public_conversation", run_public)
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_compatibility_router(None, None, conversation_run=run_conversation))

    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    management = FastAPI(root_path="/api")
    management.include_router(conversation_run.router)
    with serve(runtime) as runtime_url, serve(management) as management_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        monkeypatch.setattr(runtime_client, "_agentos_client", lambda: agentos)
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            response = await client.post(
                f"{management_url}/api/agent/run?resume=true",
                json={"query": "question", "conversation_id": 42, "model_id": None},
                headers={"Cookie": "NEXT_LOCALE=en", "X-User-Timezone": "Asia/Shanghai"},
            )
            assert response.status_code == 200
            assert response.content == _EVENTS and response.headers["X-AgentOS-Run-ID"] == run_id
            payload, actor = received[0]
            assert actor == ServicePrincipal("user-a", "tenant-a")
            assert payload.request == {"query": "question", "conversation_id": 42, "model_id": None}
            assert (payload.resume, payload.language, payload.timezone) == (True, "en", "Asia/Shanghai")

            url = f"{management_url}/api/agent/run"
            headers = {"Idempotency-Key": "retry-1"}
            request_body = {"query": "question"}
            first = await client.post(url, json=request_body, headers=headers)
            retry = await client.post(url, json=request_body, headers=headers)
            changed = await client.post(url, json={"query": "changed"}, headers=headers)
            assert first.status_code == 200 and first.headers["X-AgentOS-Run-ID"] == run_id
            assert retry.status_code == 202 and retry.headers["X-AgentOS-Run-ID"] == run_id
            assert retry.json() == {"run_id": run_id, "status": "admitted", "conversation_id": 42, "journal_available": True}
            assert changed.status_code == 409 and changed.json()["detail"]["code"] == "AGENTOS_IDEMPOTENCY_CONFLICT"

        assert len(received) == 2
        submitted, actor = received[1]
        assert submitted.claimed_run_id == run_id
        replay = await agentos.run_conversation(submitted, actor.user_id, actor.tenant_id)
        assert replay.status_code == 409
        error = b"".join([chunk async for chunk in replay.body_iterator])
        assert b"AGENTOS_ADMISSION_NOT_PENDING" in error
    assert executions == [run_id]


async def _assert_run_lifecycle_over_signed_http(monkeypatch):
    from runtime.agentos import resume

    first = AgentRunReference(conversation_id=42, run_id="1" * 32)
    next_run = AgentRunReference(conversation_id=42, run_id="2" * 32)
    states = {first.run_id: ("2-0", "running"), next_run.run_id: ("0-1", "starting")}
    requested = set()

    class Journal:
        def __init__(self, tenant_id, user_id, conversation_id, run_id):
            assert (tenant_id, user_id, conversation_id) == ("tenant-a", "user-a", 42)
            self.run_id = run_id

        def run_state(self, request_stop=False):
            event, status = states[self.run_id]
            if request_stop and status in {"running", "starting"}:
                requested.add(self.run_id)
            return event, status, status in {"running", "starting"} and self.run_id in requested

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(resume, "_control_io", control_io)
    monkeypatch.setattr(resume, "read_execution", lambda *args, **kwargs: None)
    monkeypatch.setattr(resume, "RunJournal", Journal)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        resume, "conversation_belongs_to",
        lambda conversation_id, *, user_id, tenant_id: (conversation_id, user_id, tenant_id) == (42, "user-a", "tenant-a"),
    )
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(resume.create_run_lifecycle_router())

    with serve(runtime) as runtime_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        state = await agentos.inspect_run(first, "user-a", "tenant-a")
        assert (state.status, state.latest_event_id, state.cancellation_requested) == ("running", f"{first.run_id}:2", False)

        for actor in (("other-user", "tenant-a"), ("user-a", "other-tenant")):
            for command in (agentos.inspect_run, agentos.stop_run):
                with pytest.raises(RuntimeUpstreamError) as denied:
                    await command(first, *actor)
                assert denied.value.status_code == 404
        assert not requested

        stop = await agentos.stop_run(first, "user-a", "tenant-a")
        assert stop.status == "running" and stop.cancellation_requested
        assert await agentos.stop_run(first, "user-a", "tenant-a") == stop
        states[first.run_id] = ("3-0", "stopped")
        terminal = await agentos.stop_run(first, "user-a", "tenant-a")
        assert (terminal.status, terminal.latest_event_id, terminal.cancellation_requested) == (
            "stopped", f"{first.run_id}:3", False,
        )
        next_state = await agentos.inspect_run(next_run, "user-a", "tenant-a")
        assert next_state.status == "starting" and next_state.latest_event_id is None and not next_state.cancellation_requested
        assert requested == {first.run_id}


async def _assert_public_stop_and_background(monkeypatch):
    from management.api.agent import conversation_run
    from management.services.agent import runtime_client
    from runtime.agentos import resume
    from runtime.api.agent import execution

    run_id, blocked_id, automation_id = ("b" * 32, "c" * 32, "d" * 32)
    states = {run_id: "running"}
    stopped = []
    launches = []

    def require_owner(conversation_id, user_id, tenant_id):
        if (conversation_id, user_id, tenant_id) != (42, "user-a", "tenant-a"):
            raise PermissionError

    async def control_io(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    def read_execution(run_id, user_id, tenant_id, conversation_id, *, request_stop=False, prevent_start=False):
        require_owner(42 if conversation_id is None else conversation_id, user_id, tenant_id)
        if prevent_start and run_id not in states:
            states[run_id] = "stopped"
        if run_id not in states:
            return None
        if request_stop:
            stopped.append(run_id)
        return {
            "conversation_id": 42, "status": states[run_id], "resource_versions": {"agent_id": 3, "agent_version_no": 4},
            "assistant_message_id": 77 if states[run_id] == "completed" else None,
            "cancellation_requested": request_stop and states[run_id] == "running",
        }

    def active_execution(conversation_id, user_id, tenant_id):
        require_owner(conversation_id, user_id, tenant_id)
        return run_id

    async def stream(*, agent_request, user_id, tenant_id, skip_user_save, http_request):
        require_owner(agent_request.conversation_id, user_id, tenant_id)
        assert agent_request._track_execution and skip_user_save and not agent_request.enable_automation_tool
        assert agent_request._message_source == "AUTOMATION"
        launches.append(agent_request._projection_run_id)

        async def chunks():
            yield "data: done\n\n"
            states[agent_request._projection_run_id] = "completed"

        return StreamingResponse(chunks())

    monkeypatch.setattr(resume, "_control_io", control_io)
    monkeypatch.setattr(resume, "read_execution", read_execution)
    monkeypatch.setattr(resume, "active_execution", active_execution)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=False))
    monkeypatch.setattr(execution, "read_execution", read_execution)
    monkeypatch.setattr(execution, "run_blocking", control_io)
    monkeypatch.setattr(execution, "_require_owned_conversation", lambda cid, actor: require_owner(cid, actor.user_id, actor.tenant_id))
    monkeypatch.setattr(execution, "run_agent_stream", stream)
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda auth: ("user-a", auth or "tenant-a"))

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(resume.create_run_lifecycle_router())
    runtime.include_router(create_background_router(None, None, tracked_run=execution.run_agentos_tracked_background))
    management = FastAPI(root_path="/api")
    management.include_router(conversation_run.router)

    with serve(runtime) as runtime_url, serve(management) as management_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        monkeypatch.setattr(runtime_client, "_agentos_client", lambda: agentos)
        async with httpx.AsyncClient(trust_env=False) as browser:
            response = await browser.get(f"{management_url}/api/agent/stop/{run_id}", headers={"Authorization": "foreign"})
            assert response.status_code == 404 and not stopped
            for public_id in (run_id, "42"):
                response = await browser.get(f"{management_url}/api/agent/stop/{public_id}")
                assert response.status_code == 200 and response.json()["run_id"] == run_id
                assert response.json()["cancellation_requested"]

        fenced = await agentos.stop_run(
            AgentStop(run_id=blocked_id, conversation_id=42, prevent_start=True), "user-a", "tenant-a",
        )
        assert fenced.status == "stopped"
        request = {"conversation_id": 42, "query": "automation"}
        with pytest.raises(RuntimeUpstreamError) as blocked:
            await agentos.run_tracked_background(BackgroundRun(run_id=blocked_id, request=request), "user-a", "tenant-a")
        assert blocked.value.status_code == 409 and not launches

        result = await agentos.run_tracked_background(BackgroundRun(run_id=automation_id, request=request), "user-a", "tenant-a")
        assert (result.run_id, result.assistant_message_id) == (automation_id, 77)
        state = await agentos.inspect_run(AgentRunReference(conversation_id=42, run_id=automation_id), "user-a", "tenant-a")
        assert state.status == "completed" and state.resource_versions.agent_version_no == 4
    assert stopped == [run_id, run_id, blocked_id]
    assert launches == [automation_id]

async def _assert_runtime_legacy_ingress_and_lifecycle(monkeypatch):
    from gateway.downstream.identity import IDENTITY_HEADER, sign_identity
    from infrastructure.rdb import conversation_state
    from runtime import executions
    from runtime.api.agent import execution

    key = "synthetic-runtime-ingress-signing-key"
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    conversation_id = 66142
    identity = {"kind": "session", "user_id": "legacy-actor", "tenant_id": "tenant-a"}
    checks = []
    starts = []

    def owns(conversation, *, user_id, tenant_id):
        checks.append((conversation, user_id, tenant_id))
        return (conversation, user_id, tenant_id) == (conversation_id, "legacy-actor", "tenant-a")

    async def control_io(_task, callback, *args, **kwargs):
        return callback(*args)

    async def stream(**kwargs):
        starts.append((kwargs["user_id"], kwargs["tenant_id"]))

        async def events():
            yield _EVENTS

        return StreamingResponse(events(), media_type="text/event-stream")

    registry = executions.LocalExecutionRegistry()
    from threading import Event
    info = SimpleNamespace(stop_event=Event())
    registry.register_agent_run(conversation_id, info, "legacy-actor")
    monkeypatch.setattr(executions, "agent_run_manager", registry)
    monkeypatch.setattr(execution, "agent_run_manager", registry)
    monkeypatch.setattr(conversation_state, "conversation_belongs_to", owns)
    monkeypatch.setattr(execution, "run_blocking", control_io)
    monkeypatch.setattr(execution, "run_agent_stream", stream)
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(execution.agent_runtime_router)
    runtime.include_router(create_compatibility_router(execution.run_agentos_compatibility, execution.stop_agentos_compatibility))
    runtime.include_router(create_background_router(execution.run_agentos_background, execution.inspect_agentos_conversation))

    run_path = "/api/agent/run"
    stop_path = f"/api/agent/stop/{conversation_id}"

    def signed(method, path, actor=identity):
        return {IDENTITY_HEADER: sign_identity(actor, "runtime", method, path, b"")}

    try:
        with serve(runtime) as runtime_url:
            agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
            async with httpx.AsyncClient(base_url=runtime_url, trust_env=False) as client:
                response = await client.post(run_path, json={"query": "hello"}, headers={"Authorization": "Bearer raw"})
                assert response.status_code == 401 and starts == []
                wrong_kind = signed("POST", run_path, dict(identity, kind="api_key"))
                response = await client.post(run_path, json={"query": "hello"}, headers=wrong_kind)
                assert response.status_code == 401 and starts == []
                response = await client.post(run_path, json={"query": "hello"}, headers=signed("POST", run_path))
                assert response.status_code == 200 and response.content == _EVENTS
                response = await client.get(stop_path, headers=signed("GET", stop_path, dict(identity, tenant_id="tenant-b")))
                assert response.status_code == 404 and not info.stop_event.is_set()
            state = await agentos.inspect(conversation_id, "legacy-actor", "tenant-a")
            assert state.running
            with pytest.raises(RuntimeUpstreamError) as foreign:
                await agentos.stop(conversation_id, "legacy-actor", "tenant-b")
            assert foreign.value.status_code == 404 and not info.stop_event.is_set()
            result = await agentos.stop(conversation_id, "legacy-actor", "tenant-a")
            assert result["status"] == "success" and info.stop_event.is_set()
            assert starts == [("legacy-actor", "tenant-a")]
            assert checks == [
                (conversation_id, "legacy-actor", "tenant-b"),
                (conversation_id, "legacy-actor", "tenant-a"),
                (conversation_id, "legacy-actor", "tenant-b"),
                (conversation_id, "legacy-actor", "tenant-a"),
            ]
    finally:
        registry.unregister_agent_run(conversation_id, "legacy-actor", agent_run_info=info)


async def _assert_prepared_run_over_signed_http(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from pathlib import Path
    from unittest.mock import AsyncMock, Mock

    from contracts.agent import AgentRequest
    from contracts.conversation import MessageSource
    from contracts.errors.exceptions import RuntimeServiceUnavailableError
    from management.services.automation import runner as automation
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.rdb.agent_execution import ActiveExecutionError
    from infrastructure.redis.agent_events import START
    from management.api.agent import conversation_run
    from management.services.agent import agentos_events, prepared_projection, runtime_client
    from management.services.agent.preparation import evaluation_snapshot, run as compile_run
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool
    from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool
    from runtime.agentos import prepared_evaluation, prepared_run, resume

    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    actor = ServicePrincipal("user-a", "tenant-a")
    journal_events = []
    admissions = []
    calls = []
    finished = threading.Event()
    persisted = []
    uploaded = []

    def owns(conversation_id, *, user_id, tenant_id):
        return (conversation_id, user_id, tenant_id) == (reference.conversation_id, actor.user_id, actor.tenant_id)

    def begin(identity):
        if not owns(identity.conversation_id, user_id=identity.user_id, tenant_id=identity.tenant_id):
            raise PermissionError()
        if admissions:
            raise ActiveExecutionError()
        admissions.append(identity)

    class Journal:
        def __init__(self, tenant_id, user_id, conversation_id, run_id):
            assert owns(conversation_id, user_id=user_id, tenant_id=tenant_id)
            assert run_id == reference.run_id

        def start(self):
            journal_events.append((START, {"kind": "start"}))

        def append(self, index, data):
            journal_events.append((f"{index}-0", {"kind": "chunk", "data": data}))

        def repair_terminal(self, status):
            journal_events.append((f"{len(journal_events)}-0", {"kind": "terminal", "status": status}))
            finished.set()

        def replay(self, after_id):
            index = next(i for i, (event_id, _) in enumerate(journal_events) if event_id == after_id)
            return [journal_events[index]], journal_events[index + 1:], journal_events[-1:]

    async def control_io(_task, function, *args, lane=None, owner=None, **kwargs):
        return function(*args, **kwargs)

    model_record = {
        "model_id": 11, "tenant_id": actor.tenant_id, "model_type": "llm", "model_factory": "openai",
        "delete_flag": "N", "display_name": "test-model", "model_name": "test-model", "model_repo": None,
        "base_url": "http://provider.test/v1", "api_key": "synthetic-provider-secret",
        "update_time": "2026-11-10T00:00:00",
        "extra_params": {"enable_thinking": True, "__custom__": {"temperature": 0.1}},
    }

    async def read_models(tenant_id):
        assert tenant_id == actor.tenant_id
        return [create_model_config_from_record(model_record)]

    async def compile_agent(**kwargs):
        assert kwargs["portable_evaluation"] and kwargs["version_no"] == 3
        return AgentConfig(
            name="agent", description="", agent_id=7, version_no=3,
            model_name="test-model", prompt_templates={"system_prompt": "Answer"}, tools=[],
        )

    def read_conversation(conversation_id, *, user_id, tenant_id):
        if owns(conversation_id, user_id=user_id, tenant_id=tenant_id):
            return {"runtime_metadata": {"project": "demo"}, "runtime_metadata_version": 4}
        return None

    monkeypatch.setattr(evaluation_snapshot, "run_blocking", control_io)
    monkeypatch.setattr(evaluation_snapshot, "get_conversation", read_conversation)
    monkeypatch.setattr(evaluation_snapshot, "get_memory_switch", lambda _user: False)

    def read_history(conversation_id, boundary_id, user_id, tenant_id):
        assert (conversation_id, boundary_id, user_id, tenant_id) == (42, 23, actor.user_id, actor.tenant_id)
        return {
            "history_summary": {"unit_id": 51, "summary": {"markdown": "earlier"}, "covered_through_message_id": 20},
            "conversation_turns": [{"user_message": "previous query", "assistant_final_answer": "previous answer",
                                    "user_message_id": 21, "assistant_message_id": 22, "attachments": None}],
        }

    monkeypatch.setattr(evaluation_snapshot, "get_historical_context", read_history)
    monkeypatch.setattr(evaluation_snapshot, "get_model_records", lambda *_args: [model_record])
    monkeypatch.setattr(compile_run, "create_model_config_list", read_models)
    monkeypatch.setattr(compile_run, "query_current_version_no", lambda **kwargs: 3)
    monkeypatch.setattr(compile_run, "create_agent_config", compile_agent)
    monkeypatch.setattr(compile_run, "_ensure_agent_reasoning_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(compile_run, "search_agent_info_by_agent_id", lambda **kwargs: {})
    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", lambda *_args: model_record)
    monkeypatch.setattr(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    monkeypatch.setattr("management.db.agent.repository.search_agent_info_by_agent_id", lambda **_: {"model_ids": [11]})
    monkeypatch.setattr("management.services.model.run_controls.get_model_by_model_id", lambda *_: model_record)
    request = await evaluation_snapshot.prepare_conversation_snapshot(
        AgentRequest(
            query="question", conversation_id=42, agent_id=7, version_no=3, enable_automation_tool=False,
            generation_config={"temperature": 0.45},
        ),
        reference, actor.user_id, actor.tenant_id, language="en", current_user_message_id=23,
    )
    assert isinstance(request, PreparedAgentRun)
    assert request.resource.version_no == 3
    assert "synthetic-provider-secret" not in request.model_dump_json()

    async def hydrate(payload, signed_actor, materialize):
        assert payload == request and signed_actor == actor and materialize is prepared_run.prepare_run_snapshot
        return materialize(payload, signed_actor)

    async def runner(info, **_kwargs):
        assert info.runtime_metadata == {"project": "demo"} and info.runtime_metadata_version == 4
        assert info.model_config_list[0].api_key == "synthetic-provider-secret"
        assert info.model_config_list[0].temperature == 0.45
        assert info.model_config_list[0].explicit_sampling == ["temperature"]
        assert info.model_config_list[0].enable_thinking is True
        assert "temperature" not in info.model_config_list[0].extra_body
        assert [item.id for item in info.context_input.items][-2:] == ["history_summary:51", "conversation_turn:21:22"]
        calls.append("started")
        yield '{"type":"thought","content":"step"}'
        yield '{"type":"final_answer","content":"answer"}'

        assert info.workspace_run_id == reference.run_id
        workspace = Path(info.workspace_path)
        output = workspace / "outputs" / "report.txt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"report")
        published = []

        def save_file(path, key):
            uploaded.append((Path(path).read_bytes(), key))
            return True, "stored"

        agent = NexentAgent.__new__(NexentAgent)
        agent.workspace_path = str(workspace)
        agent.workspace_mapping = None
        uploader = UploadToS3Tool(
            workspace_path=str(workspace), user_id=actor.user_id, run_id=info.workspace_run_id,
            minio_client=SimpleNamespace(upload_file=save_file, default_bucket="bucket"),
        )
        agent.agent = SimpleNamespace(tools={"upload_to_s3": uploader})
        script = RunSkillScriptTool(
            observer=SimpleNamespace(add_message=lambda _agent, kind, content: published.append({
                "type": kind.value, "content": content,
            })),
            artifact_uploader=agent._upload_skill_artifacts, artifact_path_resolver=agent._resolve_skill_artifact_path,
        )
        script.skill_manager = Mock()
        script.skill_manager.load_skill.return_value = {"script_outputs": {"report.py": {"kind": "file"}}}
        script.skill_manager.run_skill_script.return_value = json.dumps({"status": "success", "artifacts": [{
            "kind": "file", "absolute_path": str(output), "file_name": "report.txt",
            "mime_type": "text/plain", "file_size_bytes": 6,
        }]})
        result = script.execute("skill", "report.py")
        assert "absolute_path" not in result and len(published) == 1
        yield json.dumps(published[0])
        yield json.dumps({"type": "history_summary", "content": json.dumps({
            "status": "accepted", "persist_status": "not_configured", "summary": {"markdown": "compact"},
            "covered_through_message_id": 22, "previous_summary_unit_id": 51,
        })})

    from runtime.executions import LocalExecutionRegistry
    registry = LocalExecutionRegistry()
    monkeypatch.setattr(prepared_run, "agent_run_manager", registry)
    monkeypatch.setattr(prepared_run, "release_prepared_run", lambda info, cid, uid, status:
                        registry.unregister_agent_run(cid, uid, status, info))
    monkeypatch.setattr(prepared_run, "begin_execution", begin)
    monkeypatch.setattr(prepared_run, "track_execution", lambda _identity: None)
    def mark_running(identity, versions):
        assert identity.run_id == reference.run_id
        assert versions["runtime_metadata_version"] == 4 and versions["agent_version_no"] == 3
        return True

    monkeypatch.setattr(prepared_run, "mark_running", mark_running)
    monkeypatch.setattr(prepared_run, "finish_execution", lambda _identity, status: status == "completed")
    monkeypatch.setattr(prepared_run, "stop_requested", lambda _identity: False)
    monkeypatch.setattr(prepared_run, "load_prepared_run", hydrate)
    monkeypatch.setattr(prepared_run, "agent_run", runner)
    monkeypatch.setattr(resume, "conversation_belongs_to", owns)
    for module in (prepared_run, resume):
        monkeypatch.setattr(module, "_control_io", control_io)
        monkeypatch.setattr(module, "runtime_state_service", SimpleNamespace(enabled=True))
        monkeypatch.setattr(module, "RunJournal", Journal)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(prepared_run.create_prepared_run_router())
    runtime.include_router(resume.create_run_lifecycle_router())

    with serve(runtime) as runtime_url:
        agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        with pytest.raises(RuntimeUpstreamError) as foreign:
            await agentos.start_prepared_run(request, actor.user_id, "tenant-b")
        assert foreign.value.status_code == 404 and not admissions
        async with httpx.AsyncClient(base_url=runtime_url, trust_env=False) as raw:
            unauthorized = await raw.post(f"/api{AgentOperation.RUN.value}", json=request.model_dump(mode="json"))
            assert unauthorized.status_code == 401
        stored_run = {
            "run_id": 51, "runtime_run_id": reference.run_id, "status": "RUNNING",
            "task_id": 1, "trigger_type": "MANUAL", "conversation_id": 42,
            "user_id": actor.user_id, "tenant_id": actor.tenant_id,
            "started_at": datetime.now(timezone.utc),
        }
        task = {**stored_run, "status": "ACTIVE", "agent_id": 7, "instruction": "question"}
        def record(run_id, values, user_id, *, expected_statuses):
            assert (run_id, user_id, expected_statuses) == (51, actor.user_id, ["RUNNING"])
            stored_run.update(values)
            return stored_run.copy()

        real_start = agentos.start_prepared_run
        async def start_then_drop_ack(payload, user_id, tenant_id):
            assert stored_run["projection_message_index"] == 1 and stored_run["user_message_id"] == 23
            assert await real_start(payload, user_id, tenant_id) == reference
            raise RuntimeServiceUnavailableError("Synthetic dropped acknowledgement")

        monkeypatch.setattr(agentos, "start_prepared_run", start_then_drop_ack)
        monkeypatch.setattr(automation, "_agentos_client", lambda: agentos)
        monkeypatch.setattr(automation, "prepare_conversation_snapshot", AsyncMock(return_value=request))
        monkeypatch.setattr(automation, "validate_bindings_available", AsyncMock(return_value={"available": True}))
        monkeypatch.setattr(automation.automation_conversation_adapter, "append_run_prompt",
                            lambda *_: {"user_message_id": 23, "history": [], "assistant_message_index": 1})
        monkeypatch.setattr(automation.agent_automation_db, "update_run", record)
        submission = await automation.AgentAutomationRunner()._execute_active_run(stored_run.copy(), task)
        assert submission["status"] == "RUNNING" and stored_run["projection_message_index"] == 1
        assert await asyncio.to_thread(finished.wait, 5)
        monkeypatch.setattr(agentos, "start_prepared_run", real_start)
        with pytest.raises(RuntimeUpstreamError) as duplicate:
            await agentos.start_prepared_run(request, actor.user_id, actor.tenant_id)
        assert duplicate.value.status_code == 409

        cursor = AgentResume(**reference.model_dump(), after_event_id=f"{reference.run_id}:1")
        replay = await agentos.resume(cursor, actor.user_id, actor.tenant_id)
        body = b"".join([chunk async for chunk in replay.body_iterator]).decode()
        assert body.startswith(
            f"id: {reference.run_id}:2\nevent: agentos_observer\n"
            'data: {"type":"final_answer","content":"answer"}\n\n'
        )
        assert body.endswith(f'id: {reference.run_id}:5\nevent: agentos_terminal\ndata: {{"status": "completed"}}\n\n')
        assert "absolute_path" not in body and '"type":"file_artifact"' in body

        def sign_outputs(artifacts):
            assert [item["object_name"] for item in artifacts] == [
                f"workspace/{actor.user_id}/{reference.run_id}/outputs/report.txt",
            ]
            return [{**artifacts[0], "presigned_url": "https://synthetic.test/ready"}]

        monkeypatch.setattr(runtime_client, "_agentos_client", lambda: agentos)
        monkeypatch.setattr(agentos_events, "enrich_file_uploads_with_presigned_urls", sign_outputs)
        monkeypatch.setattr(agentos_events, "run_blocking", control_io)
        monkeypatch.setattr(conversation_run, "get_current_user_id", lambda token: (actor.user_id, token))
        management = FastAPI()
        management.include_router(conversation_run.router)
        params = {"resume": "true", "run_id": reference.run_id, "after_event_id": cursor.after_event_id}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=management),
                                     base_url="http://management") as browser:
            public = await browser.post("/agent/run", params=params, json={"query": "", "conversation_id": 42},
                                        headers={"Authorization": actor.tenant_id})
            foreign_public = await browser.post(
                "/agent/run", params=params, json={"query": "", "conversation_id": 42},
                headers={"Authorization": "tenant-b"},
            )
        assert public.status_code == 200 and public.headers["X-AgentOS-Run-ID"] == reference.run_id
        assert public.text.startswith(
            f'id: {reference.run_id}:2\ndata: {{"type":"final_answer","content":"answer"}}\n\n'
        )
        assert f"id: {reference.run_id}:3\ndata: " in public.text
        assert '"type":"files"' in public.text and "https://synthetic.test/ready" in public.text
        assert all(label not in public.text for label in ("agentos_observer", "file_artifact", "absolute_path"))
        assert public.text.endswith(f'id: {reference.run_id}:5\nevent: agentos_terminal\ndata: {{"status": "completed"}}\n\n')
        assert foreign_public.status_code == 404 and foreign_public.json()["detail"]["code"] == "AGENTOS_RUN_NOT_FOUND"

        def persist(**fields):
            persisted.append(fields)
            return 77

        monkeypatch.setattr(prepared_projection, "run_blocking", control_io)
        monkeypatch.setattr(prepared_projection, "persist_prepared_assistant_projection", persist)
        def finalize(pending, run_values, task_values):
            assert pending["runtime_run_id"] == reference.run_id
            assert task_values["last_run_status"] == "SUCCEEDED"
            stored_run.update(run_values)
            return stored_run.copy()

        monkeypatch.setattr(automation, "run_blocking", control_io)
        monkeypatch.setattr(automation, "get_prepared_projection_receipt", lambda **_: None)
        monkeypatch.setattr(automation.agent_automation_db, "get_task", lambda *_: task)
        monkeypatch.setattr(automation.agent_automation_db, "finish_prepared_run", finalize)
        monkeypatch.setattr(resume, "read_execution", lambda run_id, user, tenant, cid, **_: {
            "conversation_id": cid, "status": "completed", "cancellation_requested": False,
        } if (run_id, user, tenant, cid) == (reference.run_id, actor.user_id, actor.tenant_id, 42) else None)
        monkeypatch.setattr(Journal, "run_state", lambda self: (journal_events[-1][0], "completed", False), raising=False)
        await automation.AgentAutomationRunner().recover_prepared_run(stored_run.copy())
        assert stored_run["assistant_message_id"] == 77 and stored_run["status"] == "SUCCEEDED"
        assert stored_run["projection_message_index"] is None
        assert len(persisted) == 1
        assert persisted[0]["message_source"] is MessageSource.AUTOMATION
        batch = persisted[0]
        assert (batch["projection_run_id"], batch["conversation_id"]) == (reference.run_id, 42)
        assert batch["message_content"] == "answer"
        assert batch["history_checkpoints"] == [{
            "summary": {"markdown": "compact"}, "covered_through_message_id": 22, "previous_summary_unit_id": 51,
        }]
        key = f"workspace/{actor.user_id}/{reference.run_id}/outputs/report.txt"
        assert uploaded == [(b"report", key)]
        assert batch["skill_files"] == [{
            "object_name": key, "name": "report.txt", "type": "file",
            "size": 6, "url": f"s3://bucket/{key}", "description": "",
        }]
        assert [(unit["unit_index"], unit["unit_content"]) for unit in batch["message_units"]] == [
            (0, "step"), (1, "answer"),
        ]

        denied = await agentos.resume(cursor, "user-b", actor.tenant_id)
        assert denied.status_code == 404
        assert b"AGENTOS_RUN_NOT_FOUND" in b"".join([chunk async for chunk in denied.body_iterator])

    assert len(admissions) == 1 and calls == ["started"]
    assert registry.get_agent_run_info(reference.conversation_id, actor.user_id) is None


async def _assert_prepared_planning_over_signed_http(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from infrastructure.agent_model_config import model_record_revision
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.agents.plan_repo import PlanRepo
    from runtime.agentos import prepared_run

    principal = ServicePrincipal("planning-user", "planning-tenant")
    reference = AgentRunReference(conversation_id=47, run_id="a" * 32)
    model = {
        "model_id": 11, "tenant_id": principal.tenant_id, "model_type": "llm", "model_factory": "openai",
        "delete_flag": "N", "display_name": "demo", "model_name": "demo", "model_repo": None,
        "base_url": "http://provider.invalid/v1", "api_key": "synthetic", "update_time": "2026-11-10T00:00:00",
    }
    payload = PreparedAgentRun.model_validate({
        **reference.model_dump(), "mode": "nexent", "input": {"query": "plan a test"}, "language": "en",
        "resource": {
            "agent_id": 7, "version_no": 3, "name": "planning_agent", "description": "planning",
            "prompt_templates": {"system_prompt": "Plan before acting"},
            "tools": [{"tool_id": name, "version": "1"} for name in ("create_plan", "update_plan_step")],
        },
        "models": {"llm": {"model_id": 11, "alias": "demo", "revision": model_record_revision(model)}},
    })
    redis = Mock()
    events = Mock()

    class State:
        current_plan = None

        def created(self, plan):
            self.current_plan = plan

        def updated(self, plan, _step_id, _status):
            self.current_plan = plan

    async def execute(signed, actor):
        assert signed == payload and actor == principal
        info = prepared_evaluation.prepare_run_snapshot(signed, actor)
        assert info.redis_client is redis and info.agent_config.enable_planning
        executor = SimpleNamespace(observer=info.observer)
        create, update = [NexentAgent.create_local_tool(executor, tool) for tool in info.agent_config.tools]
        state = State()
        repo = PlanRepo(redis_client=info.redis_client)
        for tool in (create, update):
            tool.plan_repo = repo
            tool.observer = events
            tool._get_conversation_id = lambda: info.conversation_id
            tool._get_user_id = lambda: info.user_id
        create._on_plan_created = state.created
        update._on_step_updated = state.updated
        result = create.forward("Test", [{"id": str(i), "title": str(i)} for i in range(3)])
        assert result["step_count"] == 3
        assert update.forward("0", "completed")["status"] == "completed"
        return reference

    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", lambda *_: model)
    monkeypatch.setattr(prepared_evaluation, "get_redis_client", lambda: redis)
    monkeypatch.setattr(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(environment, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    monkeypatch.setattr(prepared_run, "start_prepared_run", execute)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(prepared_run.create_prepared_run_router())
    with serve(runtime) as runtime_url:
        client = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        assert await client.start_prepared_run(payload, principal.user_id, principal.tenant_id) == reference

    assert [call.args[0] for call in redis.setex.call_args_list] == ["plan:47:planning-user"] * 2
    assert json.loads(redis.setex.call_args.args[2])["steps"][0]["status"] == "completed"
    assert [call.args[1].value for call in events.add_message.call_args_list] == ["plan", "plan_step_update"]


async def _assert_public_prepared_turn_over_signed_http(
    monkeypatch, *, new_conversation=False, northbound=False, metadata=None, use_workbench=False,
    use_knowledge_scope=False, clarification=False,
):
    from contracts.agent import WorkbenchSessionConfig
    from contracts.clarification import ClarificationResponse
    from contracts.constants.constants import DEFAULT_EN_TITLE
    from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionScopeError
    from infrastructure.redis.agent_events import START
    from management.api.agent import conversation_run
    from management.services.agent import conversation_submission, prepared_projection, prepared_turn, runtime_client
    from runtime.agentos import prepared_run, resume

    boundary = 0 if new_conversation else 4
    actor = ServicePrincipal("public-user", "public-tenant")
    reference = AgentRunReference(conversation_id=55, run_id="b" * 32)
    knowledge_scope = {
        "local": {"mode": "override", "knowledge_ids": ["7", "8"]},
        "aidp": {"mode": "disabled"},
    } if use_knowledge_scope else None
    config = WorkbenchSessionConfig(
        mode="generic_chat", generation_config={"temperature": 0.4}, knowledge_scope=knowledge_scope,
    )
    bindings = [{"tool_id": "create_scheduled_task_proposal", "version": "1"}]
    if use_knowledge_scope:
        bindings.append({
            "tool_id": "knowledge_base_search", "version": "1", "parameters": {
                "description": {}, "index_names": ["kb-one"],
                "allowed": [{"knowledge_id": 7, "index_name": "kb-one", "revision": "a" * 64}],
                "display_name_to_index": {"One": "kb-one"}, "document_paths": ["report.txt"],
                "embedding": {"model_id": 12, "revision": "embedding-revision"},
            },
        })
    llm = {"model_id": 11, "alias": "demo", "revision": "revision"}
    if use_workbench:
        llm["root_generation"] = config.generation_config.model_dump(mode="json")
    snapshot = PreparedAgentRun.model_validate({
        **reference.model_dump(), "mode": "nexent", "input": {"query": "test"}, "language": "en",
        **({"runtime_metadata": metadata, "runtime_metadata_version": 6} if metadata is not None else {}),
        **({"workbench_config_version": 4} if use_workbench else {}),
        "resource": {"agent_id": 7, "version_no": 2, "name": "agent", "description": "example",
                     "prompt_templates": {"system_prompt": "Answer"},
                     "tools": bindings},
        "models": {"llm": llm},
    })
    response = ClarificationResponse.model_validate({
        "form": {"schema_version": 1, "questions": [{"id": "goal", "type": "text", "title": "Goal?"}]},
        "answers": [{"questionId": "goal", "value": "Continue"}],
    }) if clarification else None
    state = {"status": "pending"}
    calls = []
    pending = SimpleNamespace(reference=reference, user_id=actor.user_id, tenant_id=actor.tenant_id,
                              message_index=boundary + 1, assistant_message_id=None)
    confirmed = SimpleNamespace(**{**vars(pending), "assistant_message_id": 81})

    def claim(_scope, _fingerprint, user_id, tenant_id):
        if (user_id, tenant_id) != (actor.user_id, actor.tenant_id):
            raise AdmissionScopeError
        if state.get("claimed"):
            return AdmissionClaim(reference.run_id, state["status"], 55, True, False)
        state["claimed"] = True
        return AdmissionClaim(reference.run_id, "pending", None, False, True)

    def stage(_scope, ref, user_id, tenant_id, index, turn, *, initial_title=None):
        assert (ref, user_id, tenant_id, index) == (reference, actor.user_id, actor.tenant_id, boundary)
        assert initial_title == (DEFAULT_EN_TITLE if new_conversation else None)
        assert turn["query"] == "test"
        assert turn.get("clarification_response") == (response.model_dump(mode="json") if response else None)
        if use_workbench:
            assert turn["workbench_update"] == {
                "config": config.model_dump(mode="json"), "expected_version": 3, "version": 4,
            }
        if metadata is not None:
            assert turn["metadata_update"] == {"expected_version": 5, "value": metadata}
        if northbound:
            assert turn["automation"] is None
        else:
            automation_params = None
            if use_knowledge_scope:
                automation_params = turn["automation"]["tool_params"]
                assert automation_params["agents"]["root"]["tools"]["knowledge_base_search"] == {
                    "index_names": ["kb-one"], "document_paths": ["report.txt"],
                }
            assert turn["automation"] == {
                "agent_id": 7, "agent_version_no": 2, "model_id": None, "tool_params": automation_params,
                "has_attachments": False,
            }
        calls.append("stage")
        return pending

    def confirm(turn):
        assert turn is pending and calls == ["stage", "start"]
        calls.append("confirm")
        state["status"] = "admitted"
        return confirmed

    def persist(**fields):
        assert calls == ["stage", "start", "confirm"]
        assert fields["assistant_message_id"] == 81 and fields["projection_run_id"] == reference.run_id
        assert fields["message_content"] == "answer"
        calls.append("project")
        return 81

    def close(turn):
        assert turn is confirmed and calls[-1] == "project"
        calls.append("close")

    async def start(payload, signed_actor):
        assert payload == snapshot and signed_actor == actor and calls == ["stage"]
        assert "clarification_response" not in payload.model_dump_json()
        calls.append("start")
        return reference

    async def inline(_label, function, *args, lane=None, owner=None, **kwargs):
        return function(*args, **kwargs)

    def owned(cid, *, user_id, tenant_id):
        return (cid, user_id, tenant_id) == (reference.conversation_id, actor.user_id, actor.tenant_id)

    class Journal:
        def __init__(self, tenant_id, user_id, cid, run_id):
            assert owned(cid, user_id=user_id, tenant_id=tenant_id) and run_id == reference.run_id
            assert "confirm" in calls

        def replay(self, anchor):
            assert anchor == START
            terminal = ("2-0", {"kind": "terminal", "status": "completed"})
            return [(START, {"kind": "start"})], [
                ("1-0", {"kind": "chunk",
                         "data": 'event: agentos_observer\ndata: {"type":"final_answer","content":"answer"}\n\n'}),
                terminal,
            ], [terminal]

    monkeypatch.setattr(conversation_submission, "_control_io", inline)
    monkeypatch.setattr(conversation_submission, "claim_conversation_run", claim)
    monkeypatch.setattr(conversation_submission, "conversation_belongs_to", owned)
    monkeypatch.setattr(prepared_turn, "run_blocking", inline)
    if use_workbench:
        from management.services.agent import workbench

        monkeypatch.setattr(prepared_turn, "get_conversation", lambda *_args, **_kwargs: {
            "workbench_config": WorkbenchSessionConfig(mode="generic_chat").model_dump(mode="json"),
            "workbench_config_version": 3,
            "runtime_metadata_version": 5,
        })
        identity = SimpleNamespace(agent_id=7, version_no=2)
        monkeypatch.setattr(workbench, "resolve_workbench_config", lambda requested, **_kwargs: (
            requested, SimpleNamespace(root_skills=(), root=SimpleNamespace(identity=identity)),
        ))
        if use_knowledge_scope:
            from management.services.knowledge_base import mount, scope

            tool = {"class_name": "KnowledgeBaseSearchTool", "name": "knowledge_base_search", "params": []}
            monkeypatch.setattr(mount, "ENABLE_AIDP_KNOWLEDGE", False)
            monkeypatch.setattr(scope, "snapshot_runtime_knowledge_tree",
                                lambda *_: [{"agent_name": "root", "tools": [tool]}])
            monkeypatch.setattr(scope, "get_knowledge_info_by_ids_and_tenant", lambda *_: [
                {"knowledge_id": 7, "index_name": "kb-one", "knowledge_name": "One", "embedding_model_id": 12},
                {"knowledge_id": 8, "index_name": "kb-denied", "knowledge_name": "Denied", "embedding_model_id": 12},
            ])
            monkeypatch.setattr(scope.ElasticSearchService, "filter_accessible_indices", lambda *_, **__: ["kb-one"])

    async def compile_snapshot(request, ref, user_id, tenant_id, **kwargs):
        assert request.conversation_id == reference.conversation_id and ref == reference
        assert (user_id, tenant_id) == (actor.user_id, actor.tenant_id)
        if new_conversation:
            assert kwargs["new_conversation"] is True and "before_message_index" not in kwargs
        assert request.metadata == metadata
        assert request.clarification_response == response
        assert kwargs.get("allow_metadata_update", False) == (metadata is not None and northbound)
        if use_workbench:
            assert kwargs["workbench"].config == config and kwargs["workbench"].version == 4
        if use_knowledge_scope:
            assert kwargs["workbench"].knowledge.local_index_names == ["kb-one"]
        return snapshot

    monkeypatch.setattr(prepared_turn, "prepare_conversation_snapshot", compile_snapshot)
    monkeypatch.setattr(prepared_turn.store, "allocate_conversation_id", lambda: reference.conversation_id)
    monkeypatch.setattr(prepared_turn.store, "next_message_index", lambda *_: 4)
    monkeypatch.setattr(prepared_turn.store, "stage_turn", stage)
    monkeypatch.setattr(prepared_turn.store, "confirm_turn", confirm)
    monkeypatch.setattr(prepared_turn.store, "close_turn", close)
    monkeypatch.setattr(prepared_turn, "get_prepared_projection_receipt", lambda **_: None)
    monkeypatch.setattr(prepared_projection, "run_blocking", inline)
    monkeypatch.setattr(prepared_projection, "persist_prepared_assistant_projection", persist)
    monkeypatch.setattr(prepared_run, "start_prepared_run", start)
    monkeypatch.setattr(resume, "_control_io", inline)
    monkeypatch.setattr(resume, "conversation_belongs_to", owned)
    monkeypatch.setattr(resume, "active_execution", lambda *_: None)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=True))
    monkeypatch.setattr(resume, "RunJournal", Journal)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(prepared_run.create_prepared_run_router())
    runtime.include_router(resume.create_run_lifecycle_router())
    management = FastAPI()
    management.include_router(conversation_run.router)
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda token: (actor.user_id, token))
    with serve(runtime) as runtime_url:
        monkeypatch.setattr(runtime_client, "_agentos_client",
                            lambda: AgentOSClient(runtime_url, lambda **kw: httpx.AsyncClient(trust_env=False, **kw)))
        if northbound:
            await _assert_northbound_prepared_turn(management, monkeypatch, reference, actor, metadata)
            assert calls == ["stage", "start", "confirm", "project", "close"]
            return

        request = {"query": "test", "agent_id": 7}
        if use_workbench:
            request = {
                "query": "test", "entrypoint": "workbench", "workbench": config.model_dump(mode="json"),
                "expected_workbench_config_version": 3,
            }
        if use_workbench and metadata is not None:
            request.update(metadata=metadata, expected_metadata_version=5)
        if use_knowledge_scope:
            request.update(knowledge_scope=knowledge_scope, tool_params={
                "agents": {"root": {"tools": {"knowledge_base_search": {"document_paths": ["report.txt"]}}}},
            })
        if not new_conversation:
            request["conversation_id"] = reference.conversation_id
        if response is not None:
            request["clarification_response"] = response.model_dump(mode="json")
        headers = {"Authorization": actor.tenant_id, "Idempotency-Key": "turn-1", "Cookie": "NEXT_LOCALE=en"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=management),
                                     base_url="http://management") as browser:
            first = await browser.post("/agent/run", json=request, headers=headers)
            retry = await browser.post("/agent/run", json=request, headers=headers)
            denied = await browser.post("/agent/run", json=request, headers={**headers, "Authorization": "foreign"})
        assert first.status_code == 200 and first.headers["run_id"] == reference.run_id
        assert first.headers["conversation_id"] == str(reference.conversation_id)
        prefix = f'id: {reference.run_id}:1\ndata: {{"type":"final_answer","content":"answer"}}\n\n'
        if new_conversation:
            created = {"type": "conversation_created", "content": {"conversation_id": reference.conversation_id}}
            prefix = f"data: {json.dumps(created, separators=(',', ':'))}\n\n" + prefix
        if use_knowledge_scope:
            scope_event = {"type": "knowledge_scope_resolved", "content": {
                "effective": {
                    "local": {"disabled": False, "knowledge_ids": ["7"], "display_names": ["One"]},
                    "aidp": {"disabled": True, "kds_ids": [], "display_names": []},
                },
                "warnings": [{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE", "source": "local", "count": 1}],
            }}
            prefix = f"data: {json.dumps(scope_event, separators=(',', ':'))}\n\n" + prefix
        if use_workbench:
            event = {"type": "workbench_config_resolved", "content": {
                "config_version": 4, "schema_version": 3, "mode": "generic_chat", "agent_mounts": [],
            }}
            prefix = f"data: {json.dumps(event, separators=(',', ':'))}\n\n" + prefix
            assert first.headers["X-Workbench-Config-Version"] == "4"
            if metadata is not None:
                assert first.headers["X-Runtime-Metadata-Version"] == "6"
        assert first.text.startswith(prefix)
        assert "agentos_terminal" in first.text
        assert retry.status_code == 202 and retry.json()["run_id"] == reference.run_id
        assert retry.json()["conversation_id"] == reference.conversation_id
        assert denied.status_code == 404
    assert calls == ["stage", "start", "confirm", "project", "close"]


async def _assert_northbound_prepared_turn(management, monkeypatch, reference, actor, metadata):
    from unittest.mock import AsyncMock, Mock

    from contracts.authentication import NorthboundContext
    from management.api import northbound as northbound_api
    from management.services import northbound as northbound_service
    from management.services.agent import prepared_turn
    from runtime.agentos import resume

    async def authenticate(request):
        return NorthboundContext(
            "northbound-request", request.headers["authorization"],
            request.headers.get("X-Test-Actor", actor.user_id), "", token_id=4,
        )

    def visible(conversation_id, user_id, tenant_id):
        if (conversation_id, user_id, tenant_id) == (reference.conversation_id, actor.user_id, actor.tenant_id):
            return {"conversation_id": conversation_id}
        return None

    management.include_router(northbound_api.router)
    monkeypatch.setattr(northbound_api, "_get_northbound_context", authenticate)
    monkeypatch.setattr(northbound_service, "get_agent_by_name_impl", lambda **_: {"agent_id": 7, "latest_version_no": 2})
    monkeypatch.setattr(northbound_service, "create_new_conversation",
                        Mock(return_value={"conversation_id": reference.conversation_id}))
    monkeypatch.setattr(northbound_service, "get_conversation_service", visible)
    monkeypatch.setattr(northbound_service, "get_conversation_history_internal",
                        AsyncMock(return_value={"data": {"history": []}}))
    monkeypatch.setattr(northbound_service, "check_and_consume_rate_limit", AsyncMock())
    claim_external = AsyncMock()
    monkeypatch.setattr(northbound_service, "idempotency_start", claim_external)
    monkeypatch.setattr(northbound_service, "_release_idempotency_after_delay", AsyncMock())
    legacy_write = Mock()
    legacy_dispatch = AsyncMock()
    log_usage = Mock()
    monkeypatch.setattr(northbound_service, "save_conversation_user", legacy_write)
    monkeypatch.setattr(northbound_service, "forward_agent_run", legacy_dispatch)
    monkeypatch.setattr(northbound_service, "log_token_usage", log_usage)

    stopped_id = "c" * 32
    pending = SimpleNamespace(reference=reference.model_copy(update={"run_id": stopped_id}))
    cancel = Mock(return_value={
        "conversation_id": reference.conversation_id, "status": "stopped", "cancellation_requested": True,
    })

    body = {"query": "test", "agent_name": "test-agent", "metadata": metadata}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=management), base_url="http://management") as caller:
        response = await caller.post("/nb/v1/chat/run", json=body,
                                     headers={"Authorization": actor.tenant_id, "Idempotency-Key": "external-key"})
        followup = {**body, "conversation_id": reference.conversation_id}
        foreign_tenant = await caller.post("/nb/v1/chat/run", json=followup, headers={"Authorization": "foreign"})
        foreign_user = await caller.post("/nb/v1/chat/run", json=followup,
                                         headers={"Authorization": actor.tenant_id, "X-Test-Actor": "foreign"})
        monkeypatch.setattr(prepared_turn.store, "pending_turn", lambda *scope: pending if scope == (
            reference.conversation_id, actor.user_id, actor.tenant_id,
        ) else None)
        monkeypatch.setattr(resume, "read_execution", cancel)
        monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=False))
        stop = await caller.get(f"/nb/v1/chat/stop/{reference.conversation_id}",
                                headers={"Authorization": actor.tenant_id})
    assert response.status_code == 200
    assert foreign_tenant.status_code == foreign_user.status_code == 403
    assert response.headers["X-Request-Id"] == "northbound-request"
    assert response.headers["conversation_id"] == str(reference.conversation_id)
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "X-AgentOS-Run-ID" not in response.headers and "run_id" not in response.headers
    if metadata is not None:
        assert response.headers["X-Runtime-Metadata-Version"] == "6"
    created = {"type": "conversation_created", "content": {"conversation_id": reference.conversation_id}}
    assert response.text == (
        f"data: {json.dumps(created)}\n\n"
        'data: {"type":"final_answer","content":"answer"}\n\n'
    )
    claim_external.assert_awaited_once_with("external-key")
    legacy_write.assert_not_called()
    legacy_dispatch.assert_not_awaited()
    assert stop.status_code == 200 and stop.json() == {
        "message": f"successfully stopped agent run for user_id {actor.user_id}, run_id {reference.conversation_id}",
        "data": reference.conversation_id, "requestId": "northbound-request",
    }
    cancel.assert_called_once_with(
        stopped_id, actor.user_id, actor.tenant_id, reference.conversation_id, request_stop=True, prevent_start=True,
    )
    assert [call.kwargs["call_function_name"] for call in log_usage.call_args_list] == ["run_chat", "stop_chat_stream"]
    assert all(call.kwargs["related_id"] == reference.conversation_id for call in log_usage.call_args_list)


async def _assert_signed_ephemeral_stream(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from queue import Empty, SimpleQueue
    from threading import Event
    from unittest.mock import AsyncMock, Mock

    from contracts.agent import AgentRequest
    from contracts.agentos import PreparedEphemeralRun
    from management.api.agent import conversation_run
    from management.services.agent import agentos_events, runtime_client
    from management.services.agent.preparation import evaluation_snapshot
    from nexent.core.agents import run_agent as sdk_runner
    from nexent.core.concurrency import LanePolicy, ThreadManager
    from nexent.monitor import get_agent_monitoring_context
    from runtime.agentos import debug as debug_lifecycle, ephemeral
    from runtime.agentos.compatibility import create_compatibility_router
    from runtime.agentos.prepared_skills import skill_stage_path
    from runtime.executions import LocalExecutionRegistry

    actor = ServicePrincipal("ephemeral-user", "ephemeral-tenant")
    run_id = "d" * 32
    template = PreparedEphemeralRun.model_validate({
        "run_id": run_id, "mode": "nexent", "input": {"query": "finish"}, "runtime_metadata": {"ticket": "42"},
        "resource": {"agent_id": 7, "version_no": 3, "name": "agent", "description": "", "prompt_templates": {}},
        "models": {"llm": {"model_id": 11, "alias": "demo", "revision": "revision"}},
    })
    object_name = f"workspace/{actor.user_id}/{run_id}/outputs/report.txt"
    calls = []
    executions = []
    released = Mock()
    stages = []
    worker_stopped = Event()
    debug_registry = LocalExecutionRegistry()
    debug_states = {}
    cancel_signals = set()

    def register_debug(run, info, owner):
        debug_registry.register_agent_run(run, info, owner)
        debug_states[owner, run] = {"status": "running"}

    def unregister_debug(run, owner, status, agent_run_info):
        removed = debug_registry.unregister_agent_run(run, owner, status, agent_run_info)
        if removed:
            debug_states.pop((owner, run))
        return removed

    def publish_debug_stop(run, owner):
        cancel_signals.add((owner, run))
        return True

    async def is_debug_cancelled(owner, run):
        return (owner, run) in cancel_signals

    class Observer:
        def __init__(self):
            self.queue = SimpleQueue()

        def get_cached_message(self):
            events = []
            while True:
                try:
                    events.append(self.queue.get_nowait())
                except Empty:
                    return events

    async def compile_snapshot(request, user_id, tenant_id):
        assert (user_id, tenant_id) == (actor.user_id, actor.tenant_id)
        assert request.conversation_id is None and request.version_no == 3 and request.is_debug
        return template.model_copy(update={"input": template.input.model_copy(update={"query": request.query})})

    async def load(payload, principal, materializer):
        assert principal == actor and materializer is ephemeral.prepare_run_snapshot
        assert payload.runtime_metadata == {"ticket": "42"} and "conversation_id" not in payload.model_dump()
        calls.append(payload.input.query)
        workspace = tmp_path / "ephemeral" / f"{run_id}-{payload.input.query}"
        stage = skill_stage_path(str(workspace), create=True)
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "SKILL.md").write_text("test", encoding="utf-8")
        stages.append(stage)
        return SimpleNamespace(
            query=payload.input.query, workspace_path=str(workspace), workspace_run_id=run_id, conversation_id=None,
            runtime_metadata=payload.runtime_metadata, observer=Observer(), stop_event=Event(), cancellation_scope=None,
            attempt_outcome=None,
        )

    manager = ThreadManager(
        service_name="ephemeral-test",
        lane_policies={"agent-run": LanePolicy(
            name="agent-run", max_workers=1, max_queue_size=0, queue_timeout_seconds=2,
        )},
    )
    original_submit = manager.submit

    def submit(lane, spec, function):
        assert lane == "agent-run" and spec.run_id == run_id
        execution = original_submit(lane, spec, function)
        executions.append(execution)
        return execution

    def worker(info):
        context = get_agent_monitoring_context()
        assert (context.user_id, context.tenant_id, context.agent_id) == (actor.user_id, actor.tenant_id, 7)
        assert context.conversation_id is None
        info.observer.queue.put(json.dumps({"type": "final_answer", "content": "answer"}))
        if info.query == "wait":
            if info.stop_event.wait(5):
                worker_stopped.set()
            return
        info.observer.queue.put(json.dumps({"type": "file_artifact", "content": {"artifacts": [
            {"object_name": object_name, "name": "report.txt"},
            {"object_name": f"workspace/other/{run_id}/outputs/private.txt"},
        ]}}))

    reserve = Mock(return_value="capacity")
    monkeypatch.setattr(ephemeral, "agent_run_manager", SimpleNamespace(
        reserve_agent_capacity=reserve, release_agent_capacity=released,
        register_agent_run=register_debug, unregister_agent_run=unregister_debug,
        get_agent_run_info=lambda *_: None, stop_agent_run=publish_debug_stop,
        stop_local_run=debug_registry.stop_local_run,
    ))
    monkeypatch.setattr(ephemeral, "runtime_state_service", SimpleNamespace(
        enabled=True, get_run_state=lambda owner, run: debug_states.get((owner, run), {}),
        is_cancelled_async=is_debug_cancelled,
    ))
    monkeypatch.setattr(ephemeral, "RUNTIME_CANCEL_POLL_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(debug_lifecycle, "agent_run_manager", ephemeral.agent_run_manager)
    monkeypatch.setattr(debug_lifecycle, "runtime_state_service", ephemeral.runtime_state_service)
    monkeypatch.setattr(debug_lifecycle, "get_db_session", nullcontext)
    monkeypatch.setattr(debug_lifecycle, "tenant_membership_matches", lambda *_: True)

    async def inline(_label, function, *args, lane=None, owner=None, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ephemeral, "run_blocking", inline)
    monkeypatch.setattr(debug_lifecycle, "run_blocking", inline)
    monkeypatch.setattr(manager, "submit", submit)
    monkeypatch.setattr(ephemeral, "runtime_thread_manager", manager)
    monkeypatch.setattr(ephemeral, "load_prepared_run", load)
    monkeypatch.setattr(sdk_runner, "agent_run_thread", worker)
    monkeypatch.setattr(evaluation_snapshot, "prepare_a2a_snapshot", compile_snapshot)

    async def compile_debug(request, user_id, tenant_id, *, language, timezone):
        assert (user_id, tenant_id, language) == (actor.user_id, actor.tenant_id, "en")
        assert request.is_debug and request.version_no is None and request.query == "wait"
        resource = template.resource.model_copy(update={"version_no": 0})
        return template.model_copy(update={
            "debug": True, "resource": resource, "input": template.input.model_copy(update={"query": request.query}),
        })

    monkeypatch.setattr(evaluation_snapshot, "prepare_debug_snapshot", compile_debug)
    monkeypatch.setattr(runtime_client, "forward_agent_run", AsyncMock(side_effect=AssertionError("legacy dispatch")))
    signer = AsyncMock(return_value=[{"object_name": object_name, "presigned_url": "https://signed.invalid/report"}])
    monkeypatch.setattr(agentos_events, "run_blocking", signer)

    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(ephemeral.create_ephemeral_run_router())
    app.include_router(create_compatibility_router(None, None, debug_stop=debug_lifecycle.stop_agentos_debug))
    management = FastAPI()
    management.include_router(conversation_run.router)
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda tenant: (actor.user_id, tenant))
    manager.start()
    try:
        with serve(app) as base:
            client = AgentOSClient(base, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
            monkeypatch.setattr(runtime_client, "_agentos_client", lambda: client)
            async with httpx.AsyncClient(trust_env=False) as unauthenticated:
                rejected = await unauthenticated.post(
                    f"{base}/api{AgentOperation.RUN_EPHEMERAL.value}", json=template.model_dump(mode="json"),
                )
            assert rejected.status_code == 401 and not executions

            request = AgentRequest(query="finish", agent_id=7, version_no=3, is_debug=True)
            success = await runtime_client.forward_a2a_run(request, actor.user_id, actor.tenant_id)
            frames = [json.loads(frame[6:]) async for frame in success.body_iterator]
            assert frames[0] == {"type": "final_answer", "content": "answer"}
            assert frames[1]["type"] == "files" and len(frames) == 2
            assert json.loads(frames[1]["content"])["file_uploads"][0]["object_name"] == object_name
            assert signer.await_args.args[2] == [{"object_name": object_name, "file_name": "report.txt", "status": "success"}]

            live = await runtime_client.forward_a2a_run(
                request.model_copy(update={"query": "wait"}), actor.user_id, actor.tenant_id,
            )
            assert live.status_code == 200
            assert json.loads((await anext(live.body_iterator))[6:]) == frames[0]
            await live.body_iterator.aclose()
            deadline = asyncio.get_running_loop().time() + 3
            while any(stage.exists() for stage in stages) or released.call_count != 2:
                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.02)
            assert calls == ["finish", "wait"] and len(stages) == 2 and not any(stage.exists() for stage in stages)
            assert worker_stopped.is_set()
            assert all(item.future.done() for item in executions)
            assert released.call_count == reserve.call_count == 2

            reserve.side_effect = ephemeral.AgentRunConcurrencyExceededError
            overloaded = await runtime_client.forward_a2a_run(request, actor.user_id, actor.tenant_id)
            assert overloaded.status_code == 429 and overloaded.headers["Retry-After"] == "1"
            assert "RUNTIME_CAPACITY_FULL" in b"".join([chunk async for chunk in overloaded.body_iterator]).decode()
            assert len(executions) == 2 and released.call_count == 2

            reserve.side_effect = None
            worker_stopped.clear()
            headers = {"Authorization": actor.tenant_id, "Cookie": "NEXT_LOCALE=en"}
            with serve(management) as public_url:
                async with httpx.AsyncClient(base_url=public_url, trust_env=False, timeout=4) as browser:
                    async with browser.stream("POST", "/agent/run", headers=headers, json={
                        "query": "wait", "agent_id": 7, "is_debug": True,
                    }) as debug:
                        assert debug.status_code == 200 and debug.headers["run_id"] == f"debug-{run_id}"
                        assert "conversation_id" not in debug.headers
                        lines = debug.aiter_lines()
                        assert json.loads((await anext(lines))[6:]) == frames[0]
                        stop_url = f"/agent/stop/{debug.headers['run_id']}"
                        foreign = await browser.get(stop_url, headers={"Authorization": "foreign"})
                        assert foreign.json()["already_stopped"] is True and not cancel_signals
                        stopped = await browser.get(stop_url, headers=headers)
                        assert stopped.status_code == 200 and "already_stopped" not in stopped.json()
                        assert cancel_signals == {(debug_lifecycle.debug_owner(actor), f"debug-{run_id}")}
                        assert not [line async for line in lines if line]
            assert worker_stopped.is_set() and len(executions) == 3 and all(item.future.done() for item in executions)
            assert not debug_states and not stages[-1].exists()
            assert released.call_count == 3 and reserve.call_count == 4
    finally:
        await manager.shutdown(timeout=2)


async def _assert_automation_proposal_callback(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from contracts.agentos import AgentResource, ManagementOperation, ToolBinding
    from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL
    from management.api.automation import agentos_callback as callback_api
    from management.services.automation import agentos_callback, proposal
    from nexent.core.agents.nexent_agent import NexentAgent
    from runtime.agentos import resume
    from runtime.agentos.prepared_automation import materialize_automation_tool

    actor = ServicePrincipal("proposal-user", "proposal-tenant")
    reference = AgentRunReference(conversation_id=56, run_id="c" * 32)
    turn = SimpleNamespace(reference=reference, user_id=actor.user_id, tenant_id=actor.tenant_id,
                           assistant_message_id=None)
    confirmed = SimpleNamespace(**{**vars(turn), "assistant_message_id": 91})
    observations = Mock()
    sources = []

    def owned_turn(ref, user_id, tenant_id):
        return turn if (ref, user_id, tenant_id) == (reference, actor.user_id, actor.tenant_id) else None

    def inspect(run_id, user_id, tenant_id, conversation_id, **_):
        assert (run_id, user_id, tenant_id, conversation_id) == (
            reference.run_id, actor.user_id, actor.tenant_id, reference.conversation_id,
        )
        return {"conversation_id": conversation_id, "status": "running", "cancellation_requested": False}

    async def inline(_name, fn, *args, lane=None, owner=None, **kwargs):
        return fn(*args, **kwargs)

    async def create(request, tenant_id, user_id, **options):
        assert (tenant_id, user_id) == (actor.tenant_id, actor.user_id)
        assert request.message == "Remind me every Monday" and request.agent_version_no == 3
        assert options["persist_conversation_exchange"] is False and options["force_llm"] is True
        sources.append(options["source_message_id"])
        return {"proposal_id": 84, "title": "Weekly reminder"}

    monkeypatch.setattr(agentos_callback, "run_blocking", inline)
    monkeypatch.setattr(agentos_callback.store, "automation_turn", owned_turn)
    confirm = Mock(return_value=confirmed)
    monkeypatch.setattr(agentos_callback.store, "confirm_turn", confirm)
    monkeypatch.setattr(agentos_callback.store, "automation_source", lambda current: {
        "agent_id": 7, "agent_version_no": 3, "source_message_id": 92,
        "user_message": "Remind me every Monday",
    } if current is confirmed else None)
    monkeypatch.setattr(proposal.agent_automation_facade, "create_proposal", AsyncMock(side_effect=create))
    monkeypatch.setattr(resume, "_control_io", inline)
    monkeypatch.setattr(resume, "read_execution", inspect)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=False))

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(resume.create_run_lifecycle_router())
    management = FastAPI(root_path="/api")
    management.add_middleware(GatewayIdentityMiddleware, audience="management", required=True)
    management.include_router(callback_api.router)
    with serve(runtime) as runtime_url, serve(management) as management_url:
        monkeypatch.setattr(agentos_callback, "_agentos_client",
                            lambda: AgentOSClient(runtime_url, lambda **kw: httpx.AsyncClient(trust_env=False, **kw)))
        monkeypatch.setattr(environment, "MANAGEMENT_AGENTOS_URL", management_url)
        resource = AgentResource(
            agent_id=7, version_no=3, name="agent", description="", prompt_templates={},
            tools=[ToolBinding(tool_id=AUTOMATION_PROPOSAL_TOOL, version="1")],
        )
        config = materialize_automation_tool(resource, actor, reference)[AUTOMATION_PROPOSAL_TOOL]
        tool = NexentAgent.create_builtin_tool(SimpleNamespace(observer=observations), config)
        response = await asyncio.to_thread(tool.forward, "Untrusted text supplied by the model")
        assert "scheduled-task proposal is ready" in response
        assert observations.add_message.call_args.args[1].value == "automation_proposal"
        assert json.loads(observations.add_message.call_args.args[2])["proposal_id"] == 84

        operation = ManagementOperation.AUTOMATION_PROPOSAL
        path = f"/api{operation.value}"
        body = reference.model_dump_json().encode()
        async with httpx.AsyncClient(base_url=management_url, trust_env=False) as client:
            raw = await client.post(path, content=body)
            forward = sign_call(AgentOperation.RUN, body, actor)
            rejected = await client.post(path, content=body, headers={"Authorization": f"Bearer {forward}"})
            foreign = sign_call(operation, body, ServicePrincipal(actor.user_id, "other"))
            denied = await client.post(path, content=body, headers={"Authorization": f"Bearer {foreign}"})
            valid = sign_call(operation, body, actor)
            tampered = await client.post(path, content=body + b" ", headers={"Authorization": f"Bearer {valid}"})
            another = reference.model_copy(update={"run_id": "d" * 32}).model_dump_json().encode()
            cross_run = sign_call(operation, another, actor)
            forbidden = await client.post(path, content=another, headers={"Authorization": f"Bearer {cross_run}"})
        assert (raw.status_code, rejected.status_code, denied.status_code, tampered.status_code) == (401, 401, 404, 401)
        assert forbidden.status_code == 404
    assert sources == [92]
    confirm.assert_called_once_with(turn)
