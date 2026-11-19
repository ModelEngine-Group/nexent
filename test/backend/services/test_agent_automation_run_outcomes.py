# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run status and identity must survive failures after message creation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test.backend.services.test_agent_automation_runner import _base_task, _load_runner_with_stubs


@pytest.fixture
def execution(monkeypatch):
    module = _load_runner_with_stubs(monkeypatch)
    stored = {}

    def create(values, user_id):
        stored.update(run_id=1, user_message_id=None, assistant_message_id=None, **values)
        return dict(stored)

    def update(run_id, values, user_id=None, expected_statuses=None, **kwargs):
        if expected_statuses and stored["status"] not in expected_statuses:
            return None
        stored.update(values)
        return dict(stored)

    def append(*args, run_id=None):
        if run_id is not None:
            stored["user_message_id"] = 101
        return {"user_message_id": 101, "assistant_message_index": 1, "history": []}

    def finish_prepared_run(run, run_values, task_values):
        assert task_values["last_run_status"] == run_values["status"]
        assert stored["projection_message_index"] is not None
        assert run_values["projection_message_index"] is None
        return update(run["run_id"], run_values, expected_statuses=[run["status"]])

    async def validate(*args, **kwargs):
        return {"available": True}

    monkeypatch.setattr(module, "validate_bindings_available", validate)
    monkeypatch.setattr(module.agent_automation_db, "has_active_run_for_conversation", lambda *a: False)
    monkeypatch.setattr(module.agent_automation_db, "create_run", create)
    monkeypatch.setattr(module.agent_automation_db, "update_run", update)
    monkeypatch.setattr(module.agent_automation_db, "get_run", lambda *a: dict(stored))
    monkeypatch.setattr(module.agent_automation_db, "get_task", lambda *a: _base_task())
    monkeypatch.setattr(module.agent_automation_db, "update_task", lambda *a, **k: {})
    monkeypatch.setattr(module.agent_automation_db, "finish_prepared_run", finish_prepared_run)
    monkeypatch.setattr(module, "automation_conversation_adapter", SimpleNamespace(
        append_run_prompt=append, append_run_assistant=lambda *a, **k: 202,
    ))
    return module, stored


@pytest.mark.asyncio
async def test_failed_execution_retains_prompt_link(monkeypatch, execution):
    module, stored = execution

    async def fail(*args, **kwargs):
        raise RuntimeError("controlled model failure")

    monkeypatch.setattr(module, "forward_tracked_background", fail)
    result = await module.AgentAutomationRunner().execute_task(_base_task(), trigger_type="MANUAL")
    assert result["status"] == "FAILED"
    assert result["user_message_id"] == 101
    assert result["assistant_message_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,persisted,expected", [
    ("completed", True, "SUCCEEDED"),
    ("failed", True, "FAILED"),
    ("completed", False, "FAILED"),
    (None, True, "FAILED"),
    ("stopped", True, "FAILED"),
])
async def test_runner_requires_completed_and_persisted_projection(monkeypatch, execution, status, persisted, expected):
    module, stored = execution

    client = SimpleNamespace(start_prepared_run=AsyncMock(
        side_effect=lambda *args: module.AgentRunReference(run_id=stored["runtime_run_id"], conversation_id=100),
    ))
    monkeypatch.setattr(module, "_agentos_client", lambda: client)
    monkeypatch.setattr(module, "prepare_conversation_snapshot", AsyncMock(return_value=SimpleNamespace(memory_enabled=False)))
    projection = module.ProjectedRun(202, status, 1) if persisted and status is not None else None
    monkeypatch.setattr(module.AgentAutomationRunner, "_project_prepared_run", AsyncMock(return_value=projection))
    result = await module.AgentAutomationRunner().execute_task(_base_task(), trigger_type="MANUAL")
    assert result["status"] == expected
    assert result["user_message_id"] == 101
    assert result["assistant_message_id"] == (202 if projection is not None else None)


@pytest.mark.asyncio
async def test_late_completed_result_does_not_override_cancel(monkeypatch, execution):
    module, stored = execution

    async def background(*args, **kwargs):
        stored.update(status="CANCELED", assistant_message_id=202)
        return SimpleNamespace(assistant_message_id=202, chunks=1)

    monkeypatch.setattr(module, "forward_tracked_background", background)
    result = await module.AgentAutomationRunner().execute_task(_base_task(), trigger_type="MANUAL")
    assert result["status"] == "CANCELED"
    assert result["user_message_id"] == 101
    assert result["assistant_message_id"] == 202
