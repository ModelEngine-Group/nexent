# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Behavioural regressions for the phase-one northbound gates.

Exercises the five hand-written gates over mocked services: the northbound
envelope shape, the action-capability audit trail (success and denied), the
parameter lock on file download (redirect must not pass), the multi-segment
object name routing, and the stream pass-through exemption.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from management.utils.app_factory import create_app

IDENTITY = AuthenticatedIdentity("user-1", "tenant-1", kind=CredentialKind.API_KEY, token_id=42)


@pytest.fixture()
def gate_client(monkeypatch):
    """A client over the real gate routers with the business lanes mocked."""
    import management.api.northbound_gates.automations as auto_gates
    import management.api.northbound_gates.conversations as conv_gates
    from management.services.file import access as file_access
    from management.services.file import service as file_service

    auto_gates.agent_automation_facade = MagicMock()
    auto_gates.agent_automation_facade.list_tasks.return_value = {"items": [], "total": 0}
    auto_gates.agent_automation_facade.get_task.return_value = {"id": 1, "status": "paused"}

    conv_gates.delete_conversation_service = lambda cid, uid, tenant_id=None: None
    conv_gates.delete_conversations_batch_service = lambda ids, uid: {
        "deleted_count": len(ids),
        "failed_ids": [],
    }

    async def fake_url_impl(object_name, expires=86400):
        return {"object_name": object_name, "url": f"presigned://{object_name}"}

    async def fake_stream_impl(object_name):
        class _Stream:
            def __iter__(self):
                yield b"file-bytes"

        return _Stream(), "application/octet-stream"

    monkeypatch.setattr(file_access, "check_file_access", lambda name, uid, tid: True)
    monkeypatch.setattr(file_service, "get_file_url_impl", fake_url_impl)
    monkeypatch.setattr(file_service, "get_file_stream_impl", fake_stream_impl)

    audit_calls = []
    from management.services.monitor import audit as audit_mod
    from management.services.permission.identity import northbound as nb_ident

    monkeypatch.setattr(
        audit_mod, "record_security_event", lambda *a, **k: audit_calls.append((a, k))
    )
    monkeypatch.setattr(nb_ident, "record_api_key_usage", lambda principal, request=None: None)

    app = create_app(title="nb-gates", enable_monitoring=False)
    from management.api.northbound_gates import nb_capability_routers
    from management.services.permission.identity import dependency as dep

    for router in nb_capability_routers():
        app.include_router(router)
    app.dependency_overrides[dep.unified_identity] = lambda: IDENTITY
    return TestClient(app), audit_calls


def test_automation_query_gates_return_northbound_envelope(gate_client):
    client, _ = gate_client
    response = client.get("/nb/v1/automations")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["message"] == "success"
    assert body["requestId"]

    detail = client.get("/nb/v1/automations/5")
    assert detail.status_code == 200
    assert detail.json()["data"] == {"id": 1, "status": "paused"}


def test_conversation_delete_gate_envelopes_and_audits(gate_client):
    client, audit_calls = gate_client
    response = client.delete("/nb/v1/conversations/123")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["data"] is True

    assert len(audit_calls) == 1
    kwargs = audit_calls[0][1]
    assert kwargs["details"]["capability"] == "conversations.delete"
    assert kwargs["details"]["token_id"] == 42
    assert kwargs["details"]["target"] == {"conversation_id": 123}
    assert kwargs["result"] == "success"


def test_conversation_batch_delete_gate_audits_target_ids(gate_client):
    client, audit_calls = gate_client
    response = client.post("/nb/v1/conversations/batch-delete", json={"conversation_ids": [1, 2]})
    assert response.status_code == 200
    assert response.json()["data"] == {"deleted_count": 2, "failed_ids": []}
    assert audit_calls[0][1]["details"]["target"]["conversation_ids"] == [1, 2]


def test_file_download_gate_locks_redirect_and_base64(gate_client):
    client, _ = gate_client
    locked = client.get("/nb/v1/file/download/kb/x.pdf", params={"download": "redirect"})
    assert locked.status_code == 422  # pattern lock rejects on the signature

    locked_b64 = client.get("/nb/v1/file/download/kb/x.pdf", params={"download": "base64"})
    assert locked_b64.status_code == 422

    allowed = client.get("/nb/v1/file/download/kb/x.pdf")
    assert allowed.status_code == 200
    body = allowed.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["data"]["object_name"] == "kb/x.pdf"


def test_file_download_gate_accepts_multi_segment_object_names(gate_client):
    client, _ = gate_client
    response = client.get("/nb/v1/file/download/reports/2026/q3/summary.pdf")
    assert response.status_code == 200
    assert response.json()["data"]["object_name"] == "reports/2026/q3/summary.pdf"


def test_file_download_stream_mode_bypasses_the_envelope(gate_client):
    client, _ = gate_client
    response = client.get("/nb/v1/file/download/reports/x.bin", params={"download": "stream"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert "content-disposition" in response.headers
    # A stream response is never a JSON envelope.
    assert not response.headers["content-type"].startswith("application/json")


def test_denied_delete_still_records_audit(gate_client):
    client, audit_calls = gate_client
    import management.api.northbound_gates.conversations as conv_gates
    from contracts.errors.exceptions import ForbiddenError

    def deny(cid, uid, tenant_id=None):
        raise ForbiddenError("not yours")

    conv_gates.delete_conversation_service = deny
    response = client.delete("/nb/v1/conversations/999")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "FORBIDDEN"
    assert body["requestId"]
    # The audit dependency already ran: the denied attempt is on record.
    assert audit_calls[0][1]["result"] == "denied"
    assert audit_calls[0][1]["details"]["target"] == {"conversation_id": 999}
