# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Invitation edits and usage enforce the locked tenant, grant, and capacity."""

from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from contracts.errors.exceptions import (
    ForbiddenError,
    IncorrectInviteCodeException,
    NotFoundException,
    UnauthorizedError,
)
from management.db.models import TenantInvitationCode, TenantInvitationRecord
from management.services.permission.identity import invitations, registration


@pytest.fixture
def invitation(mocker):
    actor = {"user_id": "actor", "tenant_id": "a", "user_roles": ["ADMIN", "OPS"]}
    row = TenantInvitationCode(
        invitation_id=42,
        tenant_id="a",
        invitation_code="SHARED",
        code_type="TENANT_INVITE",
        roles=["DEV", "OPS"],
        status="IN_USE",
        capacity=2,
        group_ids="7,8",
    )
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = row
    session.scalar.return_value = 1
    snapshot = {"invitation_id": 42, "tenant_id": "a", "code_type": "TENANT_INVITE"}
    mocker.patch.object(invitations, "get_db_session", side_effect=lambda: nullcontext(session))
    mocker.patch.object(invitations, "get_user_tenant_by_user_id", return_value=actor)
    mocker.patch.object(invitations, "query_invitation_by_id", return_value=snapshot)
    mocker.patch.object(invitations, "query_invitation_by_code", return_value=snapshot)
    mocker.patch.object(invitations, "lock_tenants")
    mocker.patch.object(registration, "lock_tenants")
    mocker.patch.object(invitations, "locked_members", return_value={"actor": actor})
    return row, session, actor


@pytest.mark.parametrize(
    "initial,expiry,usage,expected",
    [
        ("DISABLE", None, 0, "DISABLE"),
        ("IN_USE", -1, 2, "EXPIRE"),
        ("IN_USE", 0, 2, "RUN_OUT"),
        ("RUN_OUT", 1, 1, "IN_USE"),
    ],
)
def test_metadata_edit_recomputes_status_without_changing_roles(invitation, mocker, initial, expiry, usage, expected):
    row, session, _ = invitation
    row.status = initial
    now = datetime(2030, 5, 15)
    mocker.patch.object(invitations, "datetime").utcnow.return_value = now
    row.expiry_date = now + timedelta(days=expiry) if expiry is not None else None
    session.scalar.return_value = usage
    mocker.patch.object(invitations, "query_groups", return_value={"group_id": 7, "tenant_id": "a"})
    modify = mocker.patch.object(invitations, "modify_invitation", return_value=True)
    updates = {"capacity": 2, "group_ids": [7]}

    assert invitations.update_invitation_code(42, updates, "actor") is True

    modify.assert_called_once_with(42, updates, "actor", db_session=session)
    session.expire.assert_called_once_with(row)
    assert row.status == expected
    assert row.roles == ["DEV", "OPS"]


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize(
    "failure,error",
    [
        ("actor_missing", UnauthorizedError),
        ("invitation_missing", NotFoundException),
        ("foreign_tenant", ForbiddenError),
        ("ops_only", UnauthorizedError),
        ("special_invitation", UnauthorizedError),
        ("actor_revoked", ForbiddenError),
        ("invitation_removed", NotFoundException),
    ],
)
def test_management_denial_cannot_write(invitation, mocker, operation, failure, error):
    _, session, actor = invitation
    snapshot = invitations.query_invitation_by_id.return_value
    if failure == "actor_missing":
        invitations.get_user_tenant_by_user_id.return_value = None
    elif failure == "invitation_missing":
        invitations.query_invitation_by_id.return_value = None
    elif failure == "foreign_tenant":
        snapshot["tenant_id"] = "other"
    elif failure == "ops_only":
        actor["user_roles"] = ["OPS"]
    elif failure == "special_invitation":
        snapshot["code_type"] = "ASSET_OWNER_INVITE"
    elif failure == "actor_revoked":
        invitations.locked_members.return_value = {}
    elif failure == "invitation_removed":
        session.execute.return_value.scalar_one_or_none.return_value = None
    modify = mocker.patch.object(invitations, "modify_invitation")
    remove = mocker.patch.object(invitations, "remove_invitation")

    with pytest.raises(error):
        if operation == "update":
            invitations.update_invitation_code(42, {"capacity": 3}, "actor")
        else:
            invitations.delete_invitation_code(42, "actor")

    modify.assert_not_called()
    remove.assert_not_called()


@pytest.mark.parametrize("field,value,error", [
    ("roles", ["OPS"], ValueError),
    ("code_type", "USER_INVITE", ValueError),
    ("group_ids", [9], ForbiddenError),
])
def test_edit_rejects_grant_changes_and_groups_from_another_tenant(invitation, mocker, field, value, error):
    _, session, _ = invitation
    mocker.patch.object(invitations, "query_groups", return_value=[{"group_id": 9, "tenant_id": "other"}])
    modify = mocker.patch.object(invitations, "modify_invitation")

    with pytest.raises(error):
        invitations.update_invitation_code(42, {field: value}, "actor")

    modify.assert_not_called()
    session.execute.assert_not_called()


def test_super_admin_can_delete_another_tenants_invitation(invitation, mocker):
    row, session, actor = invitation
    actor.update(tenant_id="platform", user_roles=["SU"])
    remove = mocker.patch.object(invitations, "remove_invitation", return_value=True)

    assert invitations.delete_invitation_code(row.invitation_id, "actor") is True

    invitations.lock_tenants.assert_called_once_with(session, ["a", "platform"])
    remove.assert_called_once_with(row.invitation_id, "actor", db_session=session)


@pytest.mark.parametrize("already_recorded", [False, True])
def test_usage_records_matching_member_once_even_on_retry(invitation, already_recorded):
    row, session, _ = invitation
    member = {"tenant_id": "a", "user_roles": ["DEV", "OPS"]}
    invitations.locked_members.return_value = {"member": member}
    record = TenantInvitationRecord(invitation_record_id=13) if already_recorded else None
    session.execute.return_value.scalar_one_or_none.side_effect = [row, record]
    if already_recorded:
        row.status = "RUN_OUT"
    else:
        session.scalar.side_effect = [1, 2]

        def assign_record_id():
            session.add.call_args.args[0].invitation_record_id = 13

        session.flush.side_effect = assign_record_id

    result = invitations.use_invitation_code(" shared ", "member")

    invitations.query_invitation_by_code.assert_called_once_with("SHARED")
    assert result == {
        "invitation_record_id": 13,
        "invitation_code": "SHARED",
        "user_id": "member",
        "invitation_id": 42,
        "code_type": "TENANT_INVITE",
        "roles": ["DEV", "OPS"],
        "group_ids": [7, 8],
    }
    assert row.status == "RUN_OUT"
    if already_recorded:
        session.add.assert_not_called()
        session.flush.assert_not_called()
    else:
        session.add.assert_called_once()
        added = session.add.call_args.args[0]
        assert (added.invitation_id, added.user_id, added.delete_flag) == (42, "member", "N")
        session.flush.assert_called_once()


@pytest.mark.parametrize("member", [
    None,
    {"tenant_id": "other", "user_roles": ["DEV", "OPS"]},
    {"tenant_id": "a", "user_roles": ["DEV"]},
])
def test_usage_denies_nonmatching_membership(invitation, member):
    _, session, _ = invitation
    invitations.locked_members.return_value = {"member": member}

    with pytest.raises(ForbiddenError, match="matching registered membership"):
        invitations.use_invitation_code("SHARED", "member")

    session.add.assert_not_called()


@pytest.mark.parametrize(
    "failure,error",
    [
        ("missing", NotFoundException),
        ("disabled", IncorrectInviteCodeException),
        ("expired", IncorrectInviteCodeException),
        ("exhausted", IncorrectInviteCodeException),
    ],
)
def test_unavailable_invitation_does_not_record_new_usage(invitation, failure, error):
    row, session, _ = invitation
    invitations.locked_members.return_value = {"member": {"tenant_id": "a", "user_roles": ["DEV", "OPS"]}}
    session.execute.return_value.scalar_one_or_none.side_effect = [row, None]
    if failure == "missing":
        invitations.query_invitation_by_code.return_value = None
    elif failure == "disabled":
        row.status = "DISABLE"
    elif failure == "expired":
        row.expiry_date = datetime.utcnow() - timedelta(days=1)
    elif failure == "exhausted":
        session.scalar.return_value = row.capacity

    with pytest.raises(error):
        invitations.use_invitation_code("SHARED", "member")

    session.add.assert_not_called()
