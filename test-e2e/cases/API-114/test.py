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
@pytest.mark.case_id("API-114")
@pytest.mark.asyncio
async def test_feedback_and_message_index_contract_reject_unknown_message_without_mutation(tenant_a_user) -> None:
    conversation_id = await _create_conversation(tenant_a_user, "feedback")
    try:
        async with client("runtime", token=tenant_a_user.access_token) as api:
            before = await api.get(f"/conversation/{conversation_id}")
            lookup = await api.post("/conversation/message/id", json={
                "conversation_id": conversation_id, "message_index": 0,
            })
            opinion = await api.post("/conversation/message/update_opinion", json={
                "message_id": absent_numeric_id(__name__), "opinion": "Y",
            })
            after = await api.get(f"/conversation/{conversation_id}")
        assert_status(before, 200)
        assert_status(after, 200)
        assert before.json()["data"] == after.json()["data"]
        # Use the valid Y/N opinion domain, so missing-resource handling is
        # tested independently of malformed opinion values. Report both routes.
        assert (lookup.status_code, opinion.status_code) == (404, 404), (
            f"missing message: lookup HTTP {lookup.status_code}, "
            f"opinion HTTP {opinion.status_code}; expected 404 for both"
        )
    finally:
        async with client("runtime", token=tenant_a_user.access_token) as api:
            await api.delete(f"/conversation/{conversation_id}")






