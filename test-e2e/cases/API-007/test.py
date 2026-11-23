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
@pytest.mark.case_id("API-007")
@pytest.mark.asyncio
async def test_logout_is_idempotent_without_session_or_cas_side_effect() -> None:
    async with client("config") as api:
        first = await api.post("/user/logout")
        second = await api.post("/user/logout")
    assert_status(first, 200)
    assert_status(second, 200)
    assert (_data(second) or {}).get("cas_logout_url") in ("", None)




























