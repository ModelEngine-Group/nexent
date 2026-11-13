# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Role administration routes preserve actor scope and domain error responses."""

from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.errors.exceptions import ForbiddenError, NotFoundException, RoleAssignmentConflict, UnauthorizedError
from management.api.identity import invitation, user


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(user.router)
    app.include_router(invitation.router)
    with TestClient(app, headers={"Authorization": "Bearer test-session"}) as http:
        yield http


def test_assignable_roles_uses_authenticated_actor_and_target(client, mocker):
    auth = mocker.patch.object(user, "get_current_user_id", return_value=("actor", "tenant"))
    choices = {
        "grantable_roles": ["ADMIN", "OPS"],
        "revocable_roles": ["OPS"],
        "locked_roles": ["ADMIN"],
        "reasons": {"ADMIN": "Cannot remove your own ADMIN role"},
    }
    options = mocker.patch.object(user, "assignable_roles", return_value=choices)

    response = client.get("/users/actor/assignable_roles")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"data": choices}
    auth.assert_called_once_with("Bearer test-session")
    options.assert_called_once_with("actor", "actor")


@pytest.mark.parametrize(
    "error,status",
    [
        (UnauthorizedError("Sign in required"), HTTPStatus.UNAUTHORIZED),
        (ForbiddenError("Tenant scope denied"), HTTPStatus.FORBIDDEN),
        (NotFoundException("User not found"), HTTPStatus.NOT_FOUND),
    ],
)
def test_assignable_role_failures_preserve_domain_status(client, mocker, error, status):
    auth = mocker.patch.object(user, "get_current_user_id", return_value=("actor", "tenant"))
    options = mocker.patch.object(user, "assignable_roles")
    if status == HTTPStatus.UNAUTHORIZED:
        auth.side_effect = error
    else:
        options.side_effect = error

    response = client.get("/users/target/assignable_roles")

    assert response.status_code == status
    assert response.json() == {"detail": str(error)}
    if status == HTTPStatus.UNAUTHORIZED:
        options.assert_not_called()


@pytest.mark.parametrize("target", ["actor", "foreign", "platform", "unavailable"])
def test_managed_delete_denial_never_calls_cleanup(client, mocker, target):
    users = {
        "actor": {"user_id": "actor", "tenant_id": "a", "user_roles": ["ADMIN", "OPS"]},
        "foreign": {"user_id": "foreign", "tenant_id": "b", "user_roles": ["USER"]},
        "platform": {"user_id": "platform", "tenant_id": "a", "user_roles": ["SU"]},
        "unavailable": {"user_id": "unavailable", "tenant_id": "a", "user_roles": ["USER"]},
    }
    actor_id = "deleted-actor" if target == "unavailable" else "actor"
    mocker.patch.object(user, "get_current_user_id", return_value=(actor_id, "a"))
    mocker.patch.object(user, "get_user_tenant_by_user_id", side_effect=users.get)
    cleanup = mocker.patch.object(user, "delete_user_and_cleanup")

    response = client.delete(f"/users/{target}")

    assert response.status_code == {
        "actor": HTTPStatus.CONFLICT,
        "foreign": HTTPStatus.FORBIDDEN,
        "platform": HTTPStatus.FORBIDDEN,
        "unavailable": HTTPStatus.UNAUTHORIZED,
    }[target]
    cleanup.assert_not_awaited()


def test_role_update_conflict_preserves_status_without_success_audit(client, mocker):
    mocker.patch.object(user, "get_current_user_context", return_value=("actor", "a", ("ADMIN", "OPS")))
    update = mocker.patch.object(
        user, "update_user_for_requester", side_effect=RoleAssignmentConflict("Last administrator")
    )
    audit = mocker.patch.object(user, "record_security_event")

    response = client.put("/users/target", json={"roles": ["OPS", "USER", "OPS"]})

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json() == {"detail": "Last administrator"}
    update.assert_awaited_once_with(
        "target", {"roles": ["USER", "OPS"]},
        updated_by="actor", requester_tenant_id="a", requester_role=("ADMIN", "OPS"),
    )
    audit.assert_not_called()


@pytest.mark.parametrize("method,path,body,service_name", [
    ("POST", "/invitations/list", {"tenant_id": "b"}, "get_invitations_list"),
    ("POST", "/invitations", {"tenant_id": "b", "roles": ["OPS"]}, "create_invitation_code"),
    ("PUT", "/invitations/CODE", {"capacity": 2}, "update_invitation_code"),
    ("DELETE", "/invitations/CODE", None, "delete_invitation_code"),
])
def test_invitation_cross_tenant_denial_keeps_403(client, mocker, method, path, body, service_name):
    mocker.patch.object(invitation, "get_current_user_id", return_value=("actor", "a"))
    mocker.patch.object(invitation, "get_invitation_by_code", return_value={"invitation_id": 42})
    service = mocker.patch.object(invitation, service_name, side_effect=ForbiddenError("Tenant scope denied"))
    audit = mocker.patch.object(invitation, "record_security_event")

    response = client.request(method, path, json=body)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json() == {"detail": "Tenant scope denied"}
    service.assert_called_once()
    audit.assert_not_called()
