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
@pytest.mark.case_id("API-012")
@pytest.mark.asyncio
async def test_personal_token_creation_and_deletion_require_authentication() -> None:
    async with client("config") as api:
        create = await api.post("/user/tokens")
        delete = await api.delete(f"/user/tokens/{absent_numeric_id(__name__)}")
    assert_status(create, 401)
    assert_status(delete, 401)


















