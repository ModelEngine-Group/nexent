# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Target binding HTTP contract keeps ownership errors and saved IDs explicit."""

import pytest
from fastapi import HTTPException

from contracts.conversation import ConversationTarget
from contracts.errors.exceptions import AgentDraftEditError, WorkbenchError
from management.api.conversation import conversation_management as routes
from management.services.conversation import creator_targets


@pytest.mark.asyncio
async def test_saved_skill_target_is_bound_for_current_owner_and_tenant(mocker):
    mocker.patch.object(routes, "get_current_user_id", return_value=("user-a", "tenant-a"))
    target = {"type": "skill", "id": 201}
    bind = mocker.patch.object(creator_targets, "bind_creator_target", return_value=target)
    result = await routes.bind_creation_target_endpoint(9, ConversationTarget(**target), "Bearer token")
    assert result == {"code": 0, "data": {"target": target}, "message": "success"}
    bind.assert_called_once_with(9, target, "user-a", "tenant-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status", [
    (PermissionError("not editable"), 403),
    (ValueError("already bound"), 409),
    (AgentDraftEditError("agent_not_found"), 404),
    (AgentDraftEditError("agent_read_only"), 403),
    (WorkbenchError("system_agent_not_ready", status_code=503), 503),
])
async def test_target_errors_have_stable_http_status(mocker, error, status):
    mocker.patch.object(routes, "get_current_user_id", return_value=("user-a", "tenant-a"))
    mocker.patch.object(creator_targets, "bind_creator_target", side_effect=error)
    with pytest.raises(HTTPException) as caught:
        await routes.bind_creation_target_endpoint(9, ConversationTarget(type="agent", id=201), "Bearer token")
    assert caught.value.status_code == status
