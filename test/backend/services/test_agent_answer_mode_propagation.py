# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Presentation stays local to Management through preparation and admission."""

from types import SimpleNamespace

import pytest

from contracts.agent import AgentRequest
from management.services.agent import prepared_turn
from .test_prepared_public_turn import ACTOR, PAYLOAD, flow


@pytest.mark.asyncio
@pytest.mark.parametrize("complete_answer", [False, True])
@pytest.mark.parametrize("memory_enabled", [False, True])
async def test_presentation_survives_prepared_admission(mocker, flow, complete_answer, memory_enabled):
    operations, compile_snapshot, client, _ = flow
    snapshot = compile_snapshot.return_value
    snapshot.memory_enabled = memory_enabled
    snapshot.resource = SimpleNamespace(agent_id=7)
    present = mocker.patch.object(prepared_turn, "present_public_resume")
    request = AgentRequest.model_validate(PAYLOAD.request)

    result = await prepared_turn.start_turn(
        PAYLOAD, request, *ACTOR, client, include_journal_controls=False, complete_answer=complete_answer,
    )

    assert result is present.return_value
    assert operations == ["stage", "start", "confirm"]
    client.start_prepared_run.assert_awaited_once_with(snapshot, *ACTOR)
    assert "complete_answer" not in compile_snapshot.await_args.kwargs
    assert present.call_args.kwargs["include_journal_controls"] is False
    assert present.call_args.kwargs["complete_answer"] is complete_answer
    staged = prepared_turn.store.stage_turn.call_args.args[5]
    assert staged.get("memory_agent_id") == (7 if memory_enabled else None)
