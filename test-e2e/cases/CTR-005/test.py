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
@pytest.mark.case_id("CTR-005")
@pytest.mark.asyncio
async def test_cas_missing_ticket_is_rejected_without_external_call() -> None:
    async with client("config") as api:
        response = await api.get("/user/cas/callback", params={"ticket": ""})
    assert_status(response, 401)
