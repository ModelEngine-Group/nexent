# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepared-turn model preflight runs before conversation and journal writes."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from contracts.agent import AgentRequest
from contracts.errors.exceptions import RunModelControlsError
from management.db.agent import repository
from management.services.agent import prepared_turn
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls
from .test_prepared_public_turn import ACTOR, PAYLOAD, flow


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected_stage", ["selection", "controls"])
async def test_model_preflight_rejection_precedes_conversation_writes(mocker, flow, rejected_stage):
    operations, _, client, _ = flow
    request = AgentRequest.model_validate({**PAYLOAD.request, "model_id": 9})
    mocker.patch.object(prepared_turn, "prepare_conversation_snapshot", evaluation_snapshot.prepare_conversation_snapshot)
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    mocker.patch.object(prepared_turn, "reject_unstaged_turn", new_callable=AsyncMock)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    stages = []

    def check(stage, actual_request, tenant, lookup):
        assert actual_request.model_id == 9
        assert tenant == ACTOR[1]
        assert lookup is repository.search_agent_info_by_agent_id
        stages.append(stage)
        if stage == rejected_stage:
            raise RunModelControlsError("model_controls_invalid")

    mocker.patch.object(run_controls, "validate_agent_model_selection", side_effect=lambda *args: check("selection", *args))
    mocker.patch.object(run_controls, "preflight_agent_turn_controls", side_effect=lambda *args: check("controls", *args))

    with pytest.raises(HTTPException) as raised:
        await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, client)

    assert raised.value.status_code == 422
    assert raised.value.detail == {"code": "model_controls_invalid"}
    assert stages == (["selection"] if rejected_stage == "selection" else ["selection", "controls"])
    assert operations == []
    client.start_prepared_run.assert_not_awaited()
    compile_run.assert_not_awaited()
    prepared_turn.reject_unstaged_turn.assert_awaited_once_with(PAYLOAD, *ACTOR)
