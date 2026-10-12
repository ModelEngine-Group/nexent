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
@pytest.mark.case_id("API-006")
@pytest.mark.asyncio
async def test_session_endpoints_reject_invalid_refresh_and_unsigned_token() -> None:
    async with client("config", token="unsigned.claims.payload") as api:
        current = await api.get("/user/current_user_id")
        refresh = await api.post("/user/refresh_token", json={"refresh_token": "invalid"})
    assert_status(current, 401)
    assert_status(refresh, 422)






























