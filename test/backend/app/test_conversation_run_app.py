# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from management.api.agent import conversation_run

RUN_ID = "a" * 32


@pytest.fixture
def app(mocker):
    mocker.patch.object(conversation_run, "get_current_user_id", return_value=("actor", "tenant"))
    application = FastAPI()
    application.include_router(conversation_run.router)
    return application


def stream():
    async def chunks():
        yield "data: done\n\n"
    return StreamingResponse(chunks(), media_type="text/event-stream", headers={"X-AgentOS-Run-ID": RUN_ID})


@pytest.mark.asyncio
async def test_public_run_relays_signed_request_context_and_existing_sse(app, mocker):
    forward = mocker.patch.object(conversation_run, "forward_conversation_run", return_value=stream())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post(
            "/agent/run?resume=true", json={"query": "question", "conversation_id": 42, "model_id": None},
            headers={"Cookie": "NEXT_LOCALE=en", "X-User-Timezone": "Asia/Shanghai"},
        )

    assert response.status_code == 200
    assert response.headers["X-AgentOS-Run-ID"] == RUN_ID
    assert response.text == "data: done\n\n"
    payload, user_id, tenant_id = forward.await_args.args
    assert (user_id, tenant_id) == ("actor", "tenant")
    assert payload.resume is True and payload.language == "en" and payload.timezone == "Asia/Shanghai"
    assert payload.request == {"query": "question", "conversation_id": 42, "model_id": None}


@pytest.mark.asyncio
async def test_public_resume_uses_cursor_operation_without_new_execution(app, mocker):
    run = mocker.patch.object(conversation_run, "forward_conversation_run")
    resume = mocker.patch.object(conversation_run, "forward_conversation_resume", return_value=stream())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post(
            "/agent/run", json={"query": "", "conversation_id": 42},
            params={"resume": True, "run_id": RUN_ID, "after_event_id": f"{RUN_ID}:1"},
        )

    assert response.status_code == 200
    payload, user_id, tenant_id = resume.await_args.args
    assert (payload.conversation_id, payload.run_id, payload.after_event_id) == (42, RUN_ID, f"{RUN_ID}:1")
    assert (user_id, tenant_id) == ("actor", "tenant")
    run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("params", "body"), [
    ({"run_id": RUN_ID}, {"conversation_id": 42}),
    ({"resume": True, "after_event_id": f"{RUN_ID}:1"}, {"conversation_id": 42}),
    ({"resume": True, "run_id": RUN_ID}, {"conversation_id": 42, "is_debug": True}),
    ({"resume": True, "run_id": RUN_ID}, {"conversation_id": 0}),
])
async def test_public_resume_rejects_invalid_combinations(app, mocker, params, body):
    run = mocker.patch.object(conversation_run, "forward_conversation_run")
    resume = mocker.patch.object(conversation_run, "forward_conversation_resume")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/agent/run", params=params, json={"query": "", **body})
    assert response.status_code == 422
    run.assert_not_called()
    resume.assert_not_called()


@pytest.mark.asyncio
async def test_public_run_forwards_idempotency_key_only_for_new_conversations(app, mocker):
    forward = mocker.patch.object(conversation_run, "forward_conversation_run", return_value=stream())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post(
            "/agent/run", json={"query": "question"}, headers={"Idempotency-Key": "client-123"},
        )
        assert response.status_code == 200
        assert forward.await_args.args[0].idempotency_key == "client-123"

        for target, body, key in (
            ("/agent/run?resume=true", {"query": "", "conversation_id": 42}, "client-123"),
            ("/agent/run", {"query": "question", "is_debug": True}, "client-123"),
            ("/agent/run", {"query": "question"}, "invalid key"),
        ):
            response = await client.post(target, json=body, headers={"Idempotency-Key": key})
            assert response.status_code == 422

    forward.assert_awaited_once()
