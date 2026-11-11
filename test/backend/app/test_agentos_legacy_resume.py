# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.errors.exceptions import ForbiddenError, WorkbenchError
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import legacy_resume


ACTOR = ServicePrincipal("user-a", "tenant-a")


@pytest.fixture
def resume_dependencies(mocker):
    state = mocker.patch.object(legacy_resume, "run_blocking", new_callable=AsyncMock)
    registry = mocker.patch.object(legacy_resume, "agent_run_manager")
    registry.get_agent_run_info.return_value = None
    channels = mocker.patch.object(legacy_resume, "streaming_channel_manager")
    channels.get_channel.return_value = None
    remote = mocker.patch.object(legacy_resume.runtime_state_service, "get_run_state_async", new_callable=AsyncMock)
    remote.return_value = {}
    replay = mocker.patch.object(legacy_resume, "replay_legacy_stream")
    return state, remote, replay


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ForbiddenError, WorkbenchError])
async def test_resume_denies_unowned_or_disabled_conversation(mocker, resume_dependencies, error):
    state, remote, replay = resume_dependencies
    mocker.patch.object(legacy_resume, "ENABLE_AGENT_WORKBENCH", False)
    if error is ForbiddenError:
        state.side_effect = PermissionError("Conversation is not accessible to the current identity")
    else:
        state.return_value = (True, None)

    with pytest.raises(error):
        await legacy_resume.resume_legacy_conversation(42, ACTOR, workbench=False)

    state.assert_awaited_once_with(
        "agentos-legacy-resume-state", legacy_resume.read_legacy_resume_state, 42,
        "user-a", "tenant-a", lane="control-io", owner="runtime",
    )
    remote.assert_not_awaited()
    replay.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("last_unit,offset", [(None, 0), (7, 8)])
async def test_resume_replays_remote_run_at_persisted_offset(resume_dependencies, last_unit, offset):
    state, remote, replay = resume_dependencies
    state.return_value = (False, ("streaming", last_unit))
    remote.return_value = {"status": "running"}

    response = await legacy_resume.resume_legacy_conversation(42, ACTOR, workbench=False)

    assert response is replay.return_value
    replay.assert_called_once_with(
        42, "user-a", offset, channel_manager=legacy_resume.streaming_channel_manager,
        state_service=legacy_resume.runtime_state_service, is_remote_running=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("assistant,expected", [
    (None, {"status": None, "message": "Stream already None: no_assistant_message"}),
    (("failed", 2), {"status": "failed", "message": "Stream already failed: backend_failed"}),
    (("streaming", 2), {"status": "completed", "message": "Agent finished during disconnection"}),
])
async def test_resume_preserves_legacy_status_response(resume_dependencies, assistant, expected):
    state, _, replay = resume_dependencies
    state.return_value = (False, assistant)

    response = await legacy_resume.resume_legacy_conversation(42, ACTOR, workbench=False)

    assert response.status_code == 200
    assert json.loads(response.body) == expected
    replay.assert_not_called()


@pytest.mark.asyncio
async def test_resume_replays_completed_message_while_local_channel_drains(resume_dependencies):
    state, _, replay = resume_dependencies
    state.return_value = (False, ("completed", 7))
    channel = Mock(is_completed=False)
    legacy_resume.streaming_channel_manager.get_channel.return_value = channel
    legacy_resume.agent_run_manager.get_agent_run_info.return_value = Mock()

    response = await legacy_resume.resume_legacy_conversation(42, ACTOR, workbench=False)

    assert response is replay.return_value
    replay.assert_called_once_with(
        42, "user-a", 8, channel_manager=legacy_resume.streaming_channel_manager,
        state_service=legacy_resume.runtime_state_service, is_remote_running=False,
    )
