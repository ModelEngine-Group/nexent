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
@pytest.mark.case_id("CTR-003")
@pytest.mark.asyncio
async def test_oauth_unsupported_provider_fails_before_external_network() -> None:
    async with client("config") as api:
        response = await api.get("/user/oauth/authorize", params={"provider": "not-configured-provider"})
    assert_status(response, 400)






