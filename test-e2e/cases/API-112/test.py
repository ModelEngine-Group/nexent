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
@pytest.mark.case_id("API-112")
@pytest.mark.asyncio
async def test_conversation_create_list_rename_history_and_delete_lifecycle(tenant_a_user) -> None:
    conversation_id = await _create_conversation(tenant_a_user)
    now_ms = int(time.time() * 1000)
    async with client("runtime", token=tenant_a_user.access_token) as api:
        renamed = await api.post("/conversation/rename", json={
            "conversation_id": conversation_id, "name": "D2 renamed",
        })
        assert_status(renamed, 200)
        listed = await api.get("/conversation/list", params={
            "today_start_ms": now_ms - 86400000, "week_start_ms": now_ms - 604800000,
            "offset": 0, "limit": 20,
        })
        assert_status(listed, 200)
        history = await api.get(f"/conversation/{conversation_id}")
        assert_status(history, 200)
        deleted = await api.delete(f"/conversation/{conversation_id}")
        assert_status(deleted, 200)










