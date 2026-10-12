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
@pytest.mark.case_id("API-117")
@pytest.mark.asyncio
async def test_share_rejects_unknown_conversation_invalid_mode_and_forged_token(tenant_a_user) -> None:
    async with client("runtime", token=tenant_a_user.access_token) as api:
        missing = await api.post(f"/share/conversation/{absent_numeric_id(__name__)}", json={"mode": "all"})
        bad_mode = await api.post(f"/share/conversation/{absent_numeric_id(__name__)}", json={"mode": "invalid"})
    async with client("runtime") as public:
        forged = await public.get("/share/not-a-real-token")
    assert_status(missing, (400, 404))
    assert_status(bad_mode, (400, 422))
    assert_status(forged, 404)
