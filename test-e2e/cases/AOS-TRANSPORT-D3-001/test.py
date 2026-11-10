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
    EvaluationAgentResult, EvaluationAgentRun, PreparedEvaluationRun,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from gateway.downstream.middleware import GatewayIdentityMiddleware
from gateway.security.context import trusted_identity
from infrastructure import agentos_identity
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.clients.agentos import AgentOSClient
from runtime.agentos.compatibility import create_background_router, create_compatibility_router
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
    runtime.include_router(create_evaluation_router(evaluate))
    runtime.include_router(create_background_router(background, inspect))

    with serve(runtime) as runtime_url:
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

            case = EvaluationAgentRun(agent_id=7, version_no=3, query="question", conversation_id=-12)
            result = await agentos.run_evaluation_case(case, principal.user_id, principal.tenant_id)
            assert result.answer == "answer"
            assert result.events == case_events
            invalid = json.dumps(case.model_dump() | {"conversation_id": 42}).encode()
            signed = sign_call(CompatibilityOperation.EVALUATION_CASE, invalid, principal)
            response = await client.post(
                f"{runtime_url}/api{CompatibilityOperation.EVALUATION_CASE.value}",
                content=invalid,
                headers={"Authorization": f"Bearer {signed}"},
            )
            assert response.status_code == 422

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
    await _assert_resume_over_signed_http(monkeypatch)
    await _assert_run_lifecycle_over_signed_http(monkeypatch)
    await _assert_public_conversation_over_signed_http(monkeypatch)
    with monkeypatch.context() as lifecycle_patches:
        await _assert_public_stop_and_background(lifecycle_patches)
    await _assert_runtime_legacy_ingress_and_lifecycle(monkeypatch)


async def _assert_stored_local_tool_over_signed_http(monkeypatch, tmp_path):
    from fastapi import Request

    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.local_tool_execution import build_local_tool
    from management.services.agent.preparation import evaluation_snapshot
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from runtime.agentos import prepared_evaluation, prepared_local_tool
    from runtime.executions import LocalExecutionRegistry

    model_record = {
        "model_id": 18, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm",
        "model_name": "fixture-model", "model_repo": None, "display_name": "eval_llm",
        "api_key": "local-llm", "base_url": "https://provider.invalid/v1", "update_time": "revision-1",
    }
    provider = FastAPI()
    calls = []

    @provider.post("/v1/datasets/fixture-private-dataset/retrieve")
    async def retrieve(request: Request):
        payload = await request.json()
        calls.append((request.headers.get("authorization"), payload["query"], payload["retrieval_model"]["top_k"]))
        return {"records": [{"score": 0.8, "segment": {"content": "scoped Dify result"}}]}

    async def run(info, thread_manager):
        tool_config, = info.agent_config.tools
        assert tool_config.name == "dify_search"
        tool = NexentAgent.create_local_tool(SimpleNamespace(observer=None), tool_config)
        answer = await asyncio.to_thread(tool.forward, "fixture query")
        assert "scoped Dify result" in answer
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
        enabled = [row]

        def read_tools(agent_id, version_no, tenant_id, names):
            assert (agent_id, version_no, names) == (8, 4, ["dify_search"])
            return enabled if tenant_id == "tenant-a" else []

        for module in (evaluation_snapshot, prepared_local_tool):
            monkeypatch.setattr(module, "read_bound_local_tools", read_tools)
        model = create_model_config_from_record(model_record)
        agent = AgentConfig(
            agent_id=8, version_no=4, name="eval", description="Scoped tool",
            prompt_templates={"system_prompt": "Evaluate the search"}, model_name=model.cite_name,
            tools=[build_local_tool(row, "en", None, None)],
        )
        prepared = evaluation_snapshot.export_snapshot(
            agent, [model], "question", None, tenant_id="tenant-a", conversation_id=-60, language="en",
        )
        assert isinstance(prepared, PreparedEvaluationRun)
        for secret in (provider_url, "synthetic-runtime-dify-key", "fixture-private-dataset"):
            assert secret not in prepared.model_dump_json()

        client = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
        result = await client.run_prepared_evaluation(prepared, "user-a", "tenant-a")
        assert result.events == [
            {"type": "thought", "content": "lookup"}, {"type": "final_answer", "content": "scoped Dify result"},
        ]
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


async def _assert_prepared_evaluation_over_signed_http(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from infrastructure import agent_attachments
    from infrastructure.object_storage.client import minio_client
    from infrastructure.agent_model_config import create_model_config_from_record
    from infrastructure.agent_tool_config import build_parallel_executor_tool_config
    from infrastructure.local_tool_execution import build_local_tool
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

    def read_local_skill_tool(agent_id, version_no, tenant_id, names):
        assert (agent_id, version_no, names) == (7, 2, ["dify_search"])
        return [derived_local] if tenant_id == "tenant-a" else []

    monkeypatch.setattr(evaluation_snapshot, "read_bound_local_tools", lambda *_: [])
    for module in (evaluation_snapshot, prepared_local_tool):
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
            "analyze_image", "dify_search",
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
               build_mcp_tool(derived_tool), kb_tool, image_tool, build_local_tool(derived_local, "zh", None, None)],
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
    from contracts.agent import AgentRequest
    from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionRequestConflict
    from management.api.agent import conversation_run
    from management.services.agent import runtime_client
    from runtime.agentos import admission

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

    monkeypatch.setattr(admission, "_control_io", control_io)
    monkeypatch.setattr(admission, "claim_conversation_run", claim)
    monkeypatch.setattr(
        admission, "conversation_belongs_to",
        lambda conversation_id, *, user_id, tenant_id: (conversation_id, user_id, tenant_id) == (42, "user-a", "tenant-a"),
    )

    async def run_conversation(payload, actor):
        received.append((payload, actor))

        async def body():
            yield _EVENTS

        def stream():
            return StreamingResponse(
                body(), media_type="text/event-stream",
                headers={"X-AgentOS-Run-ID": run_id, "conversation_id": "42"},
            )

        if payload.idempotency_key is None:
            return stream()
        request = AgentRequest.model_validate(payload.request)

        async def execute():
            assert request._projection_run_id == run_id
            scope = request._run_admission_scope
            claims[scope] = (claims[scope][0], "admitted")
            executions.append(run_id)
            return stream()

        return await admission.admit_conversation_run(payload, request, actor, execute)

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

    assert len(received) == 4
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
