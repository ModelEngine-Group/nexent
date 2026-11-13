# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Role registration, per-type scopes and legacy decision authorization proofs."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import delete

from management.db.models import UserTenant, RolePermission
from management.db.repository_reviews import REVIEW_MODELS


def access_contract(fixture):
    from sqlalchemy import delete
    roles = {}
    for role in ("ADMIN", "DEV", "SPEED", "ASSET_OWNER", "USER", "SU", "SUPER_ADMIN"):
        actor = str(uuid.uuid4())
        roles[role] = actor
        with fixture.factory.begin() as session:
            session.add(UserTenant(user_id=actor, tenant_id=fixture.tenant, user_role=role, user_email=None))
            for kind in REVIEW_MODELS:
                fixture.add(session, kind, 600 + len(roles), submitted_user_id=actor,
                            submitted_at=datetime.now(timezone.utc), revision=1)
        response = fixture.get(user=actor, params={"page_size":100})
        if role in {"USER", "SU", "SUPER_ADMIN"}:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            if role != "ADMIN":
                assert response.json()["pagination"]["total"] == 3
                assert all(row["submitted_user_id"] == actor and not row["allowed_actions"] for row in response.json()["items"])
    for key in ("user_id", "tenant_id", "submitter_id", "scope"):
        assert fixture.get(user=fixture.mine, params={key:fixture.admin}).status_code == 400
    with fixture.factory.begin() as session:
        session.execute(delete(RolePermission).where(RolePermission.user_role=="DEV",
            RolePermission.permission_subtype=="/resource-space"))
        for url in ("/agent-space", "/skill-space", "/mcp-space"):
            session.add(RolePermission(user_role="DEV", permission_category="VISIBILITY",
                permission_type="LEFT_NAV_MENU", permission_subtype=url))
    assert fixture.get(user=roles["DEV"]).status_code == 403
    with fixture.factory.begin() as session:
        session.add(RolePermission(user_role="DEV", permission_category="VISIBILITY",
            permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"))
        for role in ("SU", "SUPER_ADMIN"):
            session.add(RolePermission(user_role=role, permission_category="VISIBILITY",
                permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"))
    assert fixture.get(user=roles["DEV"]).status_code == 200
    with fixture.factory.begin() as session:
        session.add(RolePermission(user_role="USER", permission_category="VISIBILITY",
            permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"))
    ordinary = fixture.get(user=roles["USER"], params={"page_size":100})
    assert ordinary.status_code == 200
    assert ordinary.json()["pagination"]["total"] == 3
    assert all(row["submitted_user_id"] == roles["USER"] and not row["allowed_actions"]
               for row in ordinary.json()["items"])
    skill_read = fixture.client.get("/repository/skill", headers=fixture.headers(roles["USER"]))
    assert skill_read.status_code == 200, skill_read.text
    for role in ("SU", "SUPER_ADMIN"):
        response = fixture.get(user=roles[role], params={"page_size":100}).json()
        assert any(row["resource_type"] == "mcp" and row["repository_id"] == "101" for row in response["items"])
        assert all(row["submitted_user_id"] == roles[role] for row in response["items"] if row["resource_type"] != "mcp")
    for kind in REVIEW_MODELS:
        assert fixture.get(f"/reviews/{kind}/101", user=fixture.admin).status_code == 404
        assert fixture.decision(kind, 1, user=fixture.mine).status_code == 403
        assert fixture.decision(kind, 101).status_code == 404
        assert fixture.client.post(f"/reviews/{kind}/1/decision", json={"decision":"approve", "expected_revision":0}).status_code == 401
        for owner in (fixture.admin, fixture.other):
            identifier = 800 if owner == fixture.admin else 801
            with fixture.factory.begin() as session:
                fixture.add(session, kind, identifier, submitted_user_id=owner, revision=1)
            assert fixture.decision(kind, identifier, revision=1).status_code == 200
        safe = fixture.get(f"/reviews/{kind}/1").json()
        assert "secret" not in str(safe["resource_detail"])
    # Repeating a status must not bypass the original ownership/role gate.
    for kind in ("agent", "skill"):
        before = fixture.get(f"/reviews/{kind}/1").json()
        response = fixture.client.patch(f"/repository/{kind}/1/status", headers=fixture.headers(fixture.other),
            json={"status":"pending_review", "content":"Unauthorized replacement"})
        assert response.status_code in {401,403}, response.text
        after = fixture.get(f"/reviews/{kind}/1").json()
        assert (after["revision"],after["submit_description"]) == (before["revision"],before["submit_description"])

    before = fixture.get("/reviews/mcp/1").json()
    response = fixture.client.put("/mcp-tools/community/1", headers=fixture.headers(fixture.other),
        json={"description":"Unauthorized snapshot", "content":"Unauthorized submission"})
    assert response.status_code in {401, 403}, response.text
    after = fixture.get("/reviews/mcp/1").json()
    assert (after["revision"], after["description"], after["submit_description"]) == (
        before["revision"], before["description"], before["submit_description"])
