from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from services.agent_automation import facade as facade_module
from services.agent_automation.errors import (
    AutomationCapabilityBindingInvalidError,
    AutomationCapabilityNotReadyError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
    AutomationScheduleInvalidError,
)
from services.agent_automation.facade import AgentAutomationFacade
from services.agent_automation.intent_analyzer import AutomationIntentContext
from services.agent_automation.models import (
    AutomationProposalCreateRequest,
    AutomationProposalPatchRequest,
    AutomationProposalConfirmRequest,
    AutomationProposalStatus,
    AutomationRunStatus,
    AutomationTaskCreateRequest,
    AutomationTaskPatchRequest,
    CapabilityBinding,
    CapabilityResolution,
    CapabilityType,
    ScheduleMode,
    ScheduleRuleType,
    ScheduleTrigger,
)
from services.agent_automation.prompt_generator import AutomationTaskContent


@pytest.mark.asyncio
async def test_create_proposal_rejects_ambiguous_schedule_before_creating_conversation(monkeypatch):
    created = False

    def fake_create_conversation(*args, **kwargs):
        nonlocal created
        created = True

    monkeypatch.setattr(facade_module, "create_new_conversation", fake_create_conversation)

    with pytest.raises(AutomationScheduleInvalidError, match="缺少可确定的日期或时间"):
        await AgentAutomationFacade().create_proposal(
            AutomationProposalCreateRequest(agent_id=7, message="每周发一个周报"),
            "tenant",
            "user",
        )

    assert created is False


@pytest.mark.asyncio
async def test_create_proposal_maps_invalid_date_to_schedule_error():
    with pytest.raises(AutomationScheduleInvalidError, match="无法解析任务执行时间"):
        await AgentAutomationFacade().create_proposal(
            AutomationProposalCreateRequest(
                agent_id=7,
                message="2026年2月30日上午9点提醒我提交报告",
            ),
            "tenant",
            "user",
        )


@pytest.mark.asyncio
async def test_create_proposal_generates_title_and_instruction_before_capability_resolution(monkeypatch):
    captured = {}

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(
            executable=True,
            matched_capabilities=[],
            agent_snapshot={"agent_id": 7, "name": "周报助手", "description": "整理项目进展"},
        )

    async def fake_generate_task_content(context):
        captured["context"] = context
        return AutomationTaskContent(title="生成周报", instruction="整理本周项目周报")

    monkeypatch.setattr(facade_module, "get_conversation", lambda conversation_id, user_id: {
        "conversation_id": conversation_id,
    })
    monkeypatch.setattr(
        facade_module,
        "update_conversation_agent_id_service",
        lambda conversation_id, agent_id, user_id: True,
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.automation_prompt_generator,
        "generate_task_content",
        fake_generate_task_content,
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "create_proposal",
        lambda values, user_id: {"proposal_id": 11, **values},
    )
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "append_proposal_exchange",
        lambda conversation_id, user_instruction, payload, user_id, tenant_id: {
            "message_id": 31,
            "unit_id": 41,
        },
    )

    def fake_update_proposal_task(proposal_id, tenant_id, user_id, proposed_task):
        captured["stored_task"] = proposed_task
        return True

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_proposal_task",
        fake_update_proposal_task,
    )

    result = await AgentAutomationFacade().create_proposal(
        AutomationProposalCreateRequest(
            conversation_id=100,
            agent_id=7,
            message="每周五上午9点发一个周报",
        ),
        "tenant",
        "user",
    )

    assert result["task"]["title"] == "生成周报"
    assert result["task"]["instruction"] == "整理本周项目周报"
    assert result["task"]["original_instruction"] == "发一个周报"
    assert captured["context"].instruction == "发一个周报"
    assert captured["stored_task"]["_conversation_message_id"] == 31
    assert captured["stored_task"]["_conversation_unit_id"] == 41


@pytest.mark.asyncio
async def test_create_proposal_creates_conversation_only_for_automation_intent(monkeypatch):
    captured = {}

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(
            executable=True,
            agent_snapshot={"agent_id": 7, "name": "周报助手"},
        )

    async def fake_generate_task_content(context):
        captured["prompt_instruction"] = context.instruction
        return AutomationTaskContent(title=context.instruction, instruction=context.instruction)

    monkeypatch.setattr(
        facade_module,
        "create_new_conversation",
        lambda title, user_id, agent_id=None: captured.setdefault(
            "conversation",
            {
                "conversation_id": 321,
                "conversation_title": title,
                "agent_id": agent_id,
            },
        ),
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.automation_prompt_generator,
        "generate_task_content",
        fake_generate_task_content,
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "create_proposal",
        lambda values, user_id: {"proposal_id": 12, **values},
    )
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "append_proposal_exchange",
        lambda *args: {"message_id": 31, "unit_id": 41},
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal_task", lambda *args: True)

    ordinary = await AgentAutomationFacade().create_proposal(
        AutomationProposalCreateRequest(agent_id=7, message="今天项目进展如何"),
        "tenant",
        "user",
    )
    assert ordinary["proposal_id"] is None
    assert "conversation" not in captured

    proposal = await AgentAutomationFacade().create_proposal(
        AutomationProposalCreateRequest(agent_id=7, message="每分钟给我发一句你好"),
        "tenant",
        "user",
    )
    assert proposal["conversation_id"] == 321
    assert proposal["task"]["schedule_trigger"]["rule_type"] == "INTERVAL"
    assert proposal["task"]["schedule_trigger"]["interval_seconds"] == 60
    assert proposal["task"]["instruction"] == "发一句你好"
    assert captured["prompt_instruction"] == "发一句你好"
    assert captured["conversation"]["conversation_title"] == "发一句你好"
    assert captured["conversation"]["agent_id"] == 7


@pytest.mark.asyncio
async def test_create_proposal_uses_llm_structured_content_without_second_prompt_call(monkeypatch):
    captured = {}
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="Asia/Shanghai",
        start_at=datetime(2026, 7, 13, 10, 0, tzinfo=timezone(timedelta(hours=8))),
        cron_expr="0 8 * * *",
    )

    async def fake_analyze(context: AutomationIntentContext):
        captured["analysis_context"] = context
        return {
            "is_automation_intent": True,
            "confidence": 0.99,
            "title": "查询黄历",
            "instruction": "查询当天的黄历信息",
            "schedule_trigger": trigger,
            "schedule_error": None,
            "analysis_source": "llm",
            "task_content_generated": True,
            "task_content_source": "llm",
        }

    async def fail_second_prompt_call(context):
        raise AssertionError("LLM intent analysis must not trigger a second title/prompt call")

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(executable=True, agent_snapshot={"agent_id": 7})

    monkeypatch.setattr(facade_module.automation_intent_analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(
        facade_module.automation_prompt_generator,
        "generate_task_content",
        fail_second_prompt_call,
    )
    monkeypatch.setattr(
        facade_module,
        "get_conversation",
        lambda conversation_id, user_id: {"conversation_id": conversation_id},
    )
    monkeypatch.setattr(facade_module, "update_conversation_agent_id_service", lambda *args: True)
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "create_proposal",
        lambda values, user_id: {"proposal_id": 15, **values},
    )
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "append_proposal_exchange",
        lambda *args: {"message_id": 31, "unit_id": 41},
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal_task", lambda *args: True)

    result = await AgentAutomationFacade().create_proposal(
        AutomationProposalCreateRequest(
            conversation_id=100,
            agent_id=7,
            model_id=42,
            message="每天早上八点算一下当天的黄历信息",
        ),
        "tenant",
        "user",
    )

    assert result["intent_analysis_source"] == "llm"
    assert result["task_content_source"] == "llm"
    assert result["task"]["title"] == "查询黄历"
    assert result["task"]["instruction"] == "查询当天的黄历信息"
    assert result["task"]["schedule_trigger"]["cron_expr"] == "0 8 * * *"
    assert captured["analysis_context"].model_id == 42


@pytest.mark.asyncio
async def test_confirm_proposal_updates_persisted_conversation_card(monkeypatch):
    captured = {}

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(executable=True)

    proposal = {
        "proposal_id": 10,
        "tenant_id": "tenant",
        "user_id": "user",
        "conversation_id": 100,
        "agent_id": 7,
        "status": AutomationProposalStatus.PENDING.value,
        "capability_resolution": {"executable": True},
        "proposed_task": {
            "title": "周报",
            "instruction": "请整理本周周报",
            "original_instruction": "发一个周报",
            "agent_version_no": None,
            "_conversation_unit_id": 41,
            "schedule_trigger": {
                "mode": "ONCE",
                "rule_type": "AT",
                "timezone": "Asia/Shanghai",
                "start_at": "2030-01-01T09:00:00+08:00",
            },
        },
    }
    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: proposal)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_proposal_status",
        lambda *args: True,
    )
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "update_proposal",
        lambda unit_id, payload, user_id: captured.update({
            "unit_id": unit_id,
            "payload": payload,
        }),
    )

    service = AgentAutomationFacade()

    async def fake_create_task(request, tenant_id, user_id):
        captured["create_request"] = request
        return {"task_id": 99}

    monkeypatch.setattr(service, "create_task", fake_create_task)

    result = await service.confirm_proposal(
        10,
        AutomationProposalConfirmRequest(),
        "tenant",
        "user",
    )

    assert result["task_id"] == 99
    assert captured["create_request"].conversation_id == 100
    assert captured["create_request"].original_instruction == "发一个周报"
    assert captured["unit_id"] == 41
    assert captured["payload"]["confirmed_task_id"] == 99
    assert "_conversation_unit_id" not in captured["payload"]["task"]


@pytest.mark.asyncio
async def test_update_proposal_revalidates_and_persists_card(monkeypatch):
    captured = {}
    proposal = {
        "proposal_id": 10,
        "tenant_id": "tenant",
        "user_id": "user",
        "conversation_id": 100,
        "agent_id": 7,
        "status": AutomationProposalStatus.PENDING.value,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "proposed_task": {
            "title": "旧标题",
            "instruction": "旧指令",
            "agent_version_no": None,
            "_conversation_unit_id": 41,
            "schedule_trigger": {
                "mode": "ONCE",
                "rule_type": "AT",
                "timezone": "Asia/Shanghai",
                "start_at": "2030-01-01T09:00:00+08:00",
            },
        },
    }

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        captured["resolved_instruction"] = kwargs["instruction"]
        return CapabilityResolution(executable=True)

    def fake_update_proposal(proposal_id, tenant_id, user_id, proposed_task, capability_resolution):
        captured["stored_task"] = proposed_task
        captured["capability_resolution"] = capability_resolution
        return True

    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: proposal)
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal", fake_update_proposal)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "update_proposal",
        lambda unit_id, payload, user_id: captured.update({"unit_id": unit_id, "payload": payload}),
    )

    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="Asia/Shanghai",
        start_at=datetime(2030, 1, 1, 10, 0, tzinfo=timezone(timedelta(hours=8))),
        cron_expr="0 10 * * *",
    )
    result = await AgentAutomationFacade().update_proposal(
        10,
        AutomationProposalPatchRequest(
            title="新标题",
            instruction="新指令",
            schedule_trigger=trigger,
        ),
        "tenant",
        "user",
    )

    assert result["task"]["title"] == "新标题"
    assert result["task"]["schedule_trigger"]["cron_expr"] == "0 10 * * *"
    assert captured["resolved_instruction"] == "新指令"
    assert captured["stored_task"]["_conversation_unit_id"] == 41
    assert captured["unit_id"] == 41
    assert "_conversation_unit_id" not in captured["payload"]["task"]


@pytest.mark.asyncio
async def test_update_confirmed_proposal_updates_task_and_persisted_card(monkeypatch):
    captured = {}
    proposal = {
        "proposal_id": 10,
        "tenant_id": "tenant",
        "user_id": "user",
        "conversation_id": 100,
        "agent_id": 7,
        "status": AutomationProposalStatus.ACCEPTED.value,
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "capability_resolution": {"executable": True},
        "proposed_task": {
            "title": "旧标题",
            "instruction": "旧指令",
            "agent_version_no": None,
            "_conversation_unit_id": 41,
            "schedule_trigger": {
                "mode": "ONCE",
                "rule_type": "AT",
                "timezone": "Asia/Shanghai",
                "start_at": "2030-01-01T09:00:00+08:00",
            },
        },
    }
    facade = AgentAutomationFacade()

    async def fake_patch_task(task_id, request, tenant_id, user_id):
        captured["task_patch"] = request
        return {
            "task_id": task_id,
            "capability_requirements": {"executable": True},
        }

    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: proposal)
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal", lambda *args: True)
    monkeypatch.setattr(facade, "get_task_for_conversation", lambda *args: {"task_id": 22})
    monkeypatch.setattr(facade, "patch_task", fake_patch_task)
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "update_proposal",
        lambda unit_id, payload, user_id: captured.update({"unit_id": unit_id, "payload": payload}),
    )

    result = await facade.update_proposal(
        10,
        AutomationProposalPatchRequest(title="新标题"),
        "tenant",
        "user",
    )

    assert captured["task_patch"].title == "新标题"
    assert result["confirmed_task_id"] == 22
    assert result["task"]["title"] == "新标题"
    assert captured["payload"]["confirmed_task_id"] == 22


@pytest.mark.asyncio
async def test_confirm_proposal_rejects_missing_capabilities(monkeypatch):
    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(
            executable=False,
            missing_capabilities=[{"type": "TOOL", "name": "search"}],
        )

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_proposal",
        lambda proposal_id, tenant_id, user_id: {
            "proposal_id": proposal_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "conversation_id": 100,
            "agent_id": 1,
            "status": AutomationProposalStatus.PENDING.value,
            "proposed_task": {
                "title": "每日检索",
                "instruction": "每天检索项目动态",
                "agent_version_no": None,
                "schedule_trigger": {
                    "mode": "ONCE",
                    "rule_type": "AT",
                    "timezone": "Asia/Shanghai",
                    "start_at": "2030-01-01T09:00:00+08:00",
                },
            },
        },
    )
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)

    with pytest.raises(AutomationCapabilityNotReadyError):
        await AgentAutomationFacade().confirm_proposal(
            10,
            AutomationProposalConfirmRequest(),
            "tenant",
            "user",
        )


@pytest.mark.asyncio
async def test_confirm_proposal_rejects_and_marks_expired_proposal(monkeypatch):
    statuses = []
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_proposal",
        lambda *args: {
            "proposal_id": 10,
            "status": AutomationProposalStatus.PENDING.value,
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_proposal_status",
        lambda proposal_id, tenant_id, user_id, status: statuses.append(status) or True,
    )

    with pytest.raises(AutomationNotFoundError, match="expired"):
        await AgentAutomationFacade().confirm_proposal(
            10,
            AutomationProposalConfirmRequest(),
            "tenant",
            "user",
        )

    assert statuses == [AutomationProposalStatus.EXPIRED.value]


def test_cancel_run_marks_running_run_canceled(monkeypatch):
    stopped = {}

    def fake_stop(conversation_id, user_id):
        stopped["conversation_id"] = conversation_id
        stopped["user_id"] = user_id

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_run",
        lambda run_id, tenant_id, user_id: {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "task_id": 88,
            "conversation_id": 99,
            "status": AutomationRunStatus.RUNNING.value,
        },
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "cancel_run",
        lambda run_id, tenant_id, user_id, reason: {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": AutomationRunStatus.CANCELED.value,
            "error_message": reason,
        },
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: {"task_id": task_id, **values},
    )

    service = AgentAutomationFacade()
    monkeypatch.setattr(service, "_request_conversation_stop", fake_stop)

    canceled = service.cancel_run(7, "tenant", "user")

    assert canceled["status"] == AutomationRunStatus.CANCELED.value
    assert stopped == {"conversation_id": 99, "user_id": "user"}


def test_delete_run_soft_deletes_terminal_record_and_refreshes_latest_result(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_run",
        lambda run_id, tenant_id, user_id: {
            "run_id": run_id,
            "task_id": 88,
            "status": AutomationRunStatus.SUCCEEDED.value,
        },
    )

    def fake_soft_delete_run(run_id, tenant_id, user_id, expected_statuses):
        captured["deleted"] = (run_id, tenant_id, user_id)
        captured["expected_statuses"] = set(expected_statuses)
        return {"run_id": run_id, "delete_flag": "Y"}

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "soft_delete_run",
        fake_soft_delete_run,
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "list_runs",
        lambda task_id, tenant_id, user_id, limit=50: [
            {
                "status": AutomationRunStatus.FAILED.value,
                "error_message": "previous failure",
            }
        ],
    )

    def fake_update_task(task_id, tenant_id, user_id, values):
        captured["task_update"] = (task_id, tenant_id, user_id, values)
        return {"task_id": task_id, **values}

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_task",
        fake_update_task,
    )

    assert AgentAutomationFacade().delete_run(7, "tenant", "user") is True
    assert captured["deleted"] == (7, "tenant", "user")
    assert AutomationRunStatus.RUNNING.value not in captured["expected_statuses"]
    assert captured["task_update"] == (
        88,
        "tenant",
        "user",
        {
            "last_run_status": AutomationRunStatus.FAILED.value,
            "last_error": "previous failure",
        },
    )


def test_delete_run_rejects_active_record(monkeypatch):
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_run",
        lambda run_id, tenant_id, user_id: {
            "run_id": run_id,
            "task_id": 88,
            "status": AutomationRunStatus.RUNNING.value,
        },
    )

    with pytest.raises(AutomationScheduleInvalidError, match="canceled before deletion"):
        AgentAutomationFacade().delete_run(7, "tenant", "user")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("schedule_trigger", "expected_misfire_policy"),
    [
        (
            ScheduleTrigger(
                mode=ScheduleMode.ONCE,
                rule_type=ScheduleRuleType.AT,
                timezone="Asia/Shanghai",
                start_at="2030-01-01T09:00:00+08:00",
            ),
            "RUN_ONCE",
        ),
        (
            ScheduleTrigger(
                mode=ScheduleMode.RECURRING,
                rule_type=ScheduleRuleType.CRON,
                timezone="Asia/Shanghai",
                start_at="2030-01-01T09:00:00+08:00",
                cron_expr="0 9 * * *",
            ),
            "SKIP",
        ),
    ],
)
async def test_create_task_requires_and_reuses_bound_conversation(
    monkeypatch,
    schedule_trigger,
    expected_misfire_policy,
):
    created_task = {}

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(
            executable=True,
            matched_capabilities=[],
            agent_snapshot={"agent_id": 3},
        )

    monkeypatch.setattr(facade_module, "get_conversation", lambda conversation_id, user_id: {
        "conversation_id": conversation_id,
    })
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_task_by_conversation",
        lambda conversation_id, user_id: None,
    )
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(3, 0): "销售助手"},
    )

    def fake_create_task(task_data, user_id):
        created_task.update(task_data)
        return {"task_id": 1, **task_data}

    monkeypatch.setattr(facade_module.agent_automation_db, "create_task", fake_create_task)

    task = await AgentAutomationFacade().create_task(
        AutomationTaskCreateRequest(
            title="销售线索日报",
            agent_id=3,
            instruction="总结销售线索变化",
            conversation_id=123,
            original_instruction="总结销售线索变化",
            model_id=55,
            tool_params={"tools": {"search": {"top_k": 5}}},
            schedule_trigger=schedule_trigger,
        ),
        "tenant",
        "user",
    )

    assert task["conversation_id"] == 123
    assert task["status"] == "ACTIVE"
    assert created_task["misfire_policy"] == expected_misfire_policy
    assert created_task["runtime_snapshot"] == {
        "agent_id": 3,
        "display_name": "Agent #3",
        "model_id": 55,
        "tool_params": {"tools": {"search": {"top_k": 5}}},
        "original_instruction": "总结销售线索变化",
    }


def test_conversation_deleted_soft_deletes_task_and_cancels_runs(monkeypatch):
    events = []

    service = AgentAutomationFacade()
    monkeypatch.setattr(
        service,
        "_cancel_active_runs_for_conversation",
        lambda conversation_id, user_id, reason: events.append((conversation_id, user_id, reason)),
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "soft_delete_task_by_conversation",
        lambda conversation_id, user_id: 1,
    )

    deleted_count = service.on_conversation_deleted(77, "user")

    assert deleted_count == 1
    assert events == [(77, "user", "Conversation was deleted.")]


def test_list_tasks_enriches_agent_display_name(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "list_tasks",
        lambda tenant_id, user_id, status, search: captured.update(status=status) or [
            {
                "task_id": 1,
                "agent_id": 3,
                "agent_version_no": 0,
                "runtime_snapshot": {"name": "weather_query_assistant"},
            }
        ],
    )
    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(3, 0): "天气查询助手"},
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_active_run_task_ids",
        lambda task_ids, tenant_id, user_id: {1},
    )

    tasks = AgentAutomationFacade().list_tasks(
        "tenant",
        "user",
        status="RUNNING",
        search="天气",
        agent_name="查询助",
    )

    assert tasks[0]["agent_name"] == "天气查询助手"
    assert tasks[0]["is_running"] is True
    assert captured["status"] is None


def test_list_tasks_enabled_filter_excludes_active_runs(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "list_tasks",
        lambda tenant_id, user_id, status, search: captured.update(status=status) or [
            {"task_id": 1, "agent_id": 3, "agent_version_no": 0},
            {"task_id": 2, "agent_id": 4, "agent_version_no": 0},
        ],
    )
    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(3, 0): "天气助手", (4, 0): "周报助手"},
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_active_run_task_ids",
        lambda task_ids, tenant_id, user_id: {2},
    )

    tasks = AgentAutomationFacade().list_tasks("tenant", "user", status="ENABLED")

    assert captured["status"] == "ACTIVE"
    assert [task["task_id"] for task in tasks] == [1]
    assert tasks[0]["is_running"] is False


@pytest.mark.asyncio
async def test_create_task_maps_unique_conversation_race_to_domain_conflict(monkeypatch):
    class _Diag:
        constraint_name = "uq_agent_automation_conversation_active"

    class _OriginalError(Exception):
        diag = _Diag()

    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(executable=True)

    monkeypatch.setattr(
        facade_module,
        "get_conversation",
        lambda conversation_id, user_id: {"conversation_id": conversation_id},
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "create_task",
        lambda *args: (_ for _ in ()).throw(
            IntegrityError("INSERT", {}, _OriginalError("duplicate"))
        ),
    )

    with pytest.raises(AutomationConversationAlreadyBoundError):
        await AgentAutomationFacade().create_task(
            AutomationTaskCreateRequest(
                title="周报",
                agent_id=3,
                instruction="生成周报",
                conversation_id=123,
                schedule_trigger=ScheduleTrigger(
                    mode=ScheduleMode.ONCE,
                    rule_type=ScheduleRuleType.AT,
                    timezone="Asia/Shanghai",
                    start_at="2030-01-01T09:00:00+08:00",
                ),
            ),
            "tenant",
            "user",
        )


def test_completed_once_task_cannot_be_resumed(monkeypatch):
    service = AgentAutomationFacade()
    monkeypatch.setattr(
        service,
        "get_task",
        lambda task_id, tenant_id, user_id: {
            "task_id": task_id,
            "fire_count": 1,
            "schedule_config": {
                "mode": "ONCE",
                "rule_type": "AT",
                "timezone": "Asia/Shanghai",
                "start_at": "2030-01-01T09:00:00+08:00",
            },
        },
    )

    with pytest.raises(AutomationScheduleInvalidError, match="no future fire time"):
        service.resume_task(1, "tenant", "user")


@pytest.mark.asyncio
async def test_create_task_rejects_interval_shorter_than_backend_minimum(monkeypatch):
    async def fake_resolve_agent_capabilities(*args, **kwargs):
        return CapabilityResolution(executable=True)

    monkeypatch.setattr(
        facade_module,
        "get_conversation",
        lambda conversation_id, user_id: {"conversation_id": conversation_id},
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_task_by_conversation",
        lambda conversation_id, user_id: None,
    )
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve_agent_capabilities)

    with pytest.raises(AutomationScheduleInvalidError):
        await AgentAutomationFacade().create_task(
            AutomationTaskCreateRequest(
                title="短周期任务",
                agent_id=3,
                instruction="频繁执行",
                conversation_id=123,
                schedule_trigger=ScheduleTrigger(
                    mode=ScheduleMode.RECURRING,
                    rule_type=ScheduleRuleType.INTERVAL,
                    timezone="Asia/Shanghai",
                    start_at="2030-01-01T09:00:00+08:00",
                    interval_seconds=4,
                ),
            ),
            "tenant",
            "user",
        )


@pytest.mark.asyncio
async def test_create_task_rejects_past_once_schedule_before_external_lookups(monkeypatch):
    looked_up = False

    def fake_get_conversation(*args):
        nonlocal looked_up
        looked_up = True

    monkeypatch.setattr(facade_module, "get_conversation", fake_get_conversation)

    with pytest.raises(AutomationScheduleInvalidError, match="must be in the future"):
        await AgentAutomationFacade().create_task(
            AutomationTaskCreateRequest(
                title="过期任务",
                agent_id=3,
                instruction="发送提醒",
                conversation_id=123,
                schedule_trigger=ScheduleTrigger(
                    mode=ScheduleMode.ONCE,
                    rule_type=ScheduleRuleType.AT,
                    timezone="Asia/Shanghai",
                    start_at="2020-01-01T09:00:00+08:00",
                ),
            ),
            "tenant",
            "user",
        )

    assert looked_up is False


@pytest.mark.asyncio
async def test_patch_task_updates_schedule_runtime_and_capabilities(monkeypatch):
    service = AgentAutomationFacade()
    task = {
        "task_id": 1,
        "conversation_id": 9,
        "agent_id": 3,
        "agent_version_no": 2,
        "title": "old",
        "instruction": "old instruction",
        "fire_count": 4,
        "runtime_snapshot": {"name": "assistant", "model_id": 1},
    }
    updated_values = {}
    binding = CapabilityBinding(
        type=CapabilityType.TOOL,
        name="web_search",
        display_name="web_search",
        binding_ref="tool:web_search",
    )
    resolution = CapabilityResolution(
        executable=True,
        matched_capabilities=[binding],
        agent_snapshot={"name": "assistant-v2", "display_name": "助手 V2"},
    )

    monkeypatch.setattr(service, "get_task", lambda *args: task)

    async def fake_resolve(*args, **kwargs):
        return resolution

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", fake_resolve)
    monkeypatch.setattr(
        facade_module,
        "compute_next_fire_at",
        lambda trigger, now, fire_count: datetime(2030, 1, 1, 1, 1, tzinfo=timezone.utc),
    )

    def fake_update(task_id, tenant_id, user_id, values):
        updated_values.update(values)
        return {**task, **values}

    monkeypatch.setattr(facade_module.agent_automation_db, "update_task", fake_update)
    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(3, 2): "助手 V2"},
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_active_run_task_ids",
        lambda task_ids, tenant_id, user_id: set(),
    )

    result = await service.patch_task(
        1,
        AutomationTaskPatchRequest(
            title="new",
            instruction="new instruction",
            timeout_seconds=60,
            model_id=8,
            tool_params={"top_k": 3},
            capability_bindings=[binding],
            schedule_trigger=ScheduleTrigger(
                mode=ScheduleMode.RECURRING,
                rule_type=ScheduleRuleType.INTERVAL,
                timezone="UTC",
                start_at="2030-01-01T00:00:00+00:00",
                interval_seconds=60,
            ),
        ),
        "tenant",
        "user",
    )

    assert result["title"] == "new"
    assert result["agent_name"] == "助手 V2"
    assert updated_values["schedule_mode"] == "RECURRING"
    assert updated_values["schedule_rule_type"] == "INTERVAL"
    assert updated_values["capability_bindings"][0]["binding_ref"] == "tool:web_search"
    assert updated_values["runtime_snapshot"]["model_id"] == 8
    assert updated_values["runtime_snapshot"]["tool_params"] == {"top_k": 3}
    assert updated_values["runtime_snapshot"]["original_instruction"] == "new instruction"


@pytest.mark.asyncio
async def test_patch_task_rejects_unready_capabilities_and_lost_update(monkeypatch):
    service = AgentAutomationFacade()
    task = {
        "task_id": 1,
        "agent_id": 3,
        "instruction": "old",
        "runtime_snapshot": {},
    }
    monkeypatch.setattr(service, "get_task", lambda *args: task)

    async def unavailable(*args, **kwargs):
        return CapabilityResolution(
            executable=False,
            missing_capabilities=[{"name": "web_search"}],
        )

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", unavailable)
    with pytest.raises(AutomationCapabilityNotReadyError):
        await service.patch_task(
            1,
            AutomationTaskPatchRequest(instruction="search news"),
            "tenant",
            "user",
        )

    async def available(*args, **kwargs):
        return CapabilityResolution(executable=True)

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", available)
    monkeypatch.setattr(facade_module.agent_automation_db, "update_task", lambda *args: None)
    with pytest.raises(AutomationNotFoundError):
        await service.patch_task(
            1,
            AutomationTaskPatchRequest(instruction="plain task"),
            "tenant",
            "user",
        )


@pytest.mark.asyncio
async def test_task_management_methods_cover_successful_lifecycle(monkeypatch):
    service = AgentAutomationFacade()
    task = {
        "task_id": 1,
        "conversation_id": 9,
        "agent_id": 3,
        "agent_version_no": 0,
        "instruction": "run",
        "fire_count": 0,
        "schedule_config": {
            "mode": "RECURRING",
            "rule_type": "INTERVAL",
            "timezone": "UTC",
            "start_at": "2030-01-01T00:00:00+00:00",
            "interval_seconds": 60,
        },
    }
    updates = []
    canceled = []

    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(3, 0): "助手"},
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_active_run_task_ids",
        lambda task_ids, tenant_id, user_id: set(),
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task", lambda *args: task)

    def fake_update(task_id, tenant_id, user_id, values):
        updates.append(values)
        return {**task, **values}

    monkeypatch.setattr(facade_module.agent_automation_db, "update_task", fake_update)
    monkeypatch.setattr(
        facade_module,
        "compute_next_fire_at",
        lambda trigger, now, fire_count: datetime(2030, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        service,
        "_cancel_active_runs_for_conversation",
        lambda conversation_id, user_id, reason: canceled.append((conversation_id, reason)),
    )
    monkeypatch.setattr(facade_module.agent_automation_db, "soft_delete_task", lambda *args: True)
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "list_runs",
        lambda *args, **kwargs: [{"run_id": 5}],
    )

    async def fake_execute(task_payload, trigger_type):
        return {"run_id": 5, "trigger_type": trigger_type}

    monkeypatch.setattr(
        "services.agent_automation.runner.agent_automation_runner.execute_task",
        fake_execute,
    )

    assert service.get_task(1, "tenant", "user")["agent_name"] == "助手"
    assert service.pause_task(1, "tenant", "user")["status"] == "PAUSED"
    assert service.resume_task(1, "tenant", "user")["status"] == "ACTIVE"
    assert service.list_runs(1, "tenant", "user") == [{"run_id": 5}]
    assert (await service.run_task_now(1, "tenant", "user"))["trigger_type"] == "MANUAL"
    assert service.delete_task(1, "tenant", "user") is True
    assert canceled == [(9, "Automation task was deleted.")]
    assert any(update.get("next_fire_at") for update in updates)


def test_task_management_methods_cover_not_found_paths(monkeypatch):
    service = AgentAutomationFacade()
    monkeypatch.setattr(facade_module.agent_automation_db, "get_task", lambda *args: None)
    with pytest.raises(AutomationNotFoundError):
        service.get_task(1, "tenant", "user")

    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)
    assert service.get_task_for_conversation(9, "tenant", "user") is None

    monkeypatch.setattr(facade_module.agent_automation_db, "update_task", lambda *args: None)
    with pytest.raises(AutomationNotFoundError):
        service.pause_task(1, "tenant", "user")

    monkeypatch.setattr(service, "get_task", lambda *args: {
        "task_id": 1,
        "schedule_config": {
            "mode": "RECURRING",
            "rule_type": "INTERVAL",
            "timezone": "UTC",
            "start_at": "2030-01-01T00:00:00+00:00",
            "interval_seconds": 60,
        },
        "fire_count": 0,
    })
    monkeypatch.setattr(
        facade_module,
        "compute_next_fire_at",
        lambda trigger, now, fire_count: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AutomationNotFoundError):
        service.resume_task(1, "tenant", "user")


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_context_capabilities_and_binding(monkeypatch):
    service = AgentAutomationFacade()
    request = AutomationTaskCreateRequest(
        title="task",
        agent_id=3,
        instruction="search news",
        conversation_id=9,
        schedule_trigger=ScheduleTrigger(
            mode=ScheduleMode.ONCE,
            rule_type=ScheduleRuleType.AT,
            timezone="UTC",
            start_at="2030-01-01T00:00:00+00:00",
        ),
    )

    monkeypatch.setattr(facade_module, "get_conversation", lambda *args: None)
    with pytest.raises(AutomationNotFoundError):
        await service.create_task(request, "tenant", "user")

    monkeypatch.setattr(facade_module, "get_conversation", lambda *args: {"conversation_id": 9})
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_task_by_conversation",
        lambda *args: {"task_id": 1},
    )
    with pytest.raises(AutomationConversationAlreadyBoundError):
        await service.create_task(request, "tenant", "user")

    monkeypatch.setattr(facade_module.agent_automation_db, "get_task_by_conversation", lambda *args: None)

    async def unavailable(*args, **kwargs):
        return CapabilityResolution(executable=False)

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", unavailable)
    with pytest.raises(AutomationCapabilityNotReadyError):
        await service.create_task(request, "tenant", "user")

    binding = CapabilityBinding(
        type=CapabilityType.TOOL,
        name="removed",
        binding_ref="tool:removed",
    )
    request.capability_bindings = [binding]

    async def available(*args, **kwargs):
        return CapabilityResolution(executable=True, matched_capabilities=[binding])

    async def invalid_binding(*args, **kwargs):
        return {"unavailable_bindings": [binding.model_dump(mode="json")]}

    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", available)
    monkeypatch.setattr(facade_module, "validate_bindings_available", invalid_binding)
    with pytest.raises(AutomationCapabilityBindingInvalidError):
        await service.create_task(request, "tenant", "user")


def test_enrichment_and_cancellation_tolerate_optional_failures(monkeypatch):
    service = AgentAutomationFacade()
    assert facade_module._enrich_tasks_with_agent_names([], "tenant", "user") == []
    monkeypatch.setattr(
        facade_module.agent_identity_adapter,
        "resolve_agent_display_names",
        lambda *args: (_ for _ in ()).throw(RuntimeError("identity unavailable")),
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_active_run_task_ids",
        lambda *args: (_ for _ in ()).throw(RuntimeError("run lookup unavailable")),
    )
    enriched = facade_module._enrich_tasks_with_agent_names(
        [{"task_id": 1, "agent_id": 3, "runtime_snapshot": {}}],
        "tenant",
        "user",
    )
    assert enriched[0]["agent_name"] == "Agent #3"
    assert enriched[0]["is_running"] is False

    monkeypatch.setattr(
        "services.agent_automation.runner.agent_automation_runner.cancel_for_conversation",
        lambda *args: (_ for _ in ()).throw(RuntimeError("runner unavailable")),
    )
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "cancel_runs_by_conversation",
        lambda *args: 0,
    )
    service._cancel_active_runs_for_conversation(9, "user", "cleanup")


def test_facade_helpers_and_run_deletion_errors_cover_boundary_paths(monkeypatch):
    service = AgentAutomationFacade()
    assert facade_module._as_utc("2030-01-01T00:00:00Z") == datetime(
        2030,
        1,
        1,
        tzinfo=timezone.utc,
    )
    assert facade_module._json("plain") == "plain"
    with pytest.raises(AutomationScheduleInvalidError, match="cron expression"):
        facade_module._validate_schedule_policy(ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.CRON,
            timezone="UTC",
            start_at="2030-01-01T00:00:00+00:00",
            cron_expr="invalid cron",
        ))

    monkeypatch.setattr(facade_module.agent_automation_db, "get_run", lambda *args: None)
    with pytest.raises(AutomationNotFoundError):
        service.cancel_run(1, "tenant", "user")
    with pytest.raises(AutomationNotFoundError):
        service.delete_run(1, "tenant", "user")

    terminal_run = {
        "run_id": 1,
        "task_id": 2,
        "conversation_id": 9,
        "status": AutomationRunStatus.SUCCEEDED.value,
    }
    monkeypatch.setattr(facade_module.agent_automation_db, "get_run", lambda *args: terminal_run)
    assert service.cancel_run(1, "tenant", "user") == terminal_run
    monkeypatch.setattr(facade_module.agent_automation_db, "soft_delete_run", lambda *args: None)
    with pytest.raises(AutomationNotFoundError, match="no longer deletable"):
        service.delete_run(1, "tenant", "user")

    monkeypatch.setattr(service, "get_task", lambda *args: {"task_id": 2, "conversation_id": 9})
    monkeypatch.setattr(service, "_cancel_active_runs_for_conversation", lambda *args: None)
    monkeypatch.setattr(facade_module.agent_automation_db, "soft_delete_task", lambda *args: False)
    with pytest.raises(AutomationNotFoundError):
        service.delete_task(2, "tenant", "user")


@pytest.mark.asyncio
async def test_update_proposal_covers_not_editable_expired_and_missing_task_paths(monkeypatch):
    service = AgentAutomationFacade()
    request = AutomationProposalPatchRequest(title="updated")

    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: None)
    with pytest.raises(AutomationNotFoundError, match="not editable"):
        await service.update_proposal(1, request, "tenant", "user")

    expired = {
        "proposal_id": 1,
        "status": AutomationProposalStatus.PENDING.value,
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "proposed_task": {"title": "old", "instruction": "run"},
        "agent_id": 3,
        "conversation_id": 9,
    }
    statuses = []
    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: expired)
    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "update_proposal_status",
        lambda *args: statuses.append(args[-1]) or True,
    )
    with pytest.raises(AutomationNotFoundError, match="expired"):
        await service.update_proposal(1, request, "tenant", "user")
    assert statuses == [AutomationProposalStatus.EXPIRED.value]

    accepted = {
        **expired,
        "status": AutomationProposalStatus.ACCEPTED.value,
        "expires_at": None,
    }
    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: accepted)
    monkeypatch.setattr(service, "get_task_for_conversation", lambda *args: None)
    with pytest.raises(AutomationNotFoundError, match="Confirmed automation task"):
        await service.update_proposal(1, request, "tenant", "user")


@pytest.mark.asyncio
async def test_update_and_confirm_proposal_cover_persistence_failure_paths(monkeypatch):
    service = AgentAutomationFacade()
    proposal = {
        "proposal_id": 1,
        "status": AutomationProposalStatus.PENDING.value,
        "expires_at": None,
        "proposed_task": {"title": "old", "instruction": "run"},
        "capability_resolution": {},
        "agent_id": 3,
        "conversation_id": 9,
    }
    resolution = CapabilityResolution(
        executable=True,
        agent_snapshot={"display_name": "助手"},
    )

    async def resolve(*args, **kwargs):
        return resolution

    monkeypatch.setattr(facade_module.agent_automation_db, "get_proposal", lambda *args: proposal)
    monkeypatch.setattr(facade_module, "resolve_agent_capabilities", resolve)
    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal", lambda *args: False)
    with pytest.raises(AutomationNotFoundError, match="not editable"):
        await service.update_proposal(
            1,
            AutomationProposalPatchRequest(title="updated"),
            "tenant",
            "user",
        )

    monkeypatch.setattr(facade_module.agent_automation_db, "update_proposal", lambda *args: True)
    monkeypatch.setattr(
        facade_module.automation_conversation_adapter,
        "update_proposal",
        lambda *args: (_ for _ in ()).throw(RuntimeError("message unavailable")),
    )
    result = await service.update_proposal(
        1,
        AutomationProposalPatchRequest(title="updated"),
        "tenant",
        "user",
    )
    assert result["task"]["title"] == "updated"

    monkeypatch.setattr(
        facade_module.agent_automation_db,
        "get_proposal",
        lambda *args: {**proposal, "status": AutomationProposalStatus.ACCEPTED.value},
    )
    with pytest.raises(AutomationNotFoundError, match="not pending"):
        await service.confirm_proposal(
            1,
            AutomationProposalConfirmRequest(),
            "tenant",
            "user",
        )
