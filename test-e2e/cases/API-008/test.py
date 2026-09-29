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
@pytest.mark.case_id("API-008")
@pytest.mark.asyncio
async def test_logout_does_not_turn_invalid_token_into_server_error() -> None:
    async with client("config", token="expired-or-invalid") as api:
        response = await api.post("/user/logout")
    assert_status(response, 200)


























