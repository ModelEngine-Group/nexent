# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for conversation chat_mode handling during resume reconnects."""

from unittest.mock import MagicMock

import pytest
from fastapi import Request

from . import test_agent_service as service_tests


@pytest.mark.asyncio
async def test_run_agent_stream_resume_keeps_stored_chat_mode(monkeypatch):
    """Resume reconnects must not rewrite the stored conversation chat_mode.

    The frontend resume path (page refresh while a stream is still running)
    does not carry enable_plan, so the request resolves to execution mode.
    Applying the regular chat_mode update during resume would silently flip a
    planning conversation back to execution while its planning run is still
    in flight. The sibling knowledge-scope and agent-id updates in the same
    function already skip resume requests; chat_mode must follow suit.
    """
    service = service_tests.agent_subscription
    update_chat_mode = MagicMock()
    monkeypatch.setattr(
        service,
        "_resolve_user_tenant_language",
        MagicMock(return_value=("user1", "tenant1", "en")),
    )
    monkeypatch.setattr(
        service,
        "get_conversation_service",
        MagicMock(return_value={"conversation_id": 999}),
    )
    monkeypatch.setattr(service, "update_conversation_chat_mode_service", update_chat_mode)
    monkeypatch.setattr(
        service,
        "_detect_resume_position",
        MagicMock(
            return_value={
                "should_resume": False,
                "message_id": 1,
                "message_status": "completed",
                "resume_from_unit_index": None,
                "reason": "backend_completed",
            }
        ),
    )
    request = service_tests.AgentRequest(
        agent_id=1,
        conversation_id=999,
        query="resume",
        history=[],
        minio_files=[],
        is_debug=False,
        enable_plan=False,
    )
    response = await service.run_agent_stream(
        request,
        Request({"type": "http", "headers": []}),
        user_id="user1",
        tenant_id="tenant1",
        resume=True,
    )
    update_chat_mode.assert_not_called()
    assert response.status_code == 200
    assert b"already completed" in response.body
