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
@pytest.mark.case_id("API-014")
@pytest.mark.asyncio
async def test_token_list_for_other_user_is_forbidden(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        response = await api.get("/user/tokens", params={"user_id": "another-user"})
    assert_status(response, 403)














