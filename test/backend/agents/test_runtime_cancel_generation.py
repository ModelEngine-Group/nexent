# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import AgentStop
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import resume


@pytest.mark.asyncio
async def test_stop_keeps_requested_run_id_in_shared_conversation(monkeypatch):
    actor = ServicePrincipal("user", "tenant")
    target = AgentStop(run_id="a" * 32, conversation_id=7)
    lookup = Mock()
    control = AsyncMock(return_value={"conversation_id": 7, "status": "running", "cancellation_requested": True})
    monkeypatch.setattr(resume, "read_execution", lookup)
    monkeypatch.setattr(resume, "_control_io", control)
    monkeypatch.setattr(resume, "runtime_state_service", SimpleNamespace(enabled=False))
    reply = await resume.stop_run(target, actor)
    control.assert_awaited_once_with(
        "agentos-read-execution", lookup, target.run_id, actor.user_id, actor.tenant_id,
        7, request_stop=True, prevent_start=False,
    )
    assert reply.run_id == target.run_id
    assert reply.cancellation_requested
