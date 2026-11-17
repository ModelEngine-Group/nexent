# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-source HTTP contracts over an owned PostgreSQL database."""

import pytest
from ops_roles_http import role_runtime

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D2-002"), pytest.mark.stage("D2")]


def test_administrator_grants_and_protected_mutations(role_runtime):
    from sqlalchemy import select

    r = role_runtime

    def membership_state(target):
        with r.engine.connect() as connection:
            return tuple(
                connection.execute(
                    select(
                        r.models.UserTenant.roles,
                        r.models.UserTenant.delete_flag,
                        r.models.UserAccount.delete_flag,
                        r.models.UserAccount.password_login_enabled,
                    )
                    .join(r.models.UserAccount, r.models.UserAccount.user_id == r.models.UserTenant.user_id)
                    .where(r.models.UserTenant.user_id == r.users[target])
                ).one()
            )

    assert r.assign("user", ["ADMIN", "OPS"], "admin1").status_code == 200
    assert r.info("user").json()["data"]["user"]["roles"] == ["ADMIN", "OPS"]
    assert r.assign("user", ["DEV", "OPS"], "admin1").status_code == 200
    assert r.info("user").json()["data"]["user"]["roles"] == ["DEV", "OPS"]
    users = r.client.post("/users/list", headers=r.headers("admin1"), json={"tenant_id": "a", "roles": ["OPS", "DEV"]})
    assert users.status_code == 200
    ids = [user["id"] for user in users.json()["data"]]
    assert set(ids) == {r.users["user"], r.users["dev"], r.users["ops"]}
    assert len(ids) == len(set(ids)) == users.json()["total"] == 3
    mixed_filter = r.client.post(
        "/users/list", headers=r.headers("su"),
        json={"tenant_id": "platform", "roles": ["SU", "OPS"]},
    )
    assert mixed_filter.status_code == 200
    assert [user["id"] for user in mixed_filter.json()["data"]] == [r.users["su"]]
    for target, actor, status in (
        ("admin1", "admin1", 409),
        ("foreign", "admin1", 403),
        ("su", "admin1", 403),
        ("asset_owner", "su", 403),
        ("user", "ops", 403),
    ):
        before = membership_state(target)
        assert r.assign(target, ["USER"], actor).status_code == status
        assert membership_state(target) == before
    assert r.assign("admin2", ["USER"], "admin1").status_code == 200
    before = membership_state("admin1")
    assert r.assign("admin1", ["USER"], "su").status_code == 409
    assert membership_state("admin1") == before
    self_choices = r.client.get(
        "/users/" + r.users["admin1"] + "/assignable_roles", headers=r.headers("admin1")
    ).json()["data"]
    assert self_choices["locked_roles"] == ["ADMIN"]
    assert set(self_choices["grantable_roles"]) == {"ADMIN", "DEV", "USER", "OPS"}
    assert "ADMIN" not in self_choices["revocable_roles"]
    assert r.assign("user", ["USER", "OPS"], "admin1").status_code == 200
    assert "roles_version" not in r.info("user").text
    # Denied deletion cannot disable the last administrator's credentials.
    assert r.client.delete("/users/" + r.users["admin1"], headers=r.headers("su")).status_code == 409
    assert r.info("admin1").status_code == 200

    # A non-primary ADMIN grant still receives the original administrator audience.
    assert r.assign("user", ["ADMIN", "USER", "OPS"], "admin1").status_code == 200
    from management.db.client import get_db_session
    from management.db.notification.repository import _resolve_receivers
    from contracts.constants.constants import SCOPE_TENANT_ADMIN

    with get_db_session() as session:
        receivers = _resolve_receivers(session, SCOPE_TENANT_ADMIN, "a")
        assert sum(row["user_id"] == r.users["user"] for row in receivers) == 1
