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
@pytest.mark.case_id("API-011")
@pytest.mark.asyncio
async def test_personal_token_secret_is_returned_only_at_creation(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        created = await api.post("/user/tokens")
        assert_status(created, 200)
        token = _data(created) or {}
        token_id = token.get("token_id") or token.get("id")
        secret = token.get("access_key") or token.get("token")
        assert token_id and secret
        listed = await api.get("/user/tokens", params={"user_id": tenant_a_user.user_id})
        assert_status(listed, 200)
        assert secret not in listed.text
        deleted = await api.delete(f"/user/tokens/{token_id}")
        assert_status(deleted, 200)




















