# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run status and identity must survive failures after message creation."""

from types import SimpleNamespace

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
        return {"user_message_id": 101, "history": []}

    async def validate(*args, **kwargs):
        return {"available": True}

    monkeypatch.setattr(module, "validate_bindings_available", validate)
    monkeypatch.setattr(module.agent_automation_db, "has_active_run_for_conversation", lambda *a: False)
    monkeypatch.setattr(module.agent_automation_db, "create_run", create)
    monkeypatch.setattr(module.agent_automation_db, "update_run", update)
    monkeypatch.setattr(module.agent_automation_db, "get_run", lambda *a: dict(stored))
    monkeypatch.setattr(module.agent_automation_db, "update_task", lambda *a, **k: {})
    monkeypatch.setattr(module, "automation_conversation_adapter", SimpleNamespace(
        append_run_prompt=append, append_run_assistant=lambda *a, **k: 202,
    ))
    return module, stored


@pytest.mark.asyncio
async def test_failed_execution_retains_prompt_link(monkeypatch, execution):
    module, stored = execution

    async def fail(*args, **kwargs):
        raise RuntimeError("controlled model failure")

    monkeypatch.setattr(module, "run_agent_background", fail)
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
async def test_runner_uses_actual_background_result(monkeypatch, execution, status, persisted, expected):
    module, stored = execution

    async def background(*args, **kwargs):
        stored["assistant_message_id"] = 202
        return {"assistant_message_id": 202, "status": status, "persisted": persisted}

    monkeypatch.setattr(module, "run_agent_background", background)
    result = await module.AgentAutomationRunner().execute_task(_base_task(), trigger_type="MANUAL")
    assert result["status"] == expected
    assert result["user_message_id"] == 101
    assert result["assistant_message_id"] == 202


@pytest.mark.asyncio
async def test_late_completed_result_does_not_override_cancel(monkeypatch, execution):
    module, stored = execution

    async def background(*args, **kwargs):
        stored.update(status="CANCELED", assistant_message_id=202)
        return {"assistant_message_id": 202, "status": "completed", "persisted": True}

    monkeypatch.setattr(module, "run_agent_background", background)
    result = await module.AgentAutomationRunner().execute_task(_base_task(), trigger_type="MANUAL")
    assert result["status"] == "CANCELED"
    assert result["user_message_id"] == 101
    assert result["assistant_message_id"] == 202
