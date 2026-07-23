from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps import memory_dreaming_app


def test_ac009_missing_agent_id_is_rejected():
    with pytest.raises(ValidationError):
        memory_dreaming_app.DreamingRunRequest()


def test_ac009_run_uses_authenticated_scope(monkeypatch):
    service = MagicMock()
    service.run.return_value = {"run_id": 1, "status": "completed"}
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-1", "tenant-1"),
    )
    result = memory_dreaming_app.run_dreaming(
        memory_dreaming_app.DreamingRunRequest(agent_id="agent-1"),
        authorization="Bearer token",
    )
    assert result["status"] == "completed"
    assert service.run.call_args.kwargs["tenant_id"] == "tenant-1"
    assert service.run.call_args.kwargs["user_id"] == "user-1"
    assert service.run.call_args.kwargs["agent_id"] == "agent-1"


def test_ac009_audit_uses_authenticated_scope(monkeypatch):
    service = MagicMock()
    service.list_audits.return_value = [{"run_id": 2}]
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-2", "tenant-2"),
    )
    result = memory_dreaming_app.list_dreaming_audits(
        authorization="Bearer token",
        agent_id="agent-2",
        run_id=2,
        limit=100,
    )
    assert result == [{"run_id": 2}]
    service.list_audits.assert_called_once_with(
        "tenant-2", "user-2", agent_id="agent-2", run_id=2, limit=100
    )


def test_ac008_service_failure_maps_to_500(monkeypatch):
    service = MagicMock()
    service.run.side_effect = memory_dreaming_app.DreamingRunError("failed")
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user", "tenant"),
    )
    request = memory_dreaming_app.DreamingRunRequest(agent_id="agent")
    with pytest.raises(HTTPException) as exc:
        memory_dreaming_app.run_dreaming(
            request,
            authorization=None,
        )
    assert exc.value.status_code == 500
    assert exc.value.detail == "failed"
