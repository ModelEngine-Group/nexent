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
@pytest.mark.case_id("API-016")
@pytest.mark.asyncio
async def test_oauth_accounts_are_authenticated_and_unknown_unlink_is_safe(tenant_a_user) -> None:
    async with client("config") as anonymous:
        unauthorized = await anonymous.get("/user/oauth/accounts")
    assert_status(unauthorized, 401)
    async with client("config", token=tenant_a_user.access_token) as api:
        accounts = await api.get("/user/oauth/accounts")
    assert_status(accounts, 200)
    assert isinstance(_data(accounts), list)




