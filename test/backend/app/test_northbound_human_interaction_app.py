"""Contract tests for API-key authenticated HITL cards, controls and SSE replay."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

with pytest.MonkeyPatch.context() as import_mocks:
    import_mocks.setitem(sys.modules, "management.services.agent.service", MagicMock())
    from apps import northbound_human_interaction_app as api
from consts.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError

RUN = "01a09fce-3a28-7860-8646-b0eec69d5f46"
CARD = "01a09fce-3a28-7860-8646-b0eec69d5f47"
BASE = "/nb/v1/chat/human-interactions"
COMMAND = {
    "version": 1, "digest": "a" * 64, "idempotency_key": "reply-0001", "decision": "answer",
    "answers": [{"question_id": "audience", "value": "team", "other_text": None}],
}


@pytest.fixture
def boundary(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    ctx = api.NorthboundContext("trace-1", "tenant-a", "owner", "Bearer api-key")

    async def context():
        return ctx

    app.dependency_overrides[api._get_northbound_context] = context
    forward = AsyncMock(return_value={"run_id": RUN, "accepted": True})
    monkeypatch.setattr(api, "forward_human_interaction", forward)
    return TestClient(app), forward, app


@pytest.mark.parametrize("method,path,body,forwarded_path", [
    ("GET", "/capabilities", None, "capabilities"),
    ("GET", "/conversation/7", None, "conversation/7"),
    ("GET", f"/{RUN}", None, RUN),
    ("POST", f"/{RUN}/requests/{CARD}/decisions", COMMAND, f"{RUN}/requests/{CARD}/decisions"),
    ("POST", f"/{RUN}/pause", None, f"{RUN}/pause"),
    ("POST", f"/{RUN}/steer", {"message_id": "guide-0001", "text": "New direction"}, f"{RUN}/steer"),
    ("POST", f"/{RUN}/terminate", None, f"{RUN}/terminate"),
])
def test_controls_forward_only_resolved_identity(boundary, method, path, body, forwarded_path):
    client, forward, _ = boundary
    response = client.request(method, BASE + path, json=body, headers={"X-User-Id": "attacker"})
    assert response.status_code == 200
    assert response.json() == {
        "message": "success", "requestId": "trace-1", "data": {"run_id": RUN, "accepted": True},
    }
    args = forward.call_args
    assert args.args == (method, forwarded_path, "owner", "tenant-a")
    if body:
        assert all(args.kwargs["payload"][key] == value for key, value in body.items())
    else:
        assert args.kwargs["payload"] is None


def test_no_run_returns_null_snapshot(boundary):
    client, forward, _ = boundary
    forward.return_value = None
    assert client.get(BASE + "/conversation/7").json()["data"] is None


@pytest.mark.parametrize("status", [401, 403, 404, 409, 410, 422, 503])
def test_runtime_business_errors_are_preserved(boundary, status):
    client, forward, _ = boundary
    forward.side_effect = RuntimeUpstreamError(
        status_code=status, content=b'{"message":"runtime detail"}', headers={"content-type": "application/json"},
    )
    response = client.post(BASE + f"/{RUN}/requests/{CARD}/decisions", json=COMMAND)
    assert response.status_code == status
    assert response.json() == {"message": "runtime detail"}


@pytest.mark.parametrize("error,status", [
    (RuntimeServiceTimeoutError("timeout"), 504), (RuntimeServiceUnavailableError("unavailable"), 502),
])
def test_transport_errors_are_mapped(boundary, error, status):
    client, forward, _ = boundary
    forward.side_effect = error
    assert client.get(BASE + f"/{RUN}").status_code == status


@pytest.mark.parametrize("update", [
    {"tenant_id": "tenant-b"}, {"user_id": "someone-else"}, {"version": 0}, {"digest": "short"},
    {"decision": "execute"}, {"answers": [{"question_id": "audience", "value": "team", "code": "run()"}]},
])
def test_decisions_reject_untrusted_or_invalid_fields(boundary, update):
    client, forward, _ = boundary
    response = client.post(BASE + f"/{RUN}/requests/{CARD}/decisions", json={**COMMAND, **update})
    assert response.status_code == 422
    forward.assert_not_awaited()


def test_authentication_is_required_before_proxying(boundary):
    client, forward, app = boundary

    async def reject():
        raise HTTPException(status_code=401, detail="Invalid API key")

    app.dependency_overrides[api._get_northbound_context] = reject
    assert client.get(BASE + "/capabilities").status_code == 401
    forward.assert_not_awaited()


@pytest.mark.parametrize("query,headers,cursor", [
    ("", {}, 0), ("?after_event=7", {}, 7), ("", {"Last-Event-ID": "9"}, 9),
    ("?after_event=0", {"Last-Event-ID": "9"}, 0),
])
def test_event_subscription_preserves_cards_ids_and_headers(boundary, monkeypatch, query, headers, cursor):
    client, forward, _ = boundary
    chunk = b'id: 10\ndata: {"type":"human_interaction","content":{"kind":"CLARIFICATION"}}\n\n'

    async def stream():
        yield chunk

    events = AsyncMock(return_value=StreamingResponse(
        stream(), media_type="text/event-stream", headers={"run_id": RUN, "conversation_id": "7"},
    ))
    monkeypatch.setattr(api, "forward_human_interaction_events", events)
    response = client.get(BASE + f"/{RUN}/events" + query, headers=headers)
    assert response.content == chunk
    assert response.headers["run_id"] == RUN
    assert response.headers["conversation_id"] == "7"
    assert response.headers["x-accel-buffering"] == "no"
    events.assert_awaited_once_with(RUN, "owner", "tenant-a", after_event=cursor)
    forward.assert_not_awaited()


@pytest.mark.parametrize("query,headers", [
    ("?after_event=-1", {}), ("", {"Last-Event-ID": "-1"}), ("", {"Last-Event-ID": "invalid"}),
])
def test_invalid_event_cursor_does_not_reach_runtime(boundary, monkeypatch, query, headers):
    client, _, _ = boundary
    events = AsyncMock()
    monkeypatch.setattr(api, "forward_human_interaction_events", events)
    assert client.get(BASE + f"/{RUN}/events" + query, headers=headers).status_code == 422
    events.assert_not_awaited()


def test_uuid_paths_are_validated_before_forwarding(boundary):
    client, forward, _ = boundary
    assert client.get(BASE + "/not-a-run-id").status_code == 422
    forward.assert_not_awaited()
