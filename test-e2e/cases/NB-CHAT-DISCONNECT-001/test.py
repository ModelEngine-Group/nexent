# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise a real Northbound run without consuming its SSE response body."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from d3.assets import get_test_asset, model_id, temporary_conversation
from shared.asset_registry import mark_asset_state, register_asset
from shared.cases import case_params
from shared.factories.conversation import delete_owned_conversation
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.postgres import postgres_scalar


@asynccontextmanager
async def detached_run(api_key, identity, existing_id, marker):
    """Submit once and journal newly allocated resources before assertions."""
    conversation_id = existing_id
    registered = False
    primary_error = None
    try:
        async with client("northbound", api_key=api_key, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/nb/v1/chat/run", json={
                "conversation_id": existing_id,
                "agent_name": str(get_test_asset("agents", "basic_name")),
                "query": f"Reply with exactly {marker}.",
                "model_id": await model_id("llm", identity),
            }) as response:
                assert_status(response, 200)
                conversation_id = int(response.headers["conversation_id"])
                if existing_id is None:
                    register_asset(
                        "owned_conversations", str(conversation_id), conversation_id,
                        owner_case_id="NB-CHAT-DISCONNECT-001",
                        cleanup={"service": "runtime", "identity": identity.id, "method": "DELETE",
                                 "path": f"/conversation/{conversation_id}", "allowed_statuses": [200, 404]},
                    )
                    registered = True
                else:
                    assert conversation_id == existing_id
                assert conversation_id > 0
                # Exiting closes the connection. Do not iterate or read response.
        yield conversation_id
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if registered:
            try:
                await delete_owned_conversation(identity, conversation_id)
                mark_asset_state("owned_conversations", str(conversation_id), "DELETED")
            except Exception:
                mark_asset_state("owned_conversations", str(conversation_id), "ORPHANED",
                                 detail="detached conversation cleanup failed")
                if primary_error is None:
                    raise
                primary_error.add_note("Detached conversation cleanup also failed; inspect the asset journal.")


async def assert_persisted_answer(api_key, conversation_id, marker):
    """Wait for completed persistence, never resubmitting or stopping the run."""
    async with asyncio.timeout(300):
        async with client("northbound", api_key=api_key) as api:
            while True:
                history = await api.get(f"/nb/v1/conversations/{conversation_id}")
                assert_status(history, 200)
                messages = history.json()["data"]["history"]
                counts = json.loads(await asyncio.to_thread(
                    postgres_scalar,
                    "SELECT json_build_object("
                    "'user', count(*) FILTER (WHERE message_role='user'), "
                    "'assistant', count(*) FILTER (WHERE message_role='assistant'), "
                    "'completed', count(*) FILTER (WHERE message_role='assistant' AND status='completed'), "
                    "'failed', count(*) FILTER (WHERE status IN ('failed', 'stopped'))) "
                    f"FROM nexent.conversation_message_t WHERE conversation_id={int(conversation_id)}",
                ))
                assert counts["failed"] == 0, "Detached run failed or was stopped"
                if counts["completed"]:
                    assert counts == {"user": 1, "assistant": 1, "completed": 1, "failed": 0}
                    answers = [item["content"] for item in messages if item["role"] == "assistant"]
                    queries = [item["content"] for item in messages if item["role"] == "user"]
                    if len(answers) == 1 and marker.lower() in answers[0].lower():
                        assert len(queries) == 1 and marker in queries[0]
                        return
                await asyncio.sleep(1)


@pytest.mark.parametrize("case", case_params("D3", ["NB-CHAT-DISCONNECT-001"]))
@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
@pytest.mark.asyncio
async def test_headers_only_disconnect_persists_one_answer(case, tenant_a_user, northbound_key, existing):
    marker = "NB_DETACHED_" + uuid4().hex
    if existing:
        async with temporary_conversation(tenant_a_user, "Northbound detached run") as existing_id:
            async with detached_run(northbound_key, tenant_a_user, existing_id, marker) as conversation_id:
                await assert_persisted_answer(northbound_key, conversation_id, marker)
    else:
        async with detached_run(northbound_key, tenant_a_user, None, marker) as conversation_id:
            await assert_persisted_answer(northbound_key, conversation_id, marker)
