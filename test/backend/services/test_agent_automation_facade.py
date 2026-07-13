from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from services.agent_automation import facade as facade_module
from services.agent_automation.errors import (
    AutomationCapabilityNotReadyError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
    AutomationScheduleInvalidError,
)
from services.agent_automation.facade import AgentAutomationFacade
from services.agent_automation.intent_analyzer import AutomationIntentContext
from services.agent_automation.models import (
    AutomationProposalCreateRequest,
    AutomationProposalConfirmRequest,
    AutomationProposalStatus,
    AutomationRunStatus,
    AutomationTaskCreateRequest,
    CapabilityResolution,
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


@pytest.mark.asyncio
async def test_create_task_requires_and_reuses_bound_conversation(monkeypatch):
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

    assert task["conversation_id"] == 123
    assert task["status"] == "ACTIVE"
    assert created_task["runtime_snapshot"] == {
        "agent_id": 3,
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
