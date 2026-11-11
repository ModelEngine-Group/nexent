# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Role mutation policy uses the locked actor and target, never request claims."""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from contracts.errors.exceptions import ForbiddenError, RoleAssignmentConflict
from management.db.identity import membership
from management.db.identity import roles as repository
from management.services.permission.identity import roles as service


@pytest.fixture
def state(mocker):
    members = {
        "actor": {"user_id": "actor", "tenant_id": "a", "roles": ["ADMIN"]},
        "target": {"user_id": "target", "tenant_id": "a", "roles": ["DEV"]},
    }

    @contextmanager
    def session():
        yield object()

    mocker.patch.object(service, "get_db_session", session)
    mocker.patch.object(service, "get_user_tenant_by_user_id", side_effect=lambda uid: deepcopy(members.get(uid)))
    mocker.patch.object(repository, "get_db_session", session)
    mocker.patch.object(repository, "get_user_tenant_by_user_id", side_effect=lambda uid: deepcopy(members.get(uid)))
    mocker.patch.object(repository, "lock_tenants")
    mocker.patch.object(repository, "locked_members", side_effect=lambda db, ids: deepcopy(members))
    mocker.patch.object(service, "api_only_account", return_value=False)
    mocker.patch.object(repository, "active_admin_count", return_value=2)
    mocker.patch.object(membership, "active_admin_count", return_value=2)
    mocker.patch.object(repository, "api_only_account", return_value=False)
    write = mocker.patch.object(
        repository,
        "write_roles",
        side_effect=lambda db, member, values, actor: members[member["user_id"]].update(roles=list(values)),
    )
    return members, write


@pytest.mark.parametrize("values", [["ADMIN", "OPS"], ["DEV", "OPS"], ["USER"], ["OPS"]])
def test_admin_can_grant_every_ordinary_set(state, values):
    members, write = state
    result = service.replace_roles("actor", "target", values)
    assert set(result["roles"]) == set(values)
    write.assert_called_once()


def test_admin_can_remove_another_admin(state):
    members, write = state
    members["target"]["roles"] = ["ADMIN"]
    assert service.replace_roles("actor", "target", ["USER"])["roles"] == ["USER"]


@pytest.mark.parametrize("special", ["SU", "ASSET_OWNER"])
def test_special_identity_is_immutable_even_for_su(state, special):
    members, write = state
    members["actor"]["roles"] = ["SU"]
    members["target"]["roles"] = [special]
    with pytest.raises(ForbiddenError):
        service.replace_roles("actor", "target", ["OPS"])
    write.assert_not_called()


def test_cross_tenant_requires_su(state):
    members, write = state
    members["target"]["tenant_id"] = "b"
    with pytest.raises(ForbiddenError):
        service.replace_roles("actor", "target", ["OPS"])
    write.assert_not_called()
    members["actor"]["roles"] = ["SU"]
    assert service.replace_roles("actor", "target", ["OPS"])["roles"] == ["OPS"]


def test_actor_revocation_during_wait_is_enforced(state, mocker):
    members, write = state
    locked = deepcopy(members)
    locked["actor"]["roles"] = ["USER"]
    mocker.patch.object(repository, "locked_members", return_value=locked)
    with pytest.raises(ForbiddenError):
        service.replace_roles("actor", "target", ["ADMIN"])
    write.assert_not_called()


@pytest.mark.parametrize("actor", ["actor", "target"])
def test_self_and_last_admin_protection(state, mocker, actor):
    members, write = state
    members["target"]["roles"] = ["ADMIN"]
    mocker.patch.object(membership, "active_admin_count", return_value=1)
    with pytest.raises(RoleAssignmentConflict):
        service.replace_roles(actor, "target", ["OPS"])
    write.assert_not_called()


def test_legacy_write_cannot_truncate_multirole(state):
    members, write = state
    members["target"]["roles"] = ["DEV", "OPS"]
    with pytest.raises(RoleAssignmentConflict):
        service.replace_roles("actor", "target", "USER", legacy=True)
    write.assert_not_called()


def test_api_only_roles_stay_restricted(state, mocker):
    _, write = state
    mocker.patch.object(repository, "api_only_account", return_value=True)
    with pytest.raises(ForbiddenError):
        service.replace_roles("actor", "target", ["USER", "OPS"])
    write.assert_not_called()


def test_api_only_assignable_roles_match_the_write_policy(state, mocker):
    mocker.patch.object(service, "api_only_account", return_value=True)
    result = service.assignable_roles("actor", "target")
    assert set(result["grantable_roles"]) == {"DEV", "USER"}
    assert set(result["revocable_roles"]) == {"DEV", "USER"}


@pytest.mark.parametrize("values", [[], ["SPEED"], ["SU"], ["DEV", "ASSET_OWNER"]])
def test_invalid_grant_has_no_write(state, values):
    _, write = state
    with pytest.raises(ValueError):
        service.replace_roles("actor", "target", values)
    write.assert_not_called()
