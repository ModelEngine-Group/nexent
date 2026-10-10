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
@pytest.mark.case_id("API-004")
@pytest.mark.asyncio
async def test_signin_rejects_wrong_password_without_token_material() -> None:
    from shared.auth import configured_user

    record, _ = configured_user("tenant_a_user")
    async with client("config") as api:
        response = await api.post("/user/signin", json={"email": record["username"], "password": "wrong-password"})
    assert_status(response, 401)
    assert "access_token" not in response.text and "refresh_token" not in response.text


































