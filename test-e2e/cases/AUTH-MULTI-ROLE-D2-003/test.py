# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-source HTTP contracts over an owned PostgreSQL database."""

import pytest
from ops_roles_http import role_runtime

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D2-003"), pytest.mark.stage("D2")]


def test_fixed_invitation_grants_survive_issuer_revocation(role_runtime):
    from sqlalchemy import select
    from management.db.client import get_db_session

    r = role_runtime
    created = r.invite(["ADMIN", "OPS"], "admin2")
    assert created.status_code == 201, created.text
    code = created.json()["data"]["invitation_code"]
    assert created.json()["data"]["roles"] == ["ADMIN", "OPS"]
    assert (
        r.client.put("/invitations/" + code, headers=r.headers("admin1"), json={"roles": ["USER"]}).status_code == 422
    )
    assert r.client.get("/invitations/" + code).json()["data"]["roles"] == ["ADMIN", "OPS"]
    assert r.assign("admin2", ["USER"], "admin1").status_code == 200
    assert r.client.get("/invitations/" + code + "/available").json()["data"]["available"]
    assert r.client.delete("/invitations/" + code, headers=r.headers("admin1")).status_code == 200
    assert not r.client.get("/invitations/" + code + "/available").json()["data"]["available"]
    with get_db_session() as session:
        before = session.query(r.models.TenantInvitationCode).count()
    assert r.invite(["USER"], "ops").status_code == 403
    assert (
        r.client.post(
            "/invitations", headers=r.headers("admin1"), json={"tenant_id": "b", "roles": ["OPS"]}
        ).status_code
        == 403
    )
    assert r.invite(["SU"]).status_code == 422
    with get_db_session() as session:
        assert session.query(r.models.TenantInvitationCode).count() == before
    legacy = r.client.post(
        "/invitations", headers=r.headers("admin1"), json={"tenant_id": "a", "code_type": "USER_INVITE"}
    )
    assert legacy.status_code == 201 and legacy.json()["data"]["roles"] == ["USER"]
    default_admin = r.client.post(
        "/invitations", headers=r.headers("admin1"), json={"tenant_id": "a", "roles": ["ADMIN", "OPS"]}
    )
    assert default_admin.status_code == 201
    assert default_admin.json()["data"]["group_ids"] == [r.group]
    default_dev = r.client.post(
        "/invitations", headers=r.headers("admin1"), json={"tenant_id": "a", "roles": ["DEV", "OPS"]}
    )
    assert default_dev.status_code == 201
    assert default_dev.json()["data"]["group_ids"] == []
