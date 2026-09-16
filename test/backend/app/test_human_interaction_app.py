"""The runtime's internal HITL routes must preserve the signed owner scope."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from apps import human_interaction_app as api
from consts.exceptions import UnauthorizedError
from services.human_interaction.models import InteractionError

BASE = "/agent/internal/northbound/human-interactions"
RUN = "01a09fce-3a28-7860-8646-b0eec69d5f46"
CARD = "01a09fce-3a28-7860-8646-b0eec69d5f47"


@pytest.fixture
def boundary(monkeypatch):
    service = MagicMock()
    service.snapshot.return_value = {"run_id": RUN, "status": "WAITING_HUMAN"}
    service.repository.latest.return_value = RUN
    service.decide.return_value = {"accepted": True}
    service.control.return_value = {"run_id": RUN}
    service.steer.return_value = {"accepted": True}
    monkeypatch.setattr(api, "require_enabled", lambda: service)
    verify = MagicMock(return_value=("owner", "tenant-a"))
    monkeypatch.setattr("utils.auth_utils.verify_internal_runtime_jwt", verify)
    monkeypatch.setattr(api, "get_current_user_id", MagicMock(side_effect=AssertionError("Session auth used")))
    app = FastAPI()
    app.include_router(api.internal_router)
    return TestClient(app), service, verify


def test_snapshot_and_conversation_use_signed_tenant_and_user(boundary):
    client, service, verify = boundary
    response = client.get(BASE + "/conversation/7", headers={"Authorization": "Bearer internal-token"})
    assert response.status_code == 200
    verify.assert_called_once_with("Bearer internal-token")
    service.repository.latest.assert_called_once_with("tenant-a", "owner", 7)
    service.snapshot.assert_called_once_with(RUN, "tenant-a", "owner")


@pytest.mark.parametrize("path", ["/capabilities", f"/{RUN}", "/conversation/7", f"/{RUN}/events"])
def test_invalid_internal_token_is_rejected(boundary, path):
    client, service, verify = boundary
    verify.side_effect = UnauthorizedError("Invalid internal runtime token")
    assert client.get(BASE + path).status_code == 401
    service.snapshot.assert_not_called()


@pytest.mark.parametrize("status", [404, 409, 410, 422, 503])
def test_decision_preserves_lifecycle_errors_and_owner_scope(boundary, status):
    client, service, _ = boundary
    service.decide.side_effect = InteractionError("Rejected decision", status)
    response = client.post(BASE + f"/{RUN}/requests/{CARD}/decisions", json={
        "version": 1, "digest": "a" * 64, "idempotency_key": "decision-001", "decision": "approve",
    })
    assert response.status_code == status
    assert service.decide.call_args.args[:4] == (RUN, CARD, "tenant-a", "owner")


@pytest.mark.parametrize("action", ["pause", "terminate"])
def test_controls_are_owner_scoped(boundary, action):
    client, service, _ = boundary
    assert client.post(BASE + f"/{RUN}/{action}").status_code == 200
    service.control.assert_called_once_with(RUN, "tenant-a", "owner", action)


def test_steering_is_owner_scoped(boundary):
    client, service, _ = boundary
    assert client.post(BASE + f"/{RUN}/steer", json={"message_id": "guide-0001", "text": "Continue"}).status_code == 200
    assert service.steer.call_args.args[:3] == (RUN, "tenant-a", "owner")


def test_events_subscribe_with_signed_identity_and_cursor(boundary, monkeypatch):
    client, _, _ = boundary

    async def chunks():
        yield "id: 5\ndata: {}\n\n"

    stream = AsyncMock(return_value=StreamingResponse(chunks(), media_type="text/event-stream"))
    monkeypatch.setattr(api, "stream_run", stream)
    assert client.get(BASE + f"/{RUN}/events?after_event=4").status_code == 200
    stream.assert_awaited_once_with(RUN, "tenant-a", "owner", after=4)
