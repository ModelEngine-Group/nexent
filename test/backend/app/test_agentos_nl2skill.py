# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify NL2Skill crosses AgentOS only after Management authorizes the turn."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse

from contracts.agent import NL2SkillRunRequest
from management.api.skill import creation
from management.services.skill import creation as skill_service
from management.services.model import creator_snapshot

_ACTOR = ("user-a", "tenant-a", "en")


async def _inline(_name, function, *args, lane, owner, **kwargs):
    return function(*args, **kwargs)


@pytest.mark.asyncio
async def test_snapshot_uses_scoped_model_reference_and_normalized_draft(mocker):
    mocker.patch.object(creator_snapshot, "preflight_turn_controls")
    lookup = mocker.patch.object(creator_snapshot, "get_model_by_model_id", return_value={
        "model_id": 21, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm",
        "display_name": "selected", "api_key": "private-model-key", "update_time": "v1",
    })
    mocker.patch.object(creator_snapshot, "_resolve_input_budget", return_value=(8192, {}, None))
    mocker.patch.object(creator_snapshot, "_resolve_context_budget", return_value=None)
    payload = skill_service.prepare_nl2skill_snapshot(NL2SkillRunRequest(
        query='<use_script path="scripts/run.py" />', model_id=21, model_parameter_preferences={"21": {"temperature": 0.3}},
        draft_snapshot={"name": "draft", "files": [{"path": "scripts/run.py", "content": "print(1)"}]},
    ), "user-a", "tenant-a", "en")
    lookup.assert_called_once_with(21, "tenant-a")
    assert payload.mode == "nl2skill" and payload.model.model_id == 21 and payload.model.revision == "v1"
    assert payload.model.conversation_parameters == {"temperature": 0.3}
    assert payload.target_files == ["scripts/run.py"] and "print(1)" in payload.draft.content
    assert "private-model-key" not in payload.model_dump_json()


@pytest.mark.asyncio
async def test_foreign_conversation_is_rejected_before_agentos_or_history_write(mocker):
    mocker.patch.object(creation, "get_current_user_info", return_value=_ACTOR)
    mocker.patch.object(creation, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(creation, "run_blocking", side_effect=_inline)
    from contracts.agent import SystemAgentRef
    from management.services.conversation import creator_execution
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref",
                        return_value=SystemAgentRef("shared", "nl2skill_main", 78, 0))
    owned = mocker.patch.object(creator_execution, "get_conversation_history", return_value={"agent_id": 79})
    save = mocker.patch.object(creation, "prepare_creation_history")
    dispatch = mocker.patch.object(creation, "create_nl2skill_stream")
    with pytest.raises(HTTPException) as exc:
        await creation.nl2skill_run_api(
            NL2SkillRunRequest(query="continue", persist_history=True, conversation_id=42),
            authorization="Bearer test",
        )
    assert exc.value.status_code == 400
    owned.assert_called_once_with(42, "user-a")
    save.assert_not_called()
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_runtime_failure_closes_upstream_and_has_no_success_terminal(mocker):
    closed = False

    async def events():
        nonlocal closed
        try:
            yield b'event: agentos_execution_error\ndata: {"type":"error","content":"NL2Skill execution failed."}\n\n'
        finally:
            closed = True

    remote = mocker.patch.object(skill_service, "forward_creator_run", return_value=StreamingResponse(events()))
    snapshot = SimpleNamespace(target_files=[])
    stream = skill_service.create_nl2skill_stream(snapshot, "user-a", "tenant-a")
    remote.assert_not_awaited()
    assert [json.loads(item[6:]) async for item in stream] == [
        {"type": "error", "content": "NL2Skill execution failed.", "sequence": 1},
    ]
    remote.assert_awaited_once_with(snapshot, "user-a", "tenant-a")
    assert closed


@pytest.fixture
def skill_app(mocker):
    app = FastAPI()
    app.include_router(creation.skill_creator_router)
    app.dependency_overrides[creation.require_skill_create_permission] = lambda: None
    mocker.patch.object(creation, "run_blocking", side_effect=_inline)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected"), [(None, "en"), ("zh", "zh")])
async def test_public_route_preserves_stream_and_language(mocker, skill_app, language, expected):
    mocker.patch.object(creation, "get_current_user_info", return_value=_ACTOR)
    snapshot = object()
    compile_run = mocker.patch.object(creation, "prepare_nl2skill_snapshot", return_value=snapshot)

    async def stream():
        yield 'data: {"type":"done","content":""}\n\n'

    create_stream = mocker.patch.object(creation, "create_nl2skill_stream", return_value=stream())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=skill_app), base_url="http://management") as client:
        response = await client.post("/skills/nl2skill/run", json={"query": "Create", "language": language, "persist_history": False})
    assert response.status_code == 200 and response.text == 'data: {"type":"done","content":""}\n\n'
    assert compile_run.call_args.args[1:] == ("user-a", "tenant-a", expected)
    create_stream.assert_called_once_with(snapshot, "user-a", "tenant-a")


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "status", "detail"), [
    (RuntimeError("provider unavailable"), 500, "NL2Skill run error."),
    (HTTPException(status_code=409, detail="conflict"), 409, "conflict"),
])
async def test_public_route_preserves_preflight_error_mapping(mocker, skill_app, failure, status, detail):
    mocker.patch.object(creation, "get_current_user_info", return_value=_ACTOR)
    mocker.patch.object(creation, "prepare_nl2skill_snapshot", side_effect=failure)
    dispatch = mocker.patch.object(creation, "create_nl2skill_stream")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=skill_app), base_url="http://management") as client:
        response = await client.post("/skills/nl2skill/run", json={"query": "Create", "persist_history": False})
    assert response.status_code == status and response.json()["detail"] == detail
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_public_route_rejects_unauthorized_and_old_stop_stays_unavailable(mocker, skill_app):
    mocker.patch.object(creation, "get_current_user_info", side_effect=RuntimeError("unauthorized"))
    compile_run = mocker.patch.object(creation, "prepare_nl2skill_snapshot")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=skill_app), base_url="http://management") as client:
        response = await client.post("/skills/nl2skill/run", json={"query": "Create", "persist_history": False})
        removed = await client.get("/skills/stop/task123")
    assert response.status_code == 401
    assert removed.status_code == 404
    compile_run.assert_not_called()


@pytest.mark.asyncio
async def test_creation_stream_factory_http_exception_is_preserved(mocker):
    mocker.patch.object(creation, "get_current_user_info", return_value=_ACTOR)
    mocker.patch.object(creation, "run_blocking", side_effect=_inline)
    mocker.patch.object(creation, "prepare_nl2skill_snapshot", return_value=object())
    expected = HTTPException(status_code=409, detail="conflict")
    mocker.patch.object(creation, "create_nl2skill_stream", side_effect=expected)
    with pytest.raises(HTTPException) as error:
        await creation.nl2skill_run_api(NL2SkillRunRequest(query="Create", persist_history=False), authorization="token")
    assert error.value is expected


@pytest.mark.asyncio
async def test_default_route_persists_creator_and_model_preferences(mocker, skill_app):
    from contracts.agent import SystemAgentRef
    from management.services.conversation import creator_execution

    mocker.patch.object(creation, "get_current_user_info", return_value=_ACTOR)
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref",
                        return_value=SystemAgentRef("shared", "nl2skill_main", 78, 2))
    mocker.patch.object(creator_snapshot, "preflight_turn_controls")
    mocker.patch.object(creator_snapshot, "get_model_by_model_id", return_value={
        "model_id": 21, "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm",
        "display_name": "selected", "api_key": "private-model-key", "update_time": "v1",
    })
    mocker.patch.object(creator_snapshot, "_resolve_input_budget", return_value=(8192, {}, None))
    mocker.patch.object(creator_snapshot, "_resolve_context_budget", return_value=None)
    save = mocker.patch.object(creator_execution, "prepare_creation_history", return_value=(42, 1))

    async def upstream():
        yield 'data: {"type":"done","content":""}\n\n'

    async def persist(stream, **kwargs):
        assert kwargs == {"conversation_id": 42, "assistant_index": 1,
                          "user_id": "user-a", "tenant_id": "tenant-a"}
        async for event in stream:
            yield event

    dispatch = mocker.patch.object(creation, "create_nl2skill_stream", side_effect=lambda *args: upstream())
    mocker.patch.object(creator_execution, "persist_creation_stream", side_effect=persist)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=skill_app), base_url="http://management") as client:
        response = await client.post("/skills/nl2skill/run", json={
            "query": "Create", "model_id": 21, "model_parameter_preferences": {"21": {"temperature": 0.3}},
        })
    assert response.status_code == 200 and response.headers["conversation_id"] == "42"
    events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines()
              if line.startswith("data: ")]
    assert any(event["type"] == "done" for event in events)
    assert save.call_args.kwargs["agent_id"] == 78
    assert save.call_args.kwargs["selected_model_id"] == 21
    assert save.call_args.kwargs["model_parameter_preferences"] == {"21": {"temperature": 0.3}}
    payload, user, tenant = dispatch.call_args.args
    assert (user, tenant) == ("user-a", "tenant-a")
    assert payload.system_agent.agent_id == 78 and payload.system_agent.version_no == 2
    assert payload.model.conversation_parameters == {"temperature": 0.3}
    assert "private-model-key" not in payload.model_dump_json()
