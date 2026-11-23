# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native creator facts retain their terminal outcome through durable replay."""

import json
from unittest.mock import AsyncMock

import pytest

from contracts.agent import NL2AgentRunRequest
from management.services.conversation import creator_execution as execution
from test.backend.services.test_creator_session_recovery import settle, store  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
async def test_native_creator_reentry_keeps_wire_and_persisted_outcome(store, outcome):
    base = {
        "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
        "turn_id": "native-creator-recovery",
    }
    facts = [
        {**base, "type": "model_output", "sequence": 1, "block_id": "body", "content": "Preparing"},
        {**base, "type": "run_terminal", "sequence": 2, "content": "", "status": outcome,
         "end_reason": "runner_answer" if outcome == "completed" else outcome,
         "final_content": "Preparing" if outcome == "completed" else "",
         "final_block_ids": ["body"] if outcome == "completed" else [],
         "error": {"safe_message": "Controlled native failure"} if outcome == "failed" else None},
    ]

    async def source():
        for fact in facts:
            yield "data: " + json.dumps(fact) + "\n\n"

    stream, cid = await execution.start_creation_turn(
        NL2AgentRunRequest(query="build", target={"type": "agent", "id": 42}),
        kind="agent", user_id=store.user, tenant_id="tenant",
        stream_factory=AsyncMock(return_value=source()),
    )
    live = [json.loads(frame[6:]) async for frame in stream]
    await settle()
    assistant = store.rows[-1]
    assert assistant["status"] == outcome
    saved = [json.loads(unit["unit_content"]) for unit in assistant["units"]]
    assert [fact["type"] for fact in saved] == ["model_output", "run_terminal"]
    assert saved[-1]["status"] == outcome and saved[-1]["turn_id"] == base["turn_id"]

    factory = AsyncMock()
    resumed, restored_id = await execution.start_creation_turn(
        NL2AgentRunRequest(query="resume", conversation_id=cid, target={"type": "agent", "id": 42}),
        kind="agent", user_id=store.user, tenant_id="tenant", stream_factory=factory, resume=True,
    )
    replayed = [json.loads(frame[6:]) async for frame in resumed]
    assert restored_id == cid and replayed == live
    factory.assert_not_awaited()
    assert sum(event["type"] == "final_answer" for event in live) == int(outcome == "completed")
    assert any(event["type"] == "error" for event in live) == (outcome == "failed")
