# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-source HTTP contracts over an owned PostgreSQL database."""

import pytest
from fastapi.testclient import TestClient
from ops_roles_http import role_runtime

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D2-001"), pytest.mark.stage("D2")]


def test_roles_union_compatibility_and_operations_boundary(role_runtime):
    r = role_runtime
    assert r.assign("user", ["DEV", "OPS"]).status_code == 200
    profile = r.info("user").json()["data"]["user"]
    assert profile["roles"] == ["DEV", "OPS"]
    assert set(["/agents", "/ops/dashboard", "/ops/configuration", "/resource-manage"]) <= set(
        profile["accessibleRoutes"]
    )
    assert len(profile["permissions"]) == len(set(profile["permissions"]))
    assert len(profile["accessibleRoutes"]) == len(set(profile["accessibleRoutes"]))
    assert r.assign("user", ["OPS"]).status_code == 200
    profile = r.info("user").json()["data"]["user"]
    assert set(profile["accessibleRoutes"]) == {"/ops/dashboard", "/ops/configuration", "/resource-manage"}
    inventory = r.client.get("/ops/resources", headers=r.headers("user"))
    assert inventory.status_code == 200
    assert {row["tenant_id"] for row in inventory.json()["data"]["items"]} == {"a"}
    assert "MUST-NOT-LEAK" not in inventory.text and "api_key" not in inventory.text
    assert r.client.post("/model/create", headers=r.headers("user"), json={}).status_code == 403
    # Legacy bare JWTs must obey the same operations-only boundary as Bearer JWTs.
    bare_token = r.headers("user")["Authorization"].split()[1]
    assert r.client.get(
        "/user/tokens", headers={"Authorization": bare_token}, params={"user_id": r.users["user"]}
    ).status_code == 403
    for action in ("read", "create", "update", "delete"):
        assert (
            r.client.get(
                "/ops/scope", headers=r.headers("user"), params={"tenant_id": "b", "action": action}
            ).status_code
            == 403
        )
        assert (
            r.client.get(
                "/ops/scope", headers=r.headers("su"), params={"tenant_id": "b", "action": action}
            ).status_code
            == 200
        )
    assert r.assign("user", ["ADMIN", "OPS"]).status_code == 200
    profile = r.info("user").json()["data"]["user"]
    assert "/resource-manage" in profile["accessibleRoutes"]
    legacy = r.client.put("/users/" + r.users["dev"], headers=r.headers("su"), json={"role": "USER"})
    assert legacy.status_code == 200
    assert r.client.put("/users/" + r.users["user"], headers=r.headers("su"), json={"role": "USER"}).status_code == 409
    for payload in ({"roles": []}, {"roles": ["SPEED"]}, {"roles": ["UNKNOWN"]}, {"role": "DEV", "roles": ["OPS"]}):
        assert r.client.put("/users/" + r.users["dev"], headers=r.headers("su"), json=payload).status_code == 422
        assert r.info("dev").json()["data"]["user"]["roles"] == ["USER"]
    assert r.client.post("/users/list", json={"tenant_id": "a"}).status_code == 401
    assert r.client.get("/ops/authorization").status_code == 401

    disabled_special = r.client.post(
        "/invitations", headers=r.headers("su"), json={"tenant_id": "a", "code_type": "ASSET_OWNER_INVITE"}
    )
    assert disabled_special.status_code == 400
    # The independent operations process enforces the same real PG-backed identity scope.
    from ops.api.application import create_app

    with TestClient(create_app()) as ops_client:
        assert ops_client.get("/health/ready").status_code == 200
        assert ops_client.get("/ops/resources").status_code == 401
        assert ops_client.get("/ops/resources", headers=r.headers("dev")).status_code == 403
        assert ops_client.get("/ops/resources", headers=r.headers("ops"), params={"tenant_id": "b"}).status_code == 403
        response = ops_client.get("/ops/resources", headers=r.headers("su"), params={"tenant_id": "b"})
        assert response.status_code == 200
        assert {row["tenant_id"] for row in response.json()["data"]["items"]} == {"b"}
