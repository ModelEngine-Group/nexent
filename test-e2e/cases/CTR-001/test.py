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
@pytest.mark.case_id("CTR-001")
@pytest.mark.asyncio
async def test_oauth_authorize_and_callback_local_contract() -> None:
    async with client("config") as api:
        providers = await api.get("/user/oauth/providers")
        callback = await api.get("/user/oauth/callback", params={"provider": "unsupported", "code": ""})
    assert_status(providers, 200)
    assert_status(callback, 400)
    assert (_data(callback) or {}).get("oauth_error") == "no_code"










