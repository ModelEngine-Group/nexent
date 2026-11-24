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
from backend.http.server.app_factory import create_app

IDENTITY = AuthenticatedIdentity("user-1", "tenant-1", kind=CredentialKind.API_KEY, token_id=42)


class _FakeRawBody:
    """Raw storage body double: records chunk read sizes and close."""

    def __init__(self, data=b"file-bytes"):
        self._data = data
        self._pos = 0
        self.read_sizes = []
        self.closed = False

    def read(self, amt=-1):
        self.read_sizes.append(amt)
        if amt is None or amt < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + amt]
            self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


@pytest.fixture()
def gate_client(monkeypatch):
    """A client over the real gate routers with the business lanes mocked."""
    import management.api.northbound_gates.automations as auto_gates
    import management.api.northbound_gates.conversations as conv_gates
    from management.services.file import access as file_access
    from management.services.file import service as file_service

    automation_facade = MagicMock()
    automation_facade.list_tasks.return_value = {"items": [], "total": 0}
    automation_facade.get_task.return_value = {"id": 1, "status": "paused"}
    monkeypatch.setattr(auto_gates, "agent_automation_facade", automation_facade)

    async def fake_delete(cid, uid, tenant_id=None):
        return True

    async def fake_batch_delete(ids, uid, tenant_id=None):
        return {"deleted_count": len(ids), "failed_ids": []}

    monkeypatch.setattr(conv_gates, "delete_conversation_service", fake_delete)
    monkeypatch.setattr(conv_gates, "delete_conversations_batch_service", fake_batch_delete)

    url_calls = []

    async def fake_url_impl(object_name, expires=86400, *, external=False):
        url_calls.append({"object_name": object_name, "expires": expires, "external": external})
        return {"object_name": object_name, "url": f"presigned://{object_name}"}

    fake_url_impl.calls = url_calls

    raw_bodies = []

    async def fake_raw_stream_impl(object_name):
        body = _FakeRawBody()
        raw_bodies.append(body)
        return body, "application/octet-stream"

    fake_raw_stream_impl.bodies = raw_bodies

    monkeypatch.setattr(file_access, "check_file_access", lambda name, uid, tid: True)
    monkeypatch.setattr(file_service, "get_file_url_impl", fake_url_impl)
    monkeypatch.setattr(file_service, "get_file_stream_raw_impl", fake_raw_stream_impl)
    # The ignore branch checks object existence before presigning; keep that
    # storage probe out of these behavioural tests.
    from management.db.file import attachment as file_attachment

    monkeypatch.setattr(
        file_attachment, "get_file_size_from_minio_strict", lambda name, bucket=None: 1024
    )

    audit_calls = []
    from management.services.monitor import audit as audit_mod
    from management.services.permission.identity import northbound as nb_ident

    monkeypatch.setattr(
        audit_mod, "record_security_event", lambda *a, **k: audit_calls.append((a, k))
    )
    monkeypatch.setattr(nb_ident, "submit_api_key_usage", lambda principal, request=None: None)

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
    # P1 regression: authenticated partner bytes must not enter shared caches.
    assert response.headers["cache-control"] == "private, no-store"


def test_denied_delete_still_records_audit(gate_client, monkeypatch):
    client, audit_calls = gate_client
    import management.api.northbound_gates.conversations as conv_gates
    from contracts.errors.exceptions import ForbiddenError

    async def deny(cid, uid, tenant_id=None):
        raise ForbiddenError("not yours")

    monkeypatch.setattr(conv_gates, "delete_conversation_service", deny)
    response = client.delete("/nb/v1/conversations/999")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "FORBIDDEN"
    assert body["requestId"]
    # The audit dependency already ran: the denied attempt is on record.
    assert audit_calls[0][1]["result"] == "denied"
    assert audit_calls[0][1]["details"]["target"] == {"conversation_id": 999}


def test_missing_conversation_delete_maps_to_404_not_500(gate_client, monkeypatch):
    """Regression: the gate must await the async service call.

    The gate previously called the async delete service without await, so the
    ownership miss raised inside a never-awaited coroutine and every
    conversation delete collapsed into an INTERNAL_ERROR 500 instead of the
    registered 404 translation. The async mock reproduces the real shape.
    """
    client, _ = gate_client
    import management.api.northbound_gates.conversations as conv_gates
    from contracts.errors.exceptions import ConversationNotFoundError

    async def missing(cid, uid, tenant_id=None):
        raise ConversationNotFoundError(f"Conversation {cid} does not exist")

    monkeypatch.setattr(conv_gates, "delete_conversation_service", missing)
    response = client.delete("/nb/v1/conversations/99999")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"


@pytest.mark.parametrize("expires", [0, -1, 604801])
def test_file_download_gate_rejects_out_of_range_expires(gate_client, expires):
    """Partner contract bounds URL validity to 1..604800 seconds (7 days)."""
    client, _ = gate_client
    response = client.get("/nb/v1/file/download/kb/x.pdf", params={"expires": expires})
    assert response.status_code == 422


def test_file_download_gate_accepts_expires_boundaries(gate_client):
    client, _ = gate_client
    for expires in (1, 604800):
        response = client.get("/nb/v1/file/download/kb/x.pdf", params={"expires": expires})
        assert response.status_code == 200


def test_batch_delete_gate_caps_id_count(gate_client):
    """The partner contract caps one batch at NB_BATCH_DELETE_MAX_IDS ids."""
    client, audit_calls = gate_client
    from management.api.northbound_gates.conversations import NB_BATCH_DELETE_MAX_IDS

    oversized = list(range(1, NB_BATCH_DELETE_MAX_IDS + 2))
    response = client.post("/nb/v1/conversations/batch-delete", json={"conversation_ids": oversized})
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert audit_calls[0][1]["result"] == "failed"

    at_limit = list(range(1, NB_BATCH_DELETE_MAX_IDS + 1))
    ok = client.post("/nb/v1/conversations/batch-delete", json={"conversation_ids": at_limit})
    assert ok.status_code == 200
    assert ok.json()["data"]["deleted_count"] == NB_BATCH_DELETE_MAX_IDS


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/nb/v1/conversations/0"),
    ("DELETE", "/nb/v1/conversations/-3"),
    ("GET", "/nb/v1/automations/0"),
    ("GET", "/nb/v1/automations/-1/runs"),
])
def test_gate_path_ids_must_be_positive(gate_client, method, path):
    client, _ = gate_client
    response = client.request(method, path)
    assert response.status_code == 422


def test_file_download_info_mode_opts_into_external_signing(gate_client):
    """Partner direct links must sign against the external authority.

    Regression for the P1 review finding: a global external switch broke the
    internal same-origin proxy; only the partner gate opts in, internal
    consumers keep the default internal authority.
    """
    client, _ = gate_client
    from management.services.file import service as file_service

    response = client.get("/nb/v1/file/download/kb/x.pdf")
    assert response.status_code == 200
    assert file_service.get_file_url_impl.calls[-1]["external"] is True


def test_file_download_stream_reads_in_chunks_and_closes_the_body(gate_client):
    """True streaming: bounded chunk reads, no full-object read, close on end."""
    client, _ = gate_client
    from management.services.file import service as file_service

    response = client.get("/nb/v1/file/download/reports/x.bin", params={"download": "stream"})
    assert response.status_code == 200
    assert response.content == b"file-bytes"
    body = file_service.get_file_stream_raw_impl.bodies[-1]
    assert body.closed is True
    # Every read is a bounded chunk request; never a full-object read(-1).
    assert body.read_sizes and all(size == 65536 for size in body.read_sizes)


def test_file_download_stream_splits_large_objects_into_chunks(gate_client, monkeypatch):
    client, _ = gate_client
    from management.services.file import service as file_service

    payload = b"x" * 150000  # > 2 chunks
    bodies = []

    async def big_raw_impl(object_name):
        body = _FakeRawBody(payload)
        bodies.append(body)
        return body, "application/octet-stream"

    monkeypatch.setattr(file_service, "get_file_stream_raw_impl", big_raw_impl)
    response = client.get("/nb/v1/file/download/reports/big.bin", params={"download": "stream"})
    assert response.status_code == 200
    assert response.content == payload
    body = bodies[-1]
    assert len(body.read_sizes) >= 3
    assert all(size == 65536 for size in body.read_sizes)
    assert body.closed is True


def test_file_download_stream_missing_object_maps_to_404(gate_client, monkeypatch):
    client, _ = gate_client
    from management.services.file import service as file_service
    from contracts.errors.exceptions import NotFoundException

    async def missing_impl(object_name):
        raise NotFoundException("Storage object does not exist")

    monkeypatch.setattr(file_service, "get_file_stream_raw_impl", missing_impl)
    response = client.get("/nb/v1/file/download/reports/gone.bin", params={"download": "stream"})
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_file_download_stream_closes_body_when_a_read_fails(gate_client, monkeypatch):
    client, _ = gate_client
    from management.services.file import service as file_service

    class _BrokenBody(_FakeRawBody):
        def read(self, amt=-1):
            super().read(amt)
            raise RuntimeError("storage connection reset")

    body_holder = []

    async def broken_impl(object_name):
        body = _BrokenBody()
        body_holder.append(body)
        return body, "application/octet-stream"

    monkeypatch.setattr(file_service, "get_file_stream_raw_impl", broken_impl)
    with pytest.raises(Exception):
        client.get("/nb/v1/file/download/reports/broken.bin", params={"download": "stream"})
    assert body_holder[0].closed is True
