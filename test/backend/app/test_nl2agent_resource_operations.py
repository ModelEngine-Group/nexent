# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resource HTTP handlers propagate authenticated scope and map workflow errors."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from contracts.errors.exceptions import AgentDraftEditError
from contracts.nl2agent_resources import (
    ResourceInstallationAttemptRequest,
    ResourceInstallationRequest,
    ResourceLinkRequest,
)
from management.services.agent import authorization
from runtime.api.agent import execution
from services import nl2agent_resource_flow as flow
from management.services.agent.nl2agent import Nl2AgentResourceError
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def boundary(mocker):
    request = MagicMock()
    identity = mocker.patch.object(execution, "get_current_user_info", return_value=("user", "tenant", "en"))
    authorize = mocker.patch.object(authorization, "require_agent_draft_edit")
    return request, identity, authorize


def payload(kind=ResourceInstallationRequest, **extra):
    return kind(agent_id=42, conversation_id=7, card_id="card", state_version=2,
                requirement_id="r1", candidate_ref="tenant_skill_repository:3", **extra)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,operation,kind,extra", [
    ("nl2agent_resource_installation_details", "installation_details", ResourceInstallationRequest, {}),
    ("nl2agent_resource_installation_attempt", "installation_attempt", ResourceInstallationAttemptRequest, {"operation": "check"}),
    ("nl2agent_resource_link", "link_installed_resource", ResourceLinkRequest, {"resource_type": "skill", "resource_id": 9}),
])
async def test_resource_routes_use_authenticated_scope(mocker, boundary, handler, operation, kind, extra):
    request, identity, authorize = boundary
    service = mocker.patch.object(flow, operation, new=AsyncMock(return_value={"status": "installed"}))
    data = payload(kind, **extra)
    result = await getattr(execution, handler)(data, request, "Bearer test")
    service.assert_awaited_once_with(ResourceScope("tenant", "user", 42, "7", ""), data)
    identity.assert_called_once_with("Bearer test", request)
    authorize.assert_called_once_with(agent_id=42, tenant_id="tenant", user_id="user")
    assert result == {"status": "success" if operation == "link_installed_resource" else "installed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code,retryable", [
    (ResourceStateError("resource_card_stale"), "resource_card_stale", False),
    (ResourceStateError("resource_state_unavailable", retryable=True), "resource_state_unavailable", True),
    (Nl2AgentResourceError("resource_evidence_changed", retryable=True), "resource_evidence_changed", True),
])
async def test_workflow_conflicts_map_to_structured_http_409(boundary, error, code, retryable):
    request, _, _ = boundary
    operation = AsyncMock(side_effect=error)
    with pytest.raises(HTTPException) as caught:
        await execution._run_resource_operation(operation, payload(), request, "Bearer test")
    assert caught.value.status_code == 409
    assert caught.value.detail == {"code": code, "retryable": retryable}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AgentDraftEditError("agent_read_only"), PermissionError("private")])
async def test_read_only_draft_cannot_reach_resource_operation(boundary, error):
    request, _, authorize = boundary
    authorize.side_effect = error
    operation = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await execution._run_resource_operation(operation, payload(), request, "Bearer test")
    assert caught.value.status_code == 403 and caught.value.detail == {"code": "agent_read_only"}
    operation.assert_not_awaited()
