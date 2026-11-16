# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Grant, immutable invitation and locked actor policies with controlled persistence."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import DuplicateError, ForbiddenError, UnauthorizedError, ValidationError
from contracts.identity import (
    InvitationCreateRequest,
    InvitationUpdateRequest,
    UserUpdateRequest,
)
from management.services.permission.identity import invitations as service


@pytest.fixture
def invitation_state(mocker):
    actor = {"user_id": "admin", "tenant_id": "a", "roles": ["ADMIN"]}
    session = MagicMock()

    @contextmanager
    def db():
        yield session

    mocker.patch.object(service, "get_db_session", db)
    mocker.patch.object(service, "get_user_tenant_by_user_id", return_value=actor)
    mocker.patch.object(service, "lock_tenants")
    mocker.patch.object(service, "locked_members", side_effect=lambda session, ids: {"admin": actor})
    mocker.patch.object(service, "query_invitation_by_code", return_value=None)
    mocker.patch.object(service, "query_group_ids_by_user", return_value=[1])
    mocker.patch.object(service, "get_tenant_default_group_id", return_value=1)
    mocker.patch.object(service, "query_groups", return_value=[{"group_id": 1, "tenant_id": "a"}])
    add = mocker.patch.object(service, "add_invitation", return_value=100)
    return actor, session, add


@pytest.mark.parametrize("roles", [["ADMIN", "OPS"], ["DEV", "OPS"], ["OPS"], ["USER"]])
def test_admin_creates_fixed_ordinary_role_set(invitation_state, roles):
    actor, session, add = invitation_state
    result = service.create_invitation_code("a", roles=roles, invitation_code="owned", user_id="admin")
    assert set(result["roles"]) == set(roles)
    assert add.call_args.kwargs["db_session"] is session
    assert add.call_args.kwargs["roles"] == result["roles"]


@pytest.mark.parametrize("actor_roles,target", [(["OPS"], "a"), (["DEV"], "a"), (["ADMIN"], "b")])
def test_no_grants_outside_management_scope(invitation_state, actor_roles, target):
    actor, _, add = invitation_state
    actor["roles"] = actor_roles
    with pytest.raises(ForbiddenError):
        service.create_invitation_code(target, roles=["OPS"], group_ids=[], user_id="admin")
    add.assert_not_called()


def test_su_can_invite_into_other_tenant(invitation_state):
    actor, _, add = invitation_state
    actor["roles"] = ["SU"]
    result = service.create_invitation_code("b", roles=["OPS"], user_id="admin")
    assert result["group_ids"] == []
    assert add.call_args.kwargs["tenant_id"] == "b"


def test_actor_is_rechecked_after_transaction_lock(invitation_state, mocker):
    _, _, add = invitation_state
    mocker.patch.object(
        service, "locked_members", return_value={"admin": {"user_id": "admin", "tenant_id": "a", "roles": ["USER"]}}
    )
    with pytest.raises(ForbiddenError):
        service.create_invitation_code("a", roles=["ADMIN"], user_id="admin")
    add.assert_not_called()


def test_foreign_groups_are_rejected(invitation_state, mocker):
    _, _, add = invitation_state
    mocker.patch.object(service, "query_groups", return_value=[{"group_id": 1, "tenant_id": "b"}])
    with pytest.raises(ForbiddenError):
        service.create_invitation_code("a", roles=["OPS"], group_ids=[1], user_id="admin")
    add.assert_not_called()


@pytest.mark.parametrize("roles", [[], ["SU"], ["SPEED"], ["DEV", "ASSET_OWNER"]])
def test_invalid_roles_are_rejected_before_persistence(invitation_state, roles):
    _, _, add = invitation_state
    with pytest.raises(ValueError):
        service.create_invitation_code("a", roles=roles, user_id="admin")
    add.assert_not_called()


@pytest.mark.parametrize("value", [{"roles": ["OPS"]}, {"code_type": "ADMIN_INVITE"}])
def test_invitation_update_contract_rejects_role_mutation(value):
    with pytest.raises(ValueError, match="immutable"):
        InvitationUpdateRequest.model_validate(value)


def test_legacy_invitation_and_multirole_request_contracts():
    assert InvitationCreateRequest(tenant_id="a", code_type="USER_INVITE").code_type == "USER_INVITE"
    assert InvitationCreateRequest(tenant_id="a", roles=["OPS", "DEV", "OPS"]).roles == ["DEV", "OPS"]
    with pytest.raises(ValueError):
        UserUpdateRequest(role="DEV", roles=["OPS"])


def test_special_invites_retain_feature_gate(invitation_state, mocker):
    actor, _, add = invitation_state
    actor["roles"] = ["SU"]
    mocker.patch.object(
        service, "require_asset_owner_enabled", side_effect=ValidationError("ASSET_OWNER feature is not enabled")
    )
    with pytest.raises(ValidationError):
        service.create_invitation_code("a", code_type="ASSET_OWNER_INVITE", user_id="admin")
    add.assert_not_called()



def test_legacy_invite_preserves_role_and_uses_default_group(invitation_state, mocker):
    _, _, add = invitation_state
    mocker.patch.object(service, "get_tenant_default_group_id", return_value=None)

    result = service.create_invitation_code("a", "ADMIN_INVITE", "legacy", user_id="admin")

    assert (result["invitation_code"], result["code_type"], result["roles"], result["group_ids"]) == (
        "LEGACY", "ADMIN_INVITE", ["ADMIN"], [],
    )
    assert add.call_args.kwargs["roles"] == ["ADMIN"]


def test_legacy_type_cannot_conflict_with_explicit_grant(invitation_state):
    _, _, add = invitation_state

    with pytest.raises(ValueError, match="role and type conflict"):
        service.create_invitation_code("a", "ADMIN_INVITE", "legacy", roles=["OPS"], user_id="admin")

    add.assert_not_called()


@pytest.mark.parametrize("role", ["ADMIN", "SU"])
def test_asset_owner_invitation_keeps_legacy_platform_scope(invitation_state, mocker, role):
    actor, _, add = invitation_state
    actor["roles"] = [role]
    mocker.patch.object(service, "require_asset_owner_enabled")

    if role == "ADMIN":
        with pytest.raises(UnauthorizedError, match="platform administration"):
            service.create_invitation_code("a", "ASSET_OWNER_INVITE", "special", user_id="admin")
        add.assert_not_called()
    else:
        result = service.create_invitation_code("a", "ASSET_OWNER_INVITE", "special", group_ids=[1], user_id="admin")
        assert result["roles"] == ["ASSET_OWNER"]
        assert result["group_ids"] == []
        assert add.call_args.kwargs["tenant_id"] == ASSET_OWNER_TENANT_ID


def test_duplicate_invitation_code_never_reaches_insert(invitation_state):
    _, _, add = invitation_state
    service.query_invitation_by_code.return_value = {"invitation_id": 19}

    with pytest.raises(DuplicateError, match="already exists"):
        service.create_invitation_code("a", roles=["OPS"], invitation_code="used", user_id="admin")

    service.query_invitation_by_code.assert_called_once_with("USED")
    add.assert_not_called()
