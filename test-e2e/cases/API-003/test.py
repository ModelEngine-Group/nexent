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
@pytest.mark.case_id("API-003")
@pytest.mark.asyncio
async def test_signin_returns_verified_session_and_current_identity() -> None:
    identity = await sign_in("tenant_a_user")
    assert identity.access_token and identity.user_id and identity.tenant_id
    async with client("config", token=identity.access_token) as api:
        session = await api.get("/user/session")
        current = await api.get("/user/current_user_id")
    assert_status(session, 200)
    assert _data(session) is not None
    assert_status(current, 200)
    assert str(_data(current)["user_id"]) == identity.user_id




































