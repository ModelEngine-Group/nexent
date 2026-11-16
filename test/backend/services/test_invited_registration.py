# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Registration revalidates invite state inside the account transaction."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from contracts.errors.exceptions import IncorrectInviteCodeException
from management.db.models import TenantInvitationCode
from management.services.permission.identity import registration


@pytest.fixture
def transaction(mocker):
    session = MagicMock()
    invite = TenantInvitationCode(
        invitation_id=42,
        tenant_id="a",
        roles=["DEV", "OPS"],
        code_type="TENANT_INVITE",
        group_ids="",
        status="IN_USE",
        capacity=1,
    )
    session.execute.return_value.scalar_one_or_none.return_value = invite
    events = []

    @contextmanager
    def database():
        events.append("begin")
        try:
            yield session
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    mocker.patch.object(registration, "get_db_session", database)
    mocker.patch.object(registration, "lock_tenants")
    mocker.patch.object(registration, "query_invitation_by_code", return_value={"tenant_id": "a"})
    mocker.patch.object(registration, "create_account", return_value={"user_id": "new", "email": "new@example.test"})
    mocker.patch.object(registration, "insert_user_tenant", return_value={"tenant_id": "a", "roles": ["DEV", "OPS"]})
    mocker.patch.object(registration, "add_user_to_group")
    return invite, session, events


def test_registering_final_member_marks_invitation_exhausted(transaction):
    invite, session, events = transaction
    session.scalar.side_effect = [0, 1]

    account, member = registration.register_invited_account("new@example.test", "encoded", " shared ")

    registration.query_invitation_by_code.assert_called_once_with("SHARED")
    registration.lock_tenants.assert_called_once_with(session, ["a"])
    assert account["user_id"] == "new"
    assert member["roles"] == ["DEV", "OPS"]
    assert events == ["begin", "commit"]
    assert invite.status == "RUN_OUT"
    assert session.add.call_args.args[0].invitation_id == invite.invitation_id


@pytest.mark.parametrize("failure", ["missing", "removed", "moved", "full"])
def test_unavailable_invitation_never_creates_account(transaction, failure):
    invite, session, events = transaction
    if failure == "missing":
        registration.query_invitation_by_code.return_value = None
    elif failure == "removed":
        session.execute.return_value.scalar_one_or_none.return_value = None
    elif failure == "moved":
        invite.tenant_id = "b"
    elif failure == "full":
        invite.status = "RUN_OUT"

    with pytest.raises(IncorrectInviteCodeException):
        registration.register_invited_account("new@example.test", "encoded", "SHARED")

    assert events == ([] if failure == "missing" else ["begin", "rollback"])
    registration.create_account.assert_not_called()
    registration.insert_user_tenant.assert_not_called()
    session.add.assert_not_called()


def test_deleted_invitation_group_rolls_back_membership_and_does_not_consume_code(transaction):
    invite, session, events = transaction
    invite.group_ids = "7"
    session.scalar.return_value = 0
    session.execute.return_value.scalar_one_or_none.side_effect = [invite, None]

    with pytest.raises(IncorrectInviteCodeException, match="group is no longer available"):
        registration.register_invited_account("new@example.test", "encoded", "SHARED")

    registration.insert_user_tenant.assert_called_once_with(
        "new", "a", "DEV", "new@example.test", db_session=session, roles=("DEV", "OPS"),
    )
    registration.add_user_to_group.assert_not_called()
    session.add.assert_not_called()
    session.flush.assert_not_called()
    assert events == ["begin", "rollback"]
    assert invite.status == "IN_USE"
