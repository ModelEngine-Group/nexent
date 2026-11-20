# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Management stages Workbench state before Runtime and commits one confirmation."""

from unittest.mock import AsyncMock

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentStop
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, RuntimeMetadataVersionConflict, ValidationError
from management.services.agent import prepared_turn, workbench
from .test_agent_run_workbench_coverage import existing_workbench, plan
from .test_prepared_public_turn import ACTOR, PAYLOAD, REFERENCE, flow


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [False, True])
async def test_existing_workbench_confirms_config_and_metadata_together(existing_workbench, conflict):
    state = existing_workbench
    request = AgentRequest.model_validate({
        **PAYLOAD.request, "entrypoint": "workbench", "expected_workbench_config_version": 2,
        "metadata": {"ticket": "NEX-1"}, "expected_metadata_version": 4,
    })
    state.compile_snapshot.return_value.runtime_metadata_version = 5
    if conflict:
        prepared_turn.store.confirm_turn.side_effect = RuntimeMetadataVersionConflict(5)
        state.client.stop_run = AsyncMock()
        with pytest.raises(AppException) as error:
            await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)
        assert error.value.error_code == ErrorCode.CHAT_METADATA_VERSION_CONFLICT
        assert error.value.details == {"current_version": 5}
        state.client.stop_run.assert_awaited_once_with(
            AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR,
        )
        state.client.resume.assert_not_awaited()
        assert state.operations == ["stage", "start", "close"]
    else:
        response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)
        assert state.operations == ["stage", "start", "confirm"]
        assert response.headers["x-runtime-metadata-version"] == "5"
        assert response.headers["x-workbench-config-version"] == "3"
        await response.body_iterator.aclose()

    turn = prepared_turn.store.stage_turn.call_args.args[5]
    assert turn["workbench_update"] == {"expected_version": 2, "version": 3, "config": state.canonical.model_dump(mode="json")}
    assert turn["metadata_update"] == {"expected_version": 4, "value": {"ticket": "NEX-1"}}
    prepared_turn.store.confirm_turn.assert_called_once_with(state.staged)


@pytest.mark.asyncio
async def test_new_workbench_stages_canonical_config_with_reserved_id(existing_workbench, mocker):
    state = existing_workbench
    reserve = mocker.patch.object(prepared_turn.store, "allocate_conversation_id", return_value=REFERENCE.conversation_id)
    request = AgentRequest(query="hello", entrypoint="workbench", workbench=state.stored)

    response = await prepared_turn.start_turn(PAYLOAD, request, *ACTOR, state.client)

    reserve.assert_called_once_with()
    prepared_turn.get_conversation.assert_not_called()
    state.resolve.assert_called_once_with(state.stored, tenant_id=ACTOR[1], user_id=ACTOR[0])
    assert request.conversation_id is None
    assert state.compile_snapshot.await_args.args[0].conversation_id == REFERENCE.conversation_id
    assert state.compile_snapshot.await_args.kwargs["new_conversation"] is True
    stage = prepared_turn.store.stage_turn.call_args
    assert stage.args[5]["workbench_update"] == {"expected_version": 0, "version": 1, "config": state.canonical.model_dump(mode="json")}
    assert stage.kwargs["initial_title"]
    assert state.operations == ["stage", "start", "confirm"]
    assert response.headers["x-workbench-config-version"] == "1"
    await response.body_iterator.aclose()


def test_workbench_run_requires_config_when_the_saved_config_is_unavailable(existing_workbench):
    state = existing_workbench
    request = AgentRequest(query="hello", entrypoint="workbench", conversation_id=REFERENCE.conversation_id)

    with pytest.raises(ValidationError, match="Workbench configuration is required"):
        workbench.prepare_portable_workbench(request, None, *ACTOR)

    state.resolve.assert_not_called()
    state.client.start_prepared_run.assert_not_awaited()
