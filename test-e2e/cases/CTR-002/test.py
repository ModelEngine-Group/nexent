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
@pytest.mark.case_id("CTR-002")
@pytest.mark.asyncio
async def test_oauth_state_error_and_pending_account_validation() -> None:
    async with client("config") as api:
        provider_error = await api.get("/user/oauth/callback", params={
            "provider": "github", "error": "access_denied", "error_description": "cancelled",
        })
        complete = await api.post("/user/oauth/complete", json={"password": "123", "invite_code": ""})
    assert_status(provider_error, 400)
    assert (_data(provider_error) or {}).get("oauth_error") == "access_denied"
    assert_status(complete, 422)








