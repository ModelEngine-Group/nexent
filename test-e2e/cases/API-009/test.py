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
@pytest.mark.case_id("API-009")
@pytest.mark.asyncio
async def test_account_revoke_requires_authenticated_disposable_user() -> None:
    # The fixed daily accounts are assets and must never be deleted. This case
    # proves the destructive endpoint cannot be called anonymously; the positive
    # cascade is covered with the explicitly disposable asset in D3.
    async with client("config") as api:
        response = await api.post("/user/revoke")
    assert_status(response, 401)
























