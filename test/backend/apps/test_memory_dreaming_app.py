from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps import memory_dreaming_app


def test_ac009_missing_agent_id_is_rejected():
    with pytest.raises(ValidationError):
        memory_dreaming_app.DreamingRunRequest()


def test_ac011_parameters_show_effective_read_only_configuration(monkeypatch):
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-1", "tenant-1"),
    )

    result = memory_dreaming_app.get_dreaming_parameters("Bearer token")

    assert result == {
        "source_limit": memory_dreaming_app.DREAMING_SOURCE_LIMIT,
        "long_term_max_chars": memory_dreaming_app.DREAMING_LONG_TERM_MAX_CHARS,
        "compression_max_attempts": (
            memory_dreaming_app.DREAMING_COMPRESSION_MAX_ATTEMPTS
        ),
    }


def test_ac009_run_uses_authenticated_scope(monkeypatch):
    create_audit = MagicMock(return_value=1)
    monkeypatch.setattr(
        memory_dreaming_app.memory_dreaming_db, "create_audit", create_audit
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
    assert result == {"run_id": 1, "status": "queued"}
    create_audit.assert_called_once_with(
        "tenant-1",
        "user-1",
        "agent-1",
        trigger_source="manual",
        status="queued",
    )


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
    monkeypatch.setattr(
        memory_dreaming_app.memory_dreaming_db,
        "create_audit",
        MagicMock(side_effect=memory_dreaming_app.DreamingRunError("failed")),
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


def test_ac026_version_history_and_switch_use_authenticated_scope(monkeypatch):
    service = MagicMock()
    service.list_versions.return_value = [{"version_id": 2, "is_active": True}]
    service.activate_version.return_value = {"version_id": 1, "is_active": True}
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-1", "tenant-1"),
    )

    versions = memory_dreaming_app.list_dreaming_versions(
        agent_id="agent-1", authorization="Bearer token", limit=20
    )
    switched = memory_dreaming_app.activate_dreaming_version(
        1,
        memory_dreaming_app.DreamingVersionSwitchRequest(
            agent_id="agent-1", expected_active_version_id=2
        ),
        authorization="Bearer token",
    )

    assert versions[0]["version_id"] == 2
    assert switched["version_id"] == 1
    service.list_versions.assert_called_once_with(
        "tenant-1", "user-1", agent_id="agent-1", limit=20
    )
    service.activate_version.assert_called_once_with(
        "tenant-1",
        "user-1",
        agent_id="agent-1",
        version_id=1,
        actor_user_id="user-1",
        expected_active_version_id=2,
    )


def test_ac026_switch_rejects_out_of_scope_version(monkeypatch):
    service = MagicMock()
    service.activate_version.return_value = None
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-1", "tenant-1"),
    )
    with pytest.raises(HTTPException) as exc:
        memory_dreaming_app.activate_dreaming_version(
            999,
            memory_dreaming_app.DreamingVersionSwitchRequest(
                agent_id="agent-1", expected_active_version_id=2
            ),
            authorization="Bearer token",
        )
    assert exc.value.status_code == 404


def test_ac015_regular_user_cannot_target_another_user(monkeypatch):
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("caller", "tenant-1"),
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "USER", "tenant_id": "tenant-1"},
    )
    monkeypatch.setattr(
        memory_dreaming_app, "check_role_permission", lambda *_args, **_kwargs: False
    )
    with pytest.raises(HTTPException) as exc:
        memory_dreaming_app.list_dreaming_versions(
            agent_id="agent-1",
            authorization="Bearer token",
            target_user_id="other",
        )
    assert exc.value.status_code == 404


def test_ac016_admin_can_target_same_tenant_only(monkeypatch):
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("admin", "tenant-1"),
    )

    def lookup(user_id):
        return {
            "admin": {"user_role": "ADMIN", "tenant_id": "tenant-1"},
            "same": {"user_role": "USER", "tenant_id": "tenant-1"},
            "cross": {"user_role": "USER", "tenant_id": "tenant-2"},
        }[user_id]

    monkeypatch.setattr(memory_dreaming_app, "get_user_tenant_by_user_id", lookup)
    monkeypatch.setattr(
        memory_dreaming_app, "check_role_permission", lambda *_args, **_kwargs: True
    )
    service = MagicMock()
    service.list_versions.return_value = []
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    memory_dreaming_app.list_dreaming_versions(
        agent_id="agent-1",
        authorization="Bearer token",
        target_user_id="same",
    )
    service.list_versions.assert_called_once_with(
        "tenant-1", "same", agent_id="agent-1", limit=100
    )
    with pytest.raises(HTTPException) as exc:
        memory_dreaming_app.list_dreaming_versions(
            agent_id="agent-1",
            authorization="Bearer token",
            target_user_id="cross",
        )
    assert exc.value.status_code == 404


def test_ac016_admin_without_tenant_capability_is_denied(monkeypatch):
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("admin", "tenant-1"),
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_user_tenant_by_user_id",
        lambda user_id: {
            "user_role": "ADMIN" if user_id == "admin" else "USER",
            "tenant_id": "tenant-1",
        },
    )
    check = MagicMock(return_value=False)
    monkeypatch.setattr(memory_dreaming_app, "check_role_permission", check)

    with pytest.raises(HTTPException) as exc:
        memory_dreaming_app.list_dreaming_versions(
            agent_id="agent-1",
            authorization="Bearer token",
            target_user_id="same",
        )

    assert exc.value.status_code == 404
    check.assert_called_once_with(
        "ADMIN",
        permission_category="RESOURCE",
        permission_type="DREAMING",
        permission_subtype="VIEW_TENANT",
    )
