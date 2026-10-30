# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real services, SDK and MCP/HTTP runtime backed by disposable PostgreSQL."""

import asyncio
import json
import socket
import sys
import threading
import time
from contextlib import contextmanager
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.api.agent import execution as agent_app_execution
from management.services.agent.preparation import run as agent_preparation

from runtime.api.skill import creation as skill_app_creation

from management.api.conversation import conversation_management as conversation_management_app
from model_controls.database import database_fixture
from model_controls.provider import Provider
from services import nl2agent_service as nl2agent_service
from services import nl2skill_service as nl2skill_service
from infrastructure.concurrency import runtime_thread_manager
from nexent.core.concurrency.helpers import shutdown_fallback_thread_manager
from nexent.core.concurrency import ThreadManager
from tool_collection.mcp.local_mcp_service import local_mcp_service


@contextmanager
def mcp_server():
    app = local_mcp_service.http_app(transport="sse", path="/sse")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[listener])), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("Case-owned MCP server did not start")
    try:
        yield f"http://127.0.0.1:{port}/sse"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


class RuntimeFixture:
    def __init__(self, storage, provider, client, runs):
        self.storage, self.provider, self.client = storage, provider, client
        self.models = storage["models"]
        self.agent_id = storage["agent_id"]
        self.runs = runs

    def post(self, path, label="selected-B", generation=None, workbench=False, **values):
        model_id = self.models[label]
        body = {"query": "Complete the model controls fixture.", "model_id": model_id, "history": [], **values}
        if "agent" in path:
            body["agent_id"] = self.agent_id
        if generation is not None:
            from model_controls.profiles import preference_values
            body["model_parameter_preferences"] = {str(model_id): preference_values(generation)}
        if workbench:
            config = {"schema_version": 4, "mode": "agent_create" if "nl2agent" in path else
                      "skill_create" if "nl2skill" in path else "generic_chat",
                      "agent_mounts": [], "skill_mounts": []}
            if "nl2" in path:
                body["workbench_config"] = config
                body["persist_history"] = True
            else:
                body.update(entrypoint="workbench", workbench=config)
        headers = {"Authorization": "Bearer fixture-creator"}
        if body.get("conversation_id") and body.get("model_parameter_preferences"):
            preferences = body.pop("model_parameter_preferences")[str(model_id)]
            endpoint = f"/api/conversation/{body['conversation_id']}/model_preferences"
            saved = self.client.get(endpoint, headers=headers)
            assert saved.status_code == 200, saved.text
            selected = self.client.patch(endpoint, headers=headers, json={
                "selected_model_id": model_id, "expected_version": saved.json()["data"]["version"]})
            assert selected.status_code == 200, selected.text
            patched = self.client.patch(endpoint + f"/{model_id}", headers=headers, json={
                "parameter_values": preferences, "expected_version": selected.json()["data"]["version"]})
            assert patched.status_code == 200, patched.text
        return self.client.post(path, json=body, headers=headers)

    def draft(self):
        from sqlalchemy import select
        from management.db.models import AgentInfo
        with self.storage["sessions"]() as session:
            row = session.scalars(select(AgentInfo).where(AgentInfo.agent_id == self.agent_id, AgentInfo.version_no == 0)).one()
            return {"description": row.description, "model_ids": list(row.model_ids), "model_params_override": row.model_params_override,
                    "business_logic_model_id": row.business_logic_model_id}

    def set_outlet_defaults(self, label, values):
        from management.db.model.models import ModelRecord
        from management.services.model.adapter import restore_model_snapshot
        from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
        from nexent.core.model_service.registry import model_service_references
        with self.storage["sessions"]() as session:
            record = session.get(ModelRecord, self.models[label])
            row = {column.name: getattr(record, column.name) for column in record.__table__.columns}
            profile = restore_model_snapshot(row, row["tenant_id"])
            profile = profile.model_copy(update={"parameter_values": values(profile.parameter_values)})
            for key, value in encode_resolved_model_profile(profile, registered_references=model_service_references()).items():
                setattr(record, key, value)

    def model_records(self):
        from sqlalchemy import select
        from management.db.models import ModelRecord
        with self.storage["sessions"]() as session:
            return {row.model_id: (row.model_name, row.base_url, row.temperature, row.top_p, row.extra_params)
                    for row in session.scalars(select(ModelRecord))}


def _bind_case_mcp(monkeypatch, mcp_url, *consumers):
    """Route each real preparation consumer to the same case-owned server."""
    for module in consumers:
        monkeypatch.setattr(module, "get_tenant_local_mcp_server", lambda _: mcp_url)


@contextmanager
def runtime_fixture(monkeypatch):
    provider = Provider()
    try:
        with database_fixture(monkeypatch, provider) as storage, mcp_server() as mcp_url, TemporaryDirectory(prefix="model-controls-workspaces-") as workspace:
            from management.services.agent.preparation import inputs
            monkeypatch.setattr(inputs, "AGENT_WORKSPACE_ROOT", workspace)
            manager = ThreadManager("model-controls-case", runtime_thread_manager._policies)
            manager.start()
            for name, module in list(sys.modules.items()):
                if name.startswith(("services.", "management.", "tool_collection.")) and getattr(module, "runtime_thread_manager", None) is runtime_thread_manager:
                    monkeypatch.setattr(module, "runtime_thread_manager", manager)
            owner, tenant = storage["owner"], storage["tenant"]
            # Authentication is an external issuer boundary. RBAC, DAC, storage,
            # model resolution, capacity policy, services and SDK remain real.
            for name, module in list(sys.modules.items()):
                if name.startswith(("gateway.", "services.", "management.", "runtime.", "permissions.", "tool_collection.")):
                    if hasattr(module, "get_current_user_id"):
                        monkeypatch.setattr(module, "get_current_user_id", lambda *a, **k: (owner, tenant))
                    if hasattr(module, "get_current_user_info"):
                        monkeypatch.setattr(module, "get_current_user_info", lambda *a, **k: (owner, tenant, "en"))
                    if hasattr(module, "get_current_user_context"):
                        monkeypatch.setattr(module, "get_current_user_context", lambda *a, **k: (owner, tenant, "CREATOR"))
            from permissions import rbac
            old_permissions, old_initialized = rbac._ROLE_PERMISSIONS.copy(), rbac._INITIALIZED
            rbac.init_rbac()
            for module in (nl2agent_service, nl2skill_service, agent_preparation):
                if hasattr(module, "get_tenant_local_mcp_server"):
                    monkeypatch.setattr(module, "get_tenant_local_mcp_server", lambda _: mcp_url)
            monkeypatch.setattr(agent_app_execution, "ENABLE_AGENT_WORKBENCH", True)
            monkeypatch.setattr(skill_app_creation, "ENABLE_AGENT_WORKBENCH", True)
            from management.services.agent import execution as ordinary
            runs = []
            for module in (nl2agent_service, nl2skill_service, ordinary):
                original = module.agent_run
                async def observe(run_info, *args, _original=original, **kwargs):
                    runs.append(run_info)
                    async for event in _original(run_info, *args, **kwargs):
                        yield event
                monkeypatch.setattr(module, "agent_run", observe)
            original_run = agent_app_execution.run_agent_stream
            async def traced_run(*args, **kwargs):
                try:
                    return await original_run(*args, **kwargs)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    raise
            monkeypatch.setattr(agent_app_execution, "run_agent_stream", traced_run)

            def respond(body):
                messages = json.dumps(body["messages"])
                if "nl2a_save_agent_draft_fields" in messages:
                    if "Model controls fixture draft updated" not in messages:
                        return f'<code>result = nl2a_save_agent_draft_fields(agent_id={storage["agent_id"]}, fields={{"description": "Model controls fixture draft updated"}})\nprint(result)</code>'
                    return "<final_answer>Model controls fixture draft updated</final_answer>"
                if "<skill>" in messages or "skill creator" in messages.lower():
                    return "<final_answer><skill>---\nname: model_control_fixture\ndescription: Fixture skill\n---\n# Fixture\nPerform the fixture task.</skill><summary>Fixture created</summary></final_answer>"
                return "<final_answer>Model controls fixture completed.</final_answer>"

            provider.responder = respond
            app = FastAPI()
            app.include_router(agent_app_execution.agent_runtime_router, prefix="/api")
            app.include_router(skill_app_creation.skill_creator_router, prefix="/api")
            app.include_router(conversation_management_app.router, prefix="/api")
            with TestClient(app) as http:
                try:
                    yield RuntimeFixture(storage, provider, http, runs)
                finally:
                    async def shutdown():
                        await manager.shutdown(timeout=10)
                        await shutdown_fallback_thread_manager(timeout=10)
                    asyncio.run(shutdown())
                    rbac._ROLE_PERMISSIONS, rbac._INITIALIZED = old_permissions, old_initialized
    finally:
        provider.close()
