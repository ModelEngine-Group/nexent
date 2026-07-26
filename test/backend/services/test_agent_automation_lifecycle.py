import os
import sys
from datetime import datetime, timezone

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.agent_automation import conversation_adapter as adapter_module
from services.agent_automation import facade as facade_module
from services.agent_automation import runner as runner_module
from services.agent_automation.facade import AgentAutomationFacade
from services.agent_automation.models import (
    AutomationProposalConfirmRequest,
    AutomationProposalCreateRequest,
    CapabilityResolution,
    CapabilityBinding,
    CapabilityType,
)
from services.agent_automation.prompt_generator import AutomationTaskContent


@pytest.mark.asyncio
async def test_chat_proposal_confirm_and_manual_run_share_one_conversation(monkeypatch):
    """Exercise the service lifecycle without sending the schedule command to the Agent."""
    messages = []
    proposals = {}
    tasks = {}
    runs = {}
    captured = {"agent_calls": 0}

    def fake_history(conversation_id, user_id):
        return [{"conversation_id": conversation_id, "message": messages}]

    def fake_save_message(request, user_id, tenant_id):
        message_id = len(messages) + 1
        units = [
            unit.model_dump() if hasattr(unit, "model_dump") else unit
            for unit in request.message
        ]
        messages.append({
            "message_id": message_id,
            "message_idx": request.message_idx,
            "role": request.role,
            "message": units,
        })
        return message_id

    def fake_save_message_unit(**kwargs):
        return 100 + kwargs["message_id"]

    monkeypatch.setattr(adapter_module, "get_conversation_history_service", fake_history)
    monkeypatch.setattr(adapter_module, "save_message", fake_save_message)
    monkeypatch.setattr(adapter_module, "save_message_unit", fake_save_message_unit)
    monkeypatch.setattr(adapter_module, "update_unit_content", lambda *args: None)
    monkeypatch.setattr(
        facade_module,
        "create_new_conversation",
        lambda title, user_id, agent_id=None: {
            "conversation_id": 321,
            "conversation_title": title,
            "agent_id": agent_id,
        },
    )
    monkeypatch.setattr(
        facade_module,
        "get_conversation",
        lambda conversation_id, user_id: {"conversation_id": conversation_id},
    )

    initial_resolution = CapabilityResolution(
        executable=True,
        matched_capabilities=[],
        agent_snapshot={
            "agent_id": 7,
            "name": "周报助手",
            "description": "整理项目进展",
        },
    )

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return initial_resolution

    async def fake_generate_task_content(context):
        return AutomationTaskContent(title="项目周报", instruction="整理一份项目周报")

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.automation_prompt_generator,
        "generate_task_content",
        fake_generate_task_content,
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_task_by_conversation",
        lambda conversation_id, user_id: next(
            (
                task
                for task in tasks.values()
                if task["conversation_id"] == conversation_id
                and task.get("status") != "DELETED"
            ),
            None,
        ),
    )

    def fake_create_proposal(values, user_id):
        proposal = {"proposal_id": 1, **values}
        proposals[1] = proposal
        return proposal

    def fake_update_proposal_task(proposal_id, tenant_id, user_id, proposed_task):
        proposals[proposal_id]["proposed_task"] = proposed_task
        return True

    def fake_update_proposal_status(proposal_id, tenant_id, user_id, status):
        proposals[proposal_id]["status"] = status
        return True

    def fake_create_task(values, user_id):
        task = {"task_id": 11, **values}
        tasks[11] = task
        return task

    monkeypatch.setattr(facade_module.agent_automation_db, "create_proposal", fake_create_proposal)
    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: proposals.get(1))
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal_task", fake_update_proposal_task)
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal_status", fake_update_proposal_status)
    monkeypatch.setattr(facade_module.agent_automation_db, "create_task", fake_create_task)

    service = AgentAutomationFacade()
    proposal = await service.create_proposal(
        AutomationProposalCreateRequest(
            agent_id=7,
            message="每周五上午9点发一个周报",
            model_id=55,
        ),
        "tenant",
        "user",
    )

    assert proposal["conversation_id"] == 321
    assert captured["agent_calls"] == 0
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["message"][0]["content"] == "每周五上午9点发一个周报"
    assert messages[1]["message"][0]["type"] == "automation_proposal"

    task = await service.confirm_proposal(
        proposal["proposal_id"],
        AutomationProposalConfirmRequest(),
        "tenant",
        "user",
    )

    assert task["conversation_id"] == 321
    assert task["agent_id"] == 7
    assert len(tasks) == 1

    latest_binding = CapabilityBinding(
        type=CapabilityType.TOOL,
        name="latest-search",
        binding_ref="tool:latest-search",
    )

    async def fake_validate_bindings_available(*args, **kwargs):
        return {
            "available": True,
            "unavailable_bindings": [],
            "resolution": {
                "agent_snapshot": {
                    "agent_id": 7,
                    "name": "最新周报助手",
                    "description": "使用最新配置整理管理周报",
                },
                "matched_capabilities": [latest_binding.model_dump(mode="json")],
            },
        }

    async def fake_run_agent_background(agent_request, user_id, tenant_id, skip_user_save=False):
        captured["agent_calls"] += 1
        captured["agent_request"] = agent_request
        messages.append({
            "message_id": len(messages) + 1,
            "message_idx": len(messages),
            "role": "assistant",
            "message": [{"type": "final_answer", "content": "本周管理周报"}],
        })
        return {"assistant_message_id": messages[-1]["message_id"]}

    def fake_create_run(values, user_id):
        run = {
            "run_id": 21,
            "started_at": datetime.now(timezone.utc),
            **values,
        }
        runs[21] = run
        return run

    def fake_update_run(run_id, values, user_id=None, expected_statuses=None):
        run = runs[run_id]
        if expected_statuses and run["status"] not in expected_statuses:
            return None
        run.update(values)
        return run

    def fake_update_task(task_id, tenant_id, user_id, values):
        tasks[task_id].update(values)
        return tasks[task_id]

    monkeypatch.setattr(runner_module, "validate_bindings_available", fake_validate_bindings_available)
    monkeypatch.setattr(runner_module, "run_agent_background", fake_run_agent_background)
    monkeypatch.setattr(runner_module, "is_agent_running", lambda *args: False)
    monkeypatch.setattr(runner_module, "get_conversation_history_service", fake_history)
    monkeypatch.setattr(runner_module, "save_message", fake_save_message)
    monkeypatch.setattr(runner_module, "save_message_unit", fake_save_message_unit)
    monkeypatch.setattr(runner_module.agent_automation_db, "has_active_run_for_conversation", lambda *args: False)
    monkeypatch.setattr(runner_module.agent_automation_db, "create_run", fake_create_run)
    monkeypatch.setattr(runner_module.agent_automation_db, "update_run", fake_update_run)
    monkeypatch.setattr(runner_module.agent_automation_db, "get_run", lambda *args: runs.get(21))
    monkeypatch.setattr(runner_module.agent_automation_db, "get_task", lambda *args: tasks.get(11))
    monkeypatch.setattr(runner_module.agent_automation_db, "update_task", fake_update_task)

    run = await runner_module.AgentAutomationRunner().execute_task(
        task,
        trigger_type="MANUAL",
    )

    assert run["status"] == "SUCCEEDED"
    assert captured["agent_calls"] == 1
    assert captured["agent_request"].conversation_id == 321
    assert captured["agent_request"].query == "整理一份项目周报"
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[2]["message"][0]["type"] == "string"
    assert messages[2]["message"][0]["content"] == run["generated_prompt"]
