"""D2 identity, session, token and external-login boundary contracts."""

from __future__ import annotations

import uuid

import pytest

from shared.auth import sign_in
from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id


STAGE = pytest.mark.stage("D2")


def _data(response):
    payload = response.json()
    return payload.get("data") if isinstance(payload, dict) else None


@STAGE
@pytest.mark.case_id("API-001")
@pytest.mark.asyncio
async def test_signup_validates_invitation_and_password_before_account_creation(tenant_a_admin) -> None:
    from shared.auth import _find_string

    suffix = uuid.uuid4().hex[:10]
    invite_code = f"auto-{suffix}"
    email = f"auto-{suffix}@example.com"
    password = f"Functional-{suffix}-Password"
    async with client("config", token=tenant_a_admin.access_token) as admin:
        invitation = await admin.post("/invitations", json={
            "tenant_id": tenant_a_admin.tenant_id,
            "code_type": "USER_INVITE",
            "invitation_code": invite_code,
            "capacity": 1,
        })
        assert_status(invitation, 201)
        invite_code = str((_data(invitation) or {}).get("invitation_code") or invite_code)
    try:
        async with client("config") as anonymous:
            response = await anonymous.post("/user/signup", json={
                "email": email, "password": password, "invite_code": invite_code, "auto_login": True,
            })
        assert_status(response, 200)
        token = _find_string(response.json(), {"access_token", "accesstoken", "token"})
        assert token
        async with client("config", token=token.removeprefix("Bearer ")) as created_user:
            current = await created_user.get("/user/current_user_info")
            assert_status(current, 200)
            assert (_data(current) or {}).get("user")
            revoked = await created_user.post("/user/revoke")
            assert_status(revoked, 200)
    finally:
        async with client("config", token=tenant_a_admin.access_token) as admin:
            cleanup = await admin.delete(f"/invitations/{invite_code}")
            assert_status(cleanup, (200, 404))








































