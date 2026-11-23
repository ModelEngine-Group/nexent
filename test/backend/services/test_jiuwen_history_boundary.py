# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""An existing chat cannot fall back to client history when its DB boundary is unknown."""

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference
from contracts.errors.exceptions import ForbiddenError
from management.services.agent.preparation import evaluation_snapshot, run


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_turn", [False, True])
async def test_unavailable_history_boundary_rejects_before_prepared_compilation(mocker, saved_turn):
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    load = mocker.patch.object(evaluation_snapshot, "get_historical_context", return_value=None)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=101, run_id="a" * 32)
    request = AgentRequest(
        agent_id=42, conversation_id=101, query="Continue",
        history=[{"role": "assistant", "content": "Client supplied history"}],
    )
    boundary = {"current_user_message_id": 12} if saved_turn else {"before_message_index": 4}

    with pytest.raises(ForbiddenError, match="history boundary"):
        await evaluation_snapshot.prepare_conversation_snapshot(
            request, reference, "owner", "tenant", owned_conversation={}, **boundary,
        )

    if saved_turn:
        load.assert_called_once_with(101, 12, "owner", "tenant")
    else:
        load.assert_called_once_with(101, None, "owner", "tenant", before_message_index=4)
    compile_run.assert_not_awaited()
