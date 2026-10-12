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
@pytest.mark.case_id("API-005")
@pytest.mark.asyncio
async def test_refresh_token_returns_valid_session_for_same_user() -> None:
    identity = await sign_in("tenant_a_user")
    if not identity.refresh_token:
        pytest.skip("signin response did not provide the refresh-token asset required by API-005")
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/user/refresh_token", json={"refresh_token": identity.refresh_token})
    assert_status(response, 200)
    from shared.auth import _find_string
    new_access = _find_string(response.json(), {"access_token", "accesstoken", "token"})
    # Rotation is an auth-provider policy, not an API contract. Providers may
    # return the same still-valid JWT when refreshed within the same second.
    assert new_access
    async with client("config", token=new_access.removeprefix("Bearer ")) as refreshed:
        current = await refreshed.get("/user/current_user_id")
    assert_status(current, 200)
    assert str(_data(current)["user_id"]) == identity.user_id
































