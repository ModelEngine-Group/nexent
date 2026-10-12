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
@pytest.mark.case_id("API-113")
@pytest.mark.asyncio
async def test_conversation_rejects_bad_pagination_anonymous_access_and_cross_user_history(tenant_a_user, tenant_a_admin) -> None:
    conversation_id = await _create_conversation(tenant_a_user, "isolated")
    try:
        async with client("runtime", token=tenant_a_user.access_token) as owner:
            visible = await owner.get(f"/conversation/{conversation_id}")
            invalid = await owner.get("/conversation/list", params={
                "today_start_ms": -1, "week_start_ms": -1, "limit": 0,
            })
        async with client("runtime") as anonymous:
            unauthenticated = await anonymous.get(f"/conversation/{conversation_id}")
        async with client("runtime", token=tenant_a_admin.access_token) as other:
            isolated = await other.get(f"/conversation/{conversation_id}")
        assert_status(invalid, 422)
        assert_status(unauthenticated, 401)
        assert_status(visible, 200)
        assert visible.json()["data"], "owner must be able to read the created conversation"
        # History masks absent and foreign conversations with an empty result.
        # Check the payload, not just HTTP success, to retain isolation coverage.
        assert_status(isolated, 200)
        assert isolated.json()["code"] == 0
        assert isolated.json()["data"] == []
    finally:
        async with client("runtime", token=tenant_a_user.access_token) as owner:
            await owner.delete(f"/conversation/{conversation_id}")








