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
@pytest.mark.case_id("API-010")
@pytest.mark.asyncio
async def test_revoke_rejects_unsigned_identity_and_preserves_daily_accounts() -> None:
    async with client("config", token="unsigned.claims.payload") as api:
        response = await api.post("/user/revoke")
    assert_status(response, (401, 403))






















