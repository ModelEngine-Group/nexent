"""D2 contract for POST /conversation/batch-delete (candidate V5 API-164).

Ownership filtering, cascading soft delete, failed_ids accounting, idempotent
repeats, parameter validation, authentication, and the best-effort automation
cleanup hook are exercised against the real runtime service.
"""

from __future__ import annotations
from shared.factories.conversation import _create_conversation
from shared.resource_ids import absent_numeric_id

import time
from uuid import uuid4

import pytest

from shared.http import MODEL_TIMEOUT, assert_status, client


STAGE = pytest.mark.stage("D2")




async def _delete_conversations(identity, conversation_ids: list[int]):
    async with client("runtime", token=identity.access_token) as api:
        return await api.post("/conversation/batch-delete", json={"conversation_ids": conversation_ids})


async def _list_contains(identity, conversation_id: int) -> bool:
    async with client("runtime", token=identity.access_token) as api:
        offset = 0
        while True:
            response = await api.get("/conversation/list", params={
                "today_start_ms": 0, "week_start_ms": 0, "offset": offset, "limit": 100,
            })
            assert_status(response, 200)
            body = response.json()
            assert body["code"] == 0
            # The paginated API returns data.items, not data.conversations.
            # Missing fields must fail instead of making deletion look successful.
            data = body["data"]
            rows = data["items"]
            assert isinstance(rows, list)
            if any(int(row["conversation_id"]) == conversation_id for row in rows):
                return True
            offset += len(rows)
            if not rows or offset >= int(data["metadata"]["total"]):
                return False


async def _first_agent_id(identity) -> int:
    from shared.asset_registry import resolve_asset
    value=resolve_asset('agents','basic_id',required=False,consumer_case_id='API-164')
    if value is None:
        from shared.factories.agent import prepare_basic_agent
        value=await prepare_basic_agent(identity)
    return int(value)


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-164")
@pytest.mark.asyncio
async def test_conversation_batch_delete_ownership_cascade_failed_ids_and_auth(
    tenant_a_user, tenant_a_admin,
) -> None:
    tag = uuid4().hex[:8]
    agent_id = await _first_agent_id(tenant_a_user)

    mine = [await _create_conversation(tenant_a_user, f"bd-{tag}-{index}") for index in range(3)]
    theirs = await _create_conversation(tenant_a_admin, f"bd-other-{tag}")
    bound = await _create_conversation(tenant_a_user, f"bd-bound-{tag}")
    task_id = None
    try:
        # Prove the lookup can see the fixtures before asserting their removal.
        for conversation_id in [*mine, bound]:
            assert await _list_contains(tenant_a_user, conversation_id)
        assert await _list_contains(tenant_a_admin, theirs)
        # Bind an automation task (and persist exchange messages) to `bound`
        # through the real proposal/confirm API used by AGT-054.
        async with client("runtime", token=tenant_a_user.access_token, timeout=MODEL_TIMEOUT) as api:
            proposal = await api.post("/agent/automations/proposals", json={
                "conversation_id": bound, "agent_id": agent_id,
                "message": f"Every day at 03:00 summarize the batch-{tag} report.",
                "timezone": "Asia/Shanghai",
            })
            assert_status(proposal, 200)
            data = proposal.json().get("data") or {}
            proposal_id = data.get("proposal_id")
            assert proposal_id and data.get("executable") is True
            confirmed = await api.post(f"/agent/automations/proposals/{proposal_id}/confirm", json={})
            assert_status(confirmed, 200)
            task_id = int((confirmed.json().get("data") or {})["task_id"])

        # Step 1: deleting own ids returns exactly that deleted_count.
        response = await _delete_conversations(tenant_a_user, mine)
        assert_status(response, 200)
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["deleted_count"] == len(mine)
        assert body["data"]["failed_ids"] == []

        # Step 3: cascade soft delete - history empty, list no longer returns.
        for conversation_id in mine:
            async with client("runtime", token=tenant_a_user.access_token) as api:
                history = await api.get(f"/conversation/{conversation_id}")
            assert_status(history, 200)
            assert history.json()["data"] == [], "deleted conversation must not resurrect message history"
            assert not await _list_contains(tenant_a_user, conversation_id)

        # Assertion 3: repeating the same batch fails entirely (idempotency).
        repeated = await _delete_conversations(tenant_a_user, mine)
        assert_status(repeated, 200)
        assert repeated.json()["data"]["deleted_count"] == 0
        assert sorted(repeated.json()["data"]["failed_ids"]) == sorted(mine)

        # Step 2: foreign and unknown ids land in failed_ids and stay intact.
        missing_id = absent_numeric_id(__name__)
        mixed = await _delete_conversations(tenant_a_user, [theirs, missing_id, mine[0]])
        assert_status(mixed, 200)
        assert mixed.json()["data"]["deleted_count"] == 0
        assert sorted(mixed.json()["data"]["failed_ids"]) == sorted([theirs, missing_id, mine[0]])
        async with client("runtime", token=tenant_a_admin.access_token) as api:
            other_history = await api.get(f"/conversation/{theirs}")
        assert_status(other_history, 200)
        assert await _list_contains(tenant_a_admin, theirs), (
            "cross-user batch delete must not touch foreign conversations"
        )

        # Step 4: batch delete soft-deletes the bound automation and its
        # persisted exchange messages (best-effort cleanup never blocks).
        bound_response = await _delete_conversations(tenant_a_user, [bound])
        assert_status(bound_response, 200)
        assert bound_response.json()["data"]["deleted_count"] == 1
        async with client("runtime", token=tenant_a_user.access_token) as api:
            gone = await api.get(f"/agent/automations/{task_id}")
            linked = await api.get(f"/conversation/{bound}/automation")
            bound_history = await api.get(f"/conversation/{bound}")
        assert_status(gone, 404)
        assert_status(linked, 200)
        assert linked.json().get("data") in (None, {}, [])
        assert_status(bound_history, 200)
        assert bound_history.json()["data"] == []

        # Step 5: invalid payloads are 4xx parameter errors and never delete.
        async with client("runtime", token=tenant_a_user.access_token) as api:
            missing_field = await api.post("/conversation/batch-delete", json={})
            null_ids = await api.post("/conversation/batch-delete", json={"conversation_ids": None})
            string_ids = await api.post("/conversation/batch-delete", json={"conversation_ids": ["not-an-id"]})
            scalar = await api.post("/conversation/batch-delete", json={"conversation_ids": 42})
            empty_list = await api.post("/conversation/batch-delete", json={"conversation_ids": []})
        assert_status(missing_field, 422)
        assert_status(null_ids, 422)
        assert_status(string_ids, 422)
        assert_status(scalar, 422)
        # BatchDeleteConversationRequest declares List[int] with no min_length
        # and the DB layer returns [] for an empty request, so an empty list is
        # a zero-effect 200 in the real contract.
        assert_status(empty_list, 200)
        assert empty_list.json()["data"] == {"deleted_count": 0, "failed_ids": []}
        assert not await _list_contains(tenant_a_user, bound)

        # Step 6: unauthenticated batch delete is 401.
        async with client("runtime") as anonymous:
            denied = await anonymous.post("/conversation/batch-delete", json={"conversation_ids": mine})
        assert_status(denied, 401)
    finally:
        # Step 7: clean up every row this run still owns.
        if task_id is not None:
            async with client("runtime", token=tenant_a_user.access_token) as api:
                await api.delete(f"/agent/automations/{task_id}")
        async with client("runtime", token=tenant_a_user.access_token) as api:
            await api.post("/conversation/batch-delete", json={"conversation_ids": [*mine, bound]})
        async with client("runtime", token=tenant_a_admin.access_token) as api:
            await api.delete(f"/conversation/{theirs}")
