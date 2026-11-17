# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP/SSE creator contract with real routes and lifecycle, controlled storage/provider."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI

CASE_ID = "WB-SESSION-RECOVERY-D2-001"


async def http(app, path, body=None, disconnect_after=None):
    parsed = urlsplit(path)
    disconnected = asyncio.Event()
    request_sent = False
    messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": json.dumps(body).encode(),
                "more_body": False,
            }
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if disconnect_after and disconnect_after in message.get("body", b""):
            disconnected.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST" if body is not None else "GET",
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode(),
        "root_path": "",
        "query_string": parsed.query.encode(),
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return (
        start["status"],
        b"".join(m.get("body", b"") for m in messages),
        dict(start["headers"]),
    )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
async def test_creator_http_reconnect_ownership_and_retry(monkeypatch, kind):
    from contracts.agent import SystemAgentRef
    from management.services.conversation import (
        creation_history,
        creator_checkpoints,
        creator_runtime,
    )
    from management.services.conversation import (
        creator_execution as executor,
    )
    from runtime.api.agent import execution as agent_api
    from runtime.api.skill import creation as skill_api

    rows = []
    gate = asyncio.Event()
    runs = []
    target = {"type": kind, "id": 42}

    def history(*_):
        return {
            "agent_id": 77,
            "target": target,
            "message_records": copy.deepcopy(rows),
        }

    def save(request, **kwargs):
        mid = len(rows) + 1
        rows.append(
            {
                "message_id": mid,
                "role": request.role,
                "message_index": request.message_idx,
                "message_content": request.message[0].content
                if request.message
                else "",
                "status": kwargs.get("status", "completed"),
                "units": [],
            }
        )
        return mid

    def checkpoint(mid, cid, user, units, content, status):
        row = next(r for r in rows if r["message_id"] == mid)
        assert row["status"] == "streaming"
        row["units"].extend(copy.deepcopy(units))
        row.update(status=status, message_content=content)

    def authorize(value, *_):
        if value != target:
            raise PermissionError("Target is not editable")
        return value

    async def provider(**kwargs):
        runs.append(kwargs)

        async def output():
            yield 'data: {"type":"final_answer","content":"first"}\n\n'
            await gate.wait()
            if len(runs) == 1:
                yield 'data: {"type":"error","content":"controlled failure"}\n\n'
            else:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "nl2a",
                            "content": json.dumps(
                                {
                                    "subtype": "requirement_clarification",
                                    "agent_id": 42,
                                    "questions": [
                                        {
                                            "question_id": "next",
                                            "question_type": "text",
                                            "title": "Next requirement?",
                                            "required": True,
                                            "options": [],
                                            "allow_other": False,
                                            "other_input_expanded": False,
                                        }
                                    ],
                                }
                            ),
                        }
                    )
                    + "\n\n"
                )

        return output()

    monkeypatch.setattr(
        executor.system_agent_provider,
        "get_creator_ref",
        lambda *_: SystemAgentRef("shared", f"nl2{kind}_main", 77, 0),
    )
    monkeypatch.setattr(executor, "authorize_target", authorize)
    for module in [executor, creation_history, creator_runtime]:
        monkeypatch.setattr(module, "get_conversation_history", history)
    monkeypatch.setattr(
        creation_history, "create_new_conversation", lambda **_: {"conversation_id": 91}
    )
    monkeypatch.setattr(creation_history, "save_message", save)
    monkeypatch.setattr(executor, "save_message", save)
    monkeypatch.setattr(creator_checkpoints, "checkpoint_creator_message", checkpoint)
    monkeypatch.setattr(
        creator_runtime,
        "get_message_units",
        lambda mid: copy.deepcopy(
            next(r["units"] for r in rows if r["message_id"] == mid)
        ),
    )
    monkeypatch.setattr(
        "management.services.conversation.model_preferences.read_model_preferences",
        lambda *_: {"model_parameter_preferences": {}, "selected_model_id": None},
    )
    state = SimpleNamespace(
        enabled=False,
        claim_creator_run_async=AsyncMock(return_value=True),
        creator_lease_async=AsyncMock(return_value=True),
        is_cancelled_async=AsyncMock(return_value=False),
        get_run_state_async=AsyncMock(return_value={}),
        mark_stream_completed_async=AsyncMock(),
    )
    monkeypatch.setattr(executor, "runtime_state_service", state)
    monkeypatch.setattr(creator_runtime, "runtime_state_service", state)
    creator_runtime._request_claims.clear()
    for api in [agent_api, skill_api]:
        monkeypatch.setattr(api, "ENABLE_AGENT_WORKBENCH", True)
        monkeypatch.setattr(
            api,
            "get_current_user_info",
            lambda *_: ("formal-creator-user", "tenant", "en"),
        )
    monkeypatch.setattr(agent_api, "create_nl2agent_stream", provider)
    monkeypatch.setattr(
        agent_api, "get_current_user_id", lambda *_: ("formal-creator-user", "tenant")
    )
    monkeypatch.setattr(skill_api, "create_nl2skill_stream", provider)
    app = FastAPI()
    app.include_router(agent_api.agent_runtime_router)
    app.include_router(skill_api.skill_creator_router)
    app.dependency_overrides[agent_api.require_agent_create_permission] = lambda: (
        object()
    )
    app.dependency_overrides[skill_api.require_skill_create_permission] = lambda: (
        object()
    )
    path = "/agent/nl2agent/run" if kind == "agent" else "/skills/nl2skill/run"
    request = {"query": "build", "target": target, "request_id": f"{kind}-first"}
    try:
        status, output, headers = await http(
            app, path, request, disconnect_after=b"first"
        )
        assert status == 200 and b"first" in output
        assert headers[b"conversation_id"] == b"91" and headers[b"run_id"]
        assert rows[-1]["status"] == "streaming" and creator_runtime._producers
        resumed_status, resumed_output, resumed_headers = await http(
            app,
            path + "?resume=true",
            {**request, "conversation_id": 91},
            disconnect_after=b"first",
        )
        assert resumed_status == 200 and b"first" in resumed_output
        assert resumed_headers[b"run_id"] == headers[b"run_id"] and len(runs) == 1
        concurrent, _, _ = await http(
            app,
            path,
            {**request, "conversation_id": 91, "request_id": f"{kind}-duplicate"},
        )
        assert concurrent == 409 and len(runs) == 1 and len(rows) == 2
        denied, _, _ = await http(
            app,
            path + "?resume=true",
            {**request, "conversation_id": 91, "target": {"type": kind, "id": 99}},
        )
        assert denied in {400, 403} and len(runs) == 1
        gate.set()
        await asyncio.wait_for(asyncio.gather(*creator_runtime._producers), timeout=2)
        assert rows[-1]["status"] == "failed"
        status, output, _ = await http(
            app, path + "?resume=true", {**request, "conversation_id": 91}
        )
        assert status == 200 and b"controlled failure" in output and len(runs) == 1
        gate.clear()
        status, output, retry_headers = await http(
            app,
            path,
            {
                **request,
                "conversation_id": 91,
                "request_id": f"{kind}-retry",
                "retry_message_index": 0,
                "retry_user_message_id": 1,
            },
            disconnect_after=b"first",
        )
        assert status == 200 and rows[-1]["status"] == "streaming"
        # An old tab's stop must not cancel a newly accepted retry.
        await http(app, "/agent/stop/91?generation=" + headers[b"run_id"].decode())
        current = creator_runtime.agent_run_manager.get_agent_run_info(
            91, "formal-creator-user"
        )
        assert current is not None and not current.stop_event.is_set()
        await http(
            app, "/agent/stop/91?generation=" + retry_headers[b"run_id"].decode()
        )
        await asyncio.wait_for(asyncio.gather(*creator_runtime._producers), timeout=2)
        assert rows[-1]["status"] == "stopped"
        gate.set()
        status, output, _ = await http(
            app,
            path,
            {
                **request,
                "conversation_id": 91,
                "request_id": f"{kind}-retry-after-stop",
                "retry_message_index": 0,
                "retry_user_message_id": 1,
            },
        )
        assert status == 200 and b"nl2a" in output
        assert rows[-1]["status"] == "completed" and rows[-1]["message_index"] == 1
        assert len([r for r in rows if r["role"] == "user"]) == 1
        assert len(runs) == 3
    finally:
        gate.set()
        await creator_runtime.shutdown_creator_streams(2)
        assert not creator_runtime._producers
