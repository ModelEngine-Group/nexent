# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual router/DTO/RBAC contracts with an isolated service boundary."""

import gateway.authentication.auth as depends_dependencies
import json
from dataclasses import dataclass, field

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from runtime.api.agent import execution as agent_app_execution
from runtime.api.skill import creation as skill_app_creation
from management.services.model import run_bindings
from contracts.errors.exceptions import ForbiddenError
from management.services.model import run_controls
from nexent.core.agents.agent_model import AgentConfig
import permissions.depends as depends
from permissions import rbac
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

    app.dependency_overrides[depends_dependencies.authenticate] = authenticate
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {
        "CREATOR": {"agent:create", "skill:create"}, "NO-AGENT-CREATE": {"skill:create"},
        "NO-SKILL-CREATE": {"agent:create"},
    })
    monkeypatch.setattr(agent_app_execution, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(skill_app_creation, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app_execution, "get_current_user_info", lambda *args: ("fixture-owner", "tenant", "en"))
    monkeypatch.setattr(skill_app_creation, "get_current_user_info", lambda *args: ("fixture-owner", "tenant", "en"))

    def lookup(model_id, tenant_id):
        return next((r for r in records.values() if r["model_id"] == model_id and r["tenant_id"] == tenant_id), None)

    monkeypatch.setattr(run_controls, "get_model_by_model_id", lookup)
    monkeypatch.setattr(run_bindings, "_resolve_reasoning_capability",
                        lambda model_name, **kwargs: BUDGET if model_name == "budget" else
                        {"status": "unsupported", "levels": []} if model_name == "plain" else CAPABILITY)

    from model_controls.profiles import frozen_fixture_profile
    profiles = {row["model_id"]: frozen_fixture_profile(row, BUDGET if label == "budget" else
        {"status": "unsupported"} if label == "plain" else CAPABILITY)
        for label, row in records.items() if label != "embedding"}
    from management.db.model import outlets as model_outlet_db
    monkeypatch.setattr(model_outlet_db, "get_resolved_model_record", lambda identifier, *args, **kwargs: profiles.get(identifier))

    async def stream(request, ordinary=False):
        if ordinary and request.entrypoint != "workbench" and request.model_id and request.model_id not in state.configured:
            raise ForbiddenError("The selected model is not configured for this Agent")
        if ordinary and request.workbench:
            request.model_id = request.workbench.model_id
        run_controls.preflight_turn_controls(request, "tenant")
        selected = lookup(request.model_id, "tenant") if request.model_id else records["effort"]
        from management.services.conversation.model_preferences import merge_model_preferences
        root = merge_model_preferences(profiles[selected["model_id"]], request.model_parameter_preferences.get(str(selected["model_id"]), {}))
        values = root.parameter_values
        payload = {"model_id": selected["model_id"], "enabled": values.get("enable_thinking"),
                   "effort": values.get("reasoning_effort"), "budget": values.get("reasoning_budget_tokens"),
                   "temperature": values.get("temperature"), "top_p": values.get("top_p")}
        state.calls.append(request.model_dump(exclude_unset=True))
        async def chunks():
            yield f"data: {json.dumps(payload)}\n\n"
        return chunks()

    async def agent_run_stream(agent_request, **kwargs):
        return StreamingResponse(await stream(agent_request, True), media_type="text/event-stream")

    async def creator_stream(request, **kwargs):
        return await stream(request)

    monkeypatch.setattr(agent_app_execution, "run_agent_stream", agent_run_stream)
    monkeypatch.setattr(agent_app_execution, "create_nl2agent_stream", creator_stream)
    monkeypatch.setattr(skill_app_creation, "create_nl2skill_stream", creator_stream)
    return state
