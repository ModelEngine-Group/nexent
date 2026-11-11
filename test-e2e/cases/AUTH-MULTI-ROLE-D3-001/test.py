# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-source HTTP contracts over an owned PostgreSQL database."""

import pytest

from ops_roles_http import role_runtime as role_runtime

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D3-001"), pytest.mark.stage("D3")]


def test_registration_atomicity_and_next_request_revocation(role_runtime):
    from sqlalchemy import select

    from management.db.client import get_db_session

    r = role_runtime

    def foreign_state():
        with get_db_session() as session:
            member = session.execute(
                select(r.models.UserTenant.roles, r.models.UserTenant.delete_flag).where(
                    r.models.UserTenant.user_id == r.users["foreign"]
                )
            ).one()
            models = session.execute(
                select(
                    r.models.ModelRecord.model_id, r.models.ModelRecord.model_name, r.models.ModelRecord.delete_flag
                ).where(r.models.ModelRecord.tenant_id == "b")
            ).all()
            return tuple(member), [tuple(row) for row in models]

    foreign_before = foreign_state()
    invitation = r.invite(["DEV", "OPS"]).json()["data"]
    registered = r.signup(invitation["invitation_code"])
    assert registered.status_code == 200, registered.text
    data = registered.json()["data"]
    uid, token = data["user"]["id"], data["session"]["access_token"]
    r.users["registered"], r.tokens["registered"] = uid, token
    with get_db_session() as session:
        member = session.execute(select(r.models.UserTenant).where(r.models.UserTenant.user_id == uid)).scalar_one()
        account = session.execute(
            select(r.models.UserAccount).where(r.models.UserAccount.user_id == member.user_id)
        ).scalar_one()
        assert account.user_roles == ["DEV", "OPS"]
        assert member.roles == account.user_roles
        assert "roles" not in r.models.UserTenant.__table__.columns
        assert {"user_role", "roles"}.isdisjoint(r.models.UserAccount.__table__.columns.keys())
        assert session.query(r.models.TenantGroupUser).filter_by(user_id=uid, group_id=r.group).count() == 1
        assert (
            session.query(r.models.TenantInvitationRecord).filter_by(invitation_id=invitation["invitation_id"]).count()
            == 1
        )
    assert r.info("registered").json()["data"]["user"]["roles"] == ["DEV", "OPS"]
    assert r.assign(uid, ["OPS"]).status_code == 200
    assert r.client.get("/model/list", headers=r.headers("registered")).status_code == 403
    assert r.info("registered").json()["data"]["user"]["roles"] == ["OPS"]
    failure_invite = r.invite(["DEV", "OPS"]).json()["data"]
    with get_db_session() as session:
        row = session.execute(
            select(r.models.TenantInvitationCode).where(
                r.models.TenantInvitationCode.invitation_id == failure_invite["invitation_id"]
            )
        ).scalar_one()
        row.group_ids = "99999999"
        tracked = [
            r.models.UserAccount,
            r.models.UserTenant,
            r.models.TenantGroupUser,
            r.models.TenantInvitationRecord,
        ]
        before = [session.query(model).count() for model in tracked]
    failed = r.signup(failure_invite["invitation_code"])
    assert failed.status_code >= 400
    with get_db_session() as session:
        assert [session.query(model).count() for model in tracked] == before
        assert (
            session.query(r.models.TenantInvitationRecord)
            .filter_by(invitation_id=failure_invite["invitation_id"])
            .count()
            == 0
        )
    survivor = r.invite(["DEV", "OPS"], "admin2").json()["data"]
    deleted_issuer_invite = r.invite(["DEV", "OPS"], "admin2").json()["data"]
    assert r.assign("admin2", ["USER"], "admin1").status_code == 200
    assert r.signup(survivor["invitation_code"]).status_code == 200
    assert r.client.delete("/users/" + r.users["admin2"], headers=r.headers("admin1")).status_code == 200
    after_deletion = r.signup(deleted_issuer_invite["invitation_code"])
    assert after_deletion.status_code == 200, after_deletion.text
    assert after_deletion.json()["data"]["user"]["roles"] == ["DEV", "OPS"]
    assert (
        r.client.delete(
            "/invitations/" + deleted_issuer_invite["invitation_code"], headers=r.headers("admin1")
        ).status_code
        == 200
    )
    with get_db_session() as session:
        member = session.execute(
            select(r.models.UserTenant).where(
                r.models.UserTenant.user_id == after_deletion.json()["data"]["user"]["id"]
            )
        ).scalar_one()
        account = session.execute(
            select(r.models.UserAccount).where(r.models.UserAccount.user_id == member.user_id)
        ).scalar_one()
        assert account.user_roles == ["DEV", "OPS"]
        assert member.roles == account.user_roles
        assert "roles" not in r.models.UserTenant.__table__.columns
        assert {"user_role", "roles"}.isdisjoint(r.models.UserAccount.__table__.columns.keys())
    assert foreign_state() == foreign_before
