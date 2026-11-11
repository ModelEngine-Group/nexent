# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-source HTTP contracts over an owned PostgreSQL database."""

import pytest
from ops_roles_http import role_runtime

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D5-001"), pytest.mark.stage("D5")]


def test_concurrent_admin_invariants_and_invite_capacity(role_runtime, caplog):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from management.db.client import get_db_session
    from management.db.identity.roles import active_admin_count

    r = role_runtime

    def race(actions):
        barrier = Barrier(len(actions))

        def run(action):
            # Independent HTTP portals model multiple API workers, sharing real PG locks.
            with TestClient(r.app, raise_server_exceptions=False) as client:
                barrier.wait(timeout=10)
                return action(client)

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(run, actions))

    for _ in range(20):
        for admin in ("admin1", "admin2"):
            assert r.assign(admin, ["ADMIN"]).status_code == 200
        responses = race(
            [
                lambda client, admin=admin: client.put(
                    "/users/" + r.users[admin], headers=r.headers("su"), json={"roles": ["USER"]}
                )
                for admin in ("admin1", "admin2")
            ]
        )
        assert sorted(response.status_code for response in responses) == [200, 409]
        with get_db_session() as session:
            assert active_admin_count(session, "a") == 1
    for admin in ("admin1", "admin2"):
        assert r.assign(admin, ["ADMIN"]).status_code == 200
    caplog.set_level("INFO")
    assert r.assign("user", ["DEV", "OPS"]).status_code == 200
    assert r.assign("user", ["USER", "OPS"]).status_code == 200
    assert r.info("user").json()["data"]["user"]["roles"] == ["USER", "OPS"]
    assert any("before=('DEV', 'OPS') after=('USER', 'OPS')" in message for message in caplog.messages)
    invitation = r.invite(["DEV", "OPS"]).json()["data"]
    responses = race(
        [
            lambda client, suffix=suffix: client.post(
                "/user/signup",
                json={
                    "email": suffix + "@race.example.com",
                    "password": r.password,
                    "invite_code": invitation["invitation_code"],
                },
            )
            for suffix in ("first", "second")
        ]
    )
    assert sum(response.status_code == 200 for response in responses) == 1
    with get_db_session() as session:
        assert (
            session.query(r.models.TenantInvitationRecord).filter_by(invitation_id=invitation["invitation_id"]).count()
            == 1
        )
        assert (
            session.query(r.models.UserAccount)
            .filter(r.models.UserAccount.user_email.in_(["first@race.example.com", "second@race.example.com"]))
            .count()
            == 1
        )
