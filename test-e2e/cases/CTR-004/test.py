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
@pytest.mark.case_id("CTR-004")
@pytest.mark.asyncio
async def test_cas_config_login_and_logout_callback_contract() -> None:
    async with client("config") as api:
        config = await api.get("/user/cas/config")
        logout = await api.post("/user/cas/logout_callback")
    assert_status(config, 200)
    assert isinstance(_data(config), dict)
    assert_status(logout, 200)


