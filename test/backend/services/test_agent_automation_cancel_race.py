# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A losing cancellation must neither stop the conversation nor rewrite task state."""

from unittest.mock import Mock

import pytest

from management.services.automation import service


@pytest.mark.parametrize("winner", ["SUCCEEDED", "FAILED", "TIMEOUT", "CANCELED"])
def test_losing_cancel_returns_current_terminal_without_side_effects(monkeypatch, winner):
    active = dict(run_id=1, task_id=2, conversation_id=3, status="RUNNING")
    terminal = {**active, "status": winner}
    monkeypatch.setattr(service.agent_automation_db, "get_run", Mock(side_effect=[active, terminal]))
    from management.services.automation import runner
    monkeypatch.setattr(runner.agent_automation_runner, "cancel_run_by_user", Mock(return_value=(terminal, False)))
    update = Mock()
    monkeypatch.setattr(service.agent_automation_db, "update_task", update)
    facade = service.AgentAutomationFacade()
    monkeypatch.setattr(facade, "get_task", Mock(return_value={"task_id": 2}))
    stop = Mock()
    monkeypatch.setattr(facade, "_request_conversation_stop", stop)
    assert facade.cancel_run(1, "tenant", "owner") == terminal
    stop.assert_not_called()
    update.assert_not_called()


def test_winning_cancel_persists_before_stopping(monkeypatch):
    active = dict(run_id=1, task_id=2, conversation_id=3, status="RUNNING")
    monkeypatch.setattr(service.agent_automation_db, "get_run", lambda *a: active)
    events = []

    from management.services.automation import runner

    def cancel(*args):
        events.extend(["persist", "summary"])
        return {**active, "status": "CANCELED"}, True

    monkeypatch.setattr(runner.agent_automation_runner, "cancel_run_by_user", cancel)
    facade = service.AgentAutomationFacade()
    monkeypatch.setattr(facade, "get_task", Mock(return_value={"task_id": 2}))
    monkeypatch.setattr(facade, "_request_conversation_stop", lambda *a: events.append("stop"))
    assert facade.cancel_run(1, "tenant", "owner")["status"] == "CANCELED"
    assert events == ["persist", "summary", "stop"]
