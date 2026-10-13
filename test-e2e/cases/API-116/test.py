"""D2 conversation, feedback, source, and share contracts."""

from __future__ import annotations
from shared.factories.conversation import _create_conversation
from shared.resource_ids import absent_numeric_id

import time
from datetime import datetime, timedelta, timezone

import pytest

from shared.asset_registry import register_asset
from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")












@STAGE
@pytest.mark.case_id("API-116")
@pytest.mark.asyncio
async def test_empty_conversation_share_snapshot_has_public_immutable_token_contract(tenant_a_user) -> None:
    conversation_id = await _create_conversation(tenant_a_user, "share")
    try:
        async with client("runtime", token=tenant_a_user.access_token) as api:
            created = await api.post(f"/share/conversation/{conversation_id}", json={
                "mode": "all", "render_version": "legacy",
                "expire_time": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            })
        assert_status(created, 200)
        token = created.json()["data"]["share_id"]
        async with client("runtime") as public:
            first = await public.get(f"/share/{token}")
            second = await public.get(f"/share/{token}")
        assert_status(first, 200)
        assert first.json()["data"] == second.json()["data"]
        register_asset(
            "sharing", "share_token", token, owner_case_id="API-116", sensitive=True,
        )
    finally:
        async with client("runtime", token=tenant_a_user.access_token) as api:
            await api.delete(f"/conversation/{conversation_id}")


