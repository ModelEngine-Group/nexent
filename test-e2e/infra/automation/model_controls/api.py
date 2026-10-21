# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual router/DTO/RBAC contracts with an isolated service boundary."""

import json
from dataclasses import dataclass, field

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from management.api.agent import agent as agent_app
from runtime.api.agent import execution as agent_app_execution
from management.api.skill import skill as skill_app
from runtime.api.skill import creation as skill_app_creation
from agents import create_agent_info
from contracts.exceptions import ForbiddenError
from management.services.model import run_controls
from nexent.core.agents.agent_model import AgentConfig
from permissions import depends, rbac
from permissions.models import CurrentUser

EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
CAPABILITY = {"status": "supported", "control": "effort", "levels": EFFORTS,
              "wire_format": "reasoning_effort", "source": "operator"}
BUDGET = {"status": "supported", "control": "budget_tokens", "levels": [],
          "controls": [{"type": "budget_tokens", "min": 1024, "max": 8192}],
          "budget_wire_format": "thinking_budget", "source": "operator"}


@dataclass
class ApiFixture:
    client: TestClient
    records: dict
    calls: list = field(default_factory=list)
    configured: list = field(default_factory=list)

    def payload(self, path, **values):
        body = {"query": "Create model-control fixture", **values}
        if "nl2agent" in path or path == "/api/agent/run":
            body["agent_id"] = 7
        return body

    def post(self, path, body, token="creator"):
        return self.client.post(path, json=body, headers={"Authorization": f"Bearer {token}"} if token else {})


def api_fixture(monkeypatch):
    app = FastAPI()
    app.include_router(agent_app_execution.agent_runtime_router, prefix="/api")
    app.include_router(skill_app_creation.skill_creator_router, prefix="/api")
    records = {}
    for index, label in enumerate(["effort", "budget", "plain", "unavailable", "foreign", "embedding"], start=1):
        records[label] = {"model_id": index, "model_name": label, "model_repo": "", "display_name": label,
                          "model_factory": "OpenAI", "base_url": "http://fixture.invalid/v1", "api_key": "fixture-key",
                          "tenant_id": "other" if label == "foreign" else "tenant",
                          "model_type": "embedding" if label == "embedding" else "llm",
                          "connect_status": "Unavailable" if label == "unavailable" else "Available",
                          "temperature": 0.43, "top_p": 0.78,
                          "extra_params": {"enable_thinking": True, "reasoning_effort": "medium"}}
    state = ApiFixture(TestClient(app), records, configured=[records["effort"]["model_id"]])
    from management.services.configuration.tenant.settings import tenant_config_manager
    monkeypatch.setattr(tenant_config_manager, "get_model_config", lambda *a, **k: records["effort"])

    def authenticate(authorization: str | None = Header(None)):
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")
        role = authorization.removeprefix("Bearer ").upper()
        return CurrentUser("fixture-owner", "tenant", role)

    app.dependency_overrides[depends.authenticate] = authenticate
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {
        "CREATOR": {"agent:create", "skill:create"}, "NO-AGENT-CREATE": {"skill:create"},
        "NO-SKILL-CREATE": {"agent:create"},
    })
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(skill_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_info", lambda *args: ("fixture-owner", "tenant", "en"))
    monkeypatch.setattr(skill_app, "get_current_user_info", lambda *args: ("fixture-owner", "tenant", "en"))

    def lookup(model_id, tenant_id):
        return next((r for r in records.values() if r["model_id"] == model_id and r["tenant_id"] == tenant_id), None)

    monkeypatch.setattr(run_controls, "get_model_by_model_id", lookup)
    monkeypatch.setattr(create_agent_info, "_resolve_reasoning_capability",
                        lambda model_name, **kwargs: BUDGET if model_name == "budget" else
                        {"status": "unsupported", "levels": []} if model_name == "plain" else CAPABILITY)

    async def stream(request, ordinary=False):
        if ordinary and request.entrypoint != "workbench" and request.model_id and request.model_id not in state.configured:
            raise ForbiddenError("The selected model is not configured for this Agent")
        if ordinary and request.workbench:
            request.model_id = request.workbench.model_id
            request.generation_config = request.workbench.generation_config
        run_controls.preflight_turn_controls(request, "tenant")
        selected = lookup(request.model_id, "tenant") if request.model_id else records["effort"]
        base = create_agent_info.create_model_config_from_record(selected)
        values = request.generation_config.model_dump(exclude_unset=True) if request.generation_config else {}
        for legacy, canonical in (("reasoning_effort", "thinking_effort"), ("reasoning_budget_tokens", "reasoning_budget_tokens")):
            value = getattr(request, legacy, None)
            if value is not None:
                values[canonical] = value
        root = run_controls.overlay_root_model(base, values, "root")
        payload = {"model_id": selected["model_id"], "enabled": root.enable_thinking,
                   "effort": root.reasoning_effort, "budget": root.reasoning_budget_tokens,
                   "temperature": root.temperature, "top_p": root.top_p}
        state.calls.append(request.model_dump(exclude_unset=True))

        async def chunks():
            yield f"data: {json.dumps(payload)}\n\n"
        return chunks()

    async def agent_run_stream(agent_request, **kwargs):
        return StreamingResponse(await stream(agent_request, True), media_type="text/event-stream")

    async def creator_stream(request, **kwargs):
        return await stream(request)

    monkeypatch.setattr(agent_app, "run_agent_stream", agent_run_stream)
    monkeypatch.setattr(agent_app, "create_nl2agent_stream", creator_stream)
    monkeypatch.setattr(skill_app, "create_nl2skill_stream", creator_stream)
    return state
