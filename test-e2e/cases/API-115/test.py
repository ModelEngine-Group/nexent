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
@pytest.mark.case_id("API-115")
@pytest.mark.asyncio
async def test_message_sources_enforce_owner_and_type_contract(tenant_a_user, tenant_a_admin) -> None:
    conversation_id = await _create_conversation(tenant_a_user, "sources")
    payload = {"conversation_id": conversation_id, "message_id": absent_numeric_id(__name__), "type": "all"}
    try:
        async with client("runtime", token=tenant_a_user.access_token) as owner:
            missing = await owner.post("/conversation/sources", json=payload)
        async with client("runtime", token=tenant_a_admin.access_token) as other:
            isolated = await other.post("/conversation/sources", json=payload)
        # Sources are a collection: a message with no matching source rows has
        # an empty result. Foreign conversations use the response's business code.
        assert_status(missing, 200)
        assert missing.json()["code"] == 0
        assert missing.json()["data"] == {"searches": [], "images": []}
        assert_status(isolated, 200)
        assert isolated.json()["code"] == 404
        assert isolated.json()["data"] is None
        assert "password" not in isolated.text.lower()
    finally:
        async with client("runtime", token=tenant_a_user.access_token) as api:
            await api.delete(f"/conversation/{conversation_id}")




