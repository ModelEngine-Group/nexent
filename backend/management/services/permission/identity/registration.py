# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Invitation-backed local identity creation with one membership transaction."""

from datetime import datetime

from sqlalchemy import func, select

from contracts.errors.exceptions import IncorrectInviteCodeException
from contracts.roles import invitation_roles, primary_role
from management.db.client import get_db_session
from management.db.identity.account import create_account
from management.db.identity.group import add_user_to_group
from management.db.identity.invitation import query_invitation_by_code
from management.db.identity.roles import lock_tenants
from management.db.identity.user_tenant import insert_user_tenant
from management.db.models import (
    TenantGroupInfo,
    TenantInvitationCode,
    TenantInvitationRecord,
)
from management.utils.orm import as_dict
from management.utils.serialization import convert_string_to_list


def locked_invitation(session, code, snapshot):
    """Do not recheck the issuer: valid invitations survive issuer revocation."""
    lock_tenants(session, [snapshot["tenant_id"]])
    row = session.execute(
        select(TenantInvitationCode)
        .where(TenantInvitationCode.invitation_code == code, TenantInvitationCode.delete_flag == "N")
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.tenant_id != snapshot["tenant_id"]:
        raise IncorrectInviteCodeException("Invitation is unavailable")
    if row.status not in {"IN_USE", "RUN_OUT"} or (
        row.expiry_date and row.expiry_date.date() < datetime.utcnow().date()
    ):
        raise IncorrectInviteCodeException("Invitation is unavailable")
    return row


def invitation_usage(session, invitation_id):
    return session.scalar(
        select(func.count())
        .select_from(TenantInvitationRecord)
        .where(TenantInvitationRecord.invitation_id == invitation_id, TenantInvitationRecord.delete_flag == "N")
    )


def register_invited_account(email, encoded_password, code):
    code = code.strip().upper()
    snapshot = query_invitation_by_code(code)
    if not snapshot:
        raise IncorrectInviteCodeException("Invitation is unavailable")
    with get_db_session() as session:
        invite = locked_invitation(session, code, snapshot)
        if invite.status != "IN_USE" or invitation_usage(session, invite.invitation_id) >= invite.capacity:
            raise IncorrectInviteCodeException("Invitation capacity is exhausted")
        roles = invitation_roles(as_dict(invite))
        account = create_account(email, encoded_password, db_session=session)
        user_id = account["user_id"]
        member = insert_user_tenant(
            user_id, invite.tenant_id, primary_role(roles), account["email"], db_session=session, roles=roles
        )
        groups = (
            convert_string_to_list(invite.group_ids) if isinstance(invite.group_ids, str) else invite.group_ids or []
        )
        for group_id in groups:
            group = session.execute(
                select(TenantGroupInfo).where(
                    TenantGroupInfo.group_id == int(group_id),
                    TenantGroupInfo.tenant_id == invite.tenant_id,
                    TenantGroupInfo.delete_flag == "N",
                )
            ).scalar_one_or_none()
            if group is None:
                raise IncorrectInviteCodeException("Invitation group is no longer available")
            add_user_to_group(group.group_id, user_id, user_id, db_session=session)
        session.add(
            TenantInvitationRecord(
                invitation_id=invite.invitation_id,
                user_id=user_id,
                created_by=user_id,
                updated_by=user_id,
                delete_flag="N",
            )
        )
        session.flush()
        if invitation_usage(session, invite.invitation_id) >= invite.capacity:
            invite.status = "RUN_OUT"
        return account, member
