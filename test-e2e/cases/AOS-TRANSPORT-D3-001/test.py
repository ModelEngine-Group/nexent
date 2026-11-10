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
async def test_signed_agentos_transport(monkeypatch):
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
    await _assert_prepared_evaluation_over_signed_http(monkeypatch)
    await _assert_resume_over_signed_http(monkeypatch)
    await _assert_run_lifecycle_over_signed_http(monkeypatch)
    await _assert_public_conversation_over_signed_http(monkeypatch)
    await _assert_public_stop_and_background(monkeypatch)


async def _assert_prepared_evaluation_over_signed_http(monkeypatch):
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent import runtime_client
    from management.services.agent.preparation import evaluation_snapshot
    from infrastructure.a2a_execution import build_external_agent_config
    from nexent.core.agents.agent_model import AgentConfig, ToolConfig
    from runtime.agentos import prepared_evaluation
    from runtime.executions import LocalExecutionRegistry

    key = "synthetic-prepared-evaluation-fixture-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    monkeypatch.setattr(prepared_evaluation, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")

    lookups = []
    invocations = []
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

    async def run(info, thread_manager):
        assert registry.get_agent_run_info(-42, "user-a") is info
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
        worker_agents=[AgentConfig(
            agent_id=8, version_no=5, name="child", invocation_name="child_lookup",
            description="Static child", model_name=model.cite_name, tools=[], external_a2a_agents=[external],
        )],
        tools=[ToolConfig(
            class_name="DownloadFromS3Tool", name="download_from_s3", source="builtin", usage="builtin",
            params={"workspace_path": "/management/workspace"},
            metadata={"validate_url_access": lambda _urls: None},
        )],
    )
    monkeypatch.setattr(evaluation_snapshot, "get_model_records", lambda _filters, _tenant: [record])
    case = EvaluationAgentRun(agent_id=7, version_no=2, query="question", conversation_id=-42)
    prepared = evaluation_snapshot.export_snapshot(
        agent, [model], case.query, None, tenant_id="tenant-a", conversation_id=-42, language="zh",
    )
    assert isinstance(prepared, PreparedEvaluationRun)
    assert "/management/workspace" not in prepared.model_dump_json()
    assert "only-in-runtime" not in prepared.model_dump_json()
    assert external_row["agent_url"] not in prepared.model_dump_json()
    assert "local-peer-token" not in prepared.model_dump_json()

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
        with pytest.raises(RuntimeUpstreamError) as refused:
            await agentos.run_prepared_evaluation(prepared, "user-a", "tenant-b")
        assert refused.value.status_code == 404
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
    assert external_reads == [(8, "tenant-a", [19]), (8, "tenant-b", [19]), (8, "tenant-a", [19])]
    assert invocations == [("user-a", "tenant-a", -42)]
    assert registry.get_agent_run_info(-42, "user-a") is None


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
