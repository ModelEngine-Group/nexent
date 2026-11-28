# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""CHAT-MODEL-CONTROLS-D2-002: actual API permissions and safe model errors."""

import pytest

from model_controls.api import api_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D2-002"), pytest.mark.stage("D2")]


@pytest.fixture
def api(monkeypatch):
    return api_fixture(monkeypatch)


def test_model_permission_and_tenant_preflight(api):
    for path, denied in [("/api/agent/nl2agent/run", "no-agent-create"), ("/api/skills/nl2skill/run", "no-skill-create")]:
        assert api.post(path, api.payload(path), token=None).status_code == 401
        assert api.post(path, api.payload(path), token=denied).status_code == 403
        assert api.calls == []
    for path in ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"]:
        for label, status, code in [("foreign", 404, "model_not_available"),
                                    ("embedding", 400, "model_type_invalid")]:
            model_id = api.records[label]["model_id"]
            api.configured.append(model_id)
            response = api.post(path, api.payload(path, model_id=model_id))
            assert response.status_code == status, response.text
            assert response.json()["detail"] == {"code": code}
            assert "fixture.invalid" not in response.text and "api_key" not in response.text
        missing = max(r["model_id"] for r in api.records.values()) + 1
        api.configured.append(missing)
        assert api.post(path, api.payload(path, model_id=missing)).json()["detail"] == {"code": "model_not_available"}
    assert api.calls == []
    # A past connectivity check is evidence, not a current execution gate.
    stale_id = api.records["unavailable"]["model_id"]
    for path in ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"]:
        api.configured.append(stale_id)
        assert api.post(path, api.payload(path, model_id=stale_id)).status_code == 200
    assert len(api.calls) == 3
    api.calls.clear()
    plain_id = api.records["plain"]["model_id"]
    api.configured = [api.records["effort"]["model_id"]]
    assert api.post("/api/agent/run", api.payload("/api/agent/run", model_id=plain_id)).status_code == 403
    response = api.post("/api/skills/nl2skill/run", api.payload("/api/skills/nl2skill/run", model_id=plain_id,
                                                            model_parameter_preferences={str(plain_id): {"enable_thinking": True, "reasoning_effort": "xhigh"}}))
    assert response.status_code == 422 and api.calls == []
    valid = api.records["effort"]["model_id"]
    assert api.post("/api/skills/nl2skill/run", api.payload("/api/skills/nl2skill/run", model_id=valid)).status_code == 200
    assert len(api.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("root_id", [7, 48])
async def test_configured_model_failure_names_pinned_agent(monkeypatch, root_id):
    """Exercise recursive compilation through the public JSON error handler."""
    from unittest.mock import AsyncMock, Mock

    import httpx

    from backend.http.server.app_factory import create_app
    from management.api.agent import conversation_run
    from management.services.agent.preparation import compiler

    child = {"name": "chef", "display_name": "厨师助手", "model_ids": [104], "description": ""}
    parent = {"name": "parent", "display_name": "协作问答助手", "model_ids": [95], "description": ""}
    monkeypatch.setattr(compiler, "search_agent_info_by_agent_id", lambda **kw: child if kw["agent_id"] == 48 else parent)
    monkeypatch.setattr(compiler, "query_sub_agent_relations", lambda **kw:
        [{"selected_agent_id": 48, "selected_agent_version_no": 1}] if kw["main_agent_id"] == 7 else [])
    monkeypatch.setattr(compiler, "get_model_by_model_id", lambda mid, **kw:
        {"model_id": 95, "display_name": "valid-root", "connect_status": "available"} if mid == 95 else None)
    for name in ("_get_external_a2a_agents", "_get_skill_script_tools", "_get_skills_for_template"):
        monkeypatch.setattr(compiler, name, Mock(return_value=[]))
    monkeypatch.setattr(compiler, "create_tool_config_list", AsyncMock(return_value=[]))
    monkeypatch.setattr(compiler, "get_config_snapshot", lambda: {"RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS": 120})
    monkeypatch.setattr(conversation_run, "get_current_user_id", lambda _: ("actor", "tenant"))
    dispatch = Mock(side_effect=AssertionError("Runtime must not receive an invalid Agent graph"))

    async def prepare(payload, user_id, tenant_id):
        await compiler.create_agent_config(agent_id=root_id, version_no=1, tenant_id=tenant_id,
                                           user_id=user_id, allow_memory_search=False, portable_evaluation=True)
        return dispatch()

    monkeypatch.setattr(conversation_run, "forward_conversation_run", prepare)
    app = create_app(enable_monitoring=False)
    app.include_router(conversation_run.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post("/api/agent/run", json={"query": "hello", "agent_id": root_id})
    assert response.status_code == 404
    assert response.json() == {"message": {"code": "model_not_available", "details": {
        "agent_id": 48, "agent_name": "厨师助手", "version_no": 1,
    }}}
    assert "协作问答助手" not in response.text
    assert "api_key" not in response.text and "base_url" not in response.text
    dispatch.assert_not_called()
