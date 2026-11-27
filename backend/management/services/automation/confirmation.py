# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirm owned automation proposals in response to an adjacent invitation."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from unicodedata import normalize

from contracts.agentos import ChatOptions
from contracts.automation import AutomationProposalConfirmRequest, AutomationProposalStatus
from contracts.errors.exceptions import (
    AgentAutomationError,
    AutomationCapabilityNotReadyError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
    AutomationScheduleInvalidError,
)
from management.clients.model import invoke_chat_prompt
from management.db.automation import repository
from management.db.conversation.prepared_turn import previous_automation_invitation
from management.services.agent.context import strip_current_time_prefix
from management.services.automation.intent import resolve_automation_model_id
from management.services.automation.prompt import detect_instruction_language
from management.services.automation.service import agent_automation_facade
from management.services.model.text import remove_think_blocks
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)
_COMMANDS = {
    "确认创建", "确认创建任务", "创建任务", "创建这个任务", "创建此任务", "创建定时任务",
    "确认创建定时任务", "确认创建这个任务", "创建这个定时任务", "确认创建这个定时任务",
    "请创建任务", "请创建这个任务", "请创建定时任务", "请确认创建",
    "confirm creation", "confirm task", "create task", "create the task", "create this task",
    "create the scheduled task", "please create the task", "confirm task creation",
}
_AFFIRMATIONS = {"好", "好的", "可以", "行", "创建", "确认", "yes", "okay", "ok", "create", "confirm"}
_CONFIRMATION_VETO = re.compile(
    r"[?？]|修改|调整|改到|改成|改为|换个|不要|不创建|先别|别创建|暂缓|暂不|之后再|晚点|如果|除非|取消|再决定|不过"
    r"|\b(?:if|unless|not|don['’]t|cancel|change|modify|edit|reschedule|instead|wait|later|hold off|but)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChatConfirmation:
    action: Literal["explicit", "confirm", "edit"]
    proposal_id: int | None = None


def _command(query: str) -> str:
    text = normalize("NFKC", query).casefold().strip()
    return " ".join(text.rstrip(".!。").split())


async def _scoped_proposals(conversation_id, tenant_id, user_id):
    return await run_blocking(
        "automation-confirmation-proposals", repository.list_confirmation_proposals,
        conversation_id, tenant_id, user_id, lane="control-io", owner="management",
    )


async def _previous_invitation(conversation_id, tenant_id, user_id, before_index):
    if before_index is None or before_index <= 0:
        return None
    return await run_blocking(
        "automation-previous-invitation", previous_automation_invitation,
        conversation_id, tenant_id, user_id, before_index, lane="control-io", owner="management",
    )


async def _classify_reply(query, tenant_id, user_id, model_id):
    try:
        model_id = await run_blocking(
            "automation-confirmation-model", resolve_automation_model_id, model_id, tenant_id,
            lane="control-io", owner="management",
        )
        if model_id is None:
            return None
        prompt = compose_auxiliary_prompt(
            detect_instruction_language(query), "automation_confirmation",
            {"reply": json.dumps(query, ensure_ascii=False)},
        )
        response = await asyncio.wait_for(invoke_chat_prompt(
            model_id=model_id, system_prompt=prompt.system, user_prompt=prompt.user,
            user_id=user_id, tenant_id=tenant_id, options=ChatOptions(temperature=0, max_output_tokens=64),
        ), timeout=8)
    except Exception as exc:
        logger.warning("Unable to classify an automation confirmation reply (%s)", type(exc).__name__)
        return None
    return remove_think_blocks(response).strip()


async def route_chat_confirmation(
    query: str, conversation_id: int, tenant_id: str, user_id: str, before_index: int, model_id: int | None,
) -> ChatConfirmation | None:
    query = strip_current_time_prefix(query)
    command = _command(query)
    if command in _COMMANDS:
        return ChatConfirmation("explicit")
    target = await _previous_invitation(conversation_id, tenant_id, user_id, before_index)
    if target is None:
        return None
    if command in _AFFIRMATIONS:
        return ChatConfirmation("confirm", target)
    if not command or len(query) > 1000:
        return None
    assessment = await _classify_reply(query, tenant_id, user_id, model_id)
    if assessment == "EDIT":
        return ChatConfirmation("edit", target)
    if assessment == "CONFIRM" and not _CONFIRMATION_VETO.search(command):
        return ChatConfirmation("confirm", target)
    return None


def _feedback(zh: bool, chinese: str, english: str, *, status: str = "needs_clarification") -> dict:
    return {"status": status, "user_message": chinese if zh else english}


async def confirm_from_chat(context) -> dict:
    query = strip_current_time_prefix(context.user_message)
    zh = detect_instruction_language(query) == "zh"
    action = context.confirmation_action
    target = context.confirmation_proposal_id
    authorized = _command(query) in _COMMANDS if action == "explicit" else (
        action in {"confirm", "edit"} and target is not None
    )
    if context.has_attachments or not authorized:
        return _feedback(zh, "请单独发送「确认创建」或点击草稿上的创建按钮。",
                         'Send "Confirm creation" by itself or use the create button on the draft.')

    proposals = await _scoped_proposals(context.conversation_id, context.tenant_id, context.user_id)
    now = datetime.now(timezone.utc)
    pending = [
        proposal for proposal in proposals
        if proposal["status"] == AutomationProposalStatus.PENDING and proposal["expires_at"] > now
    ]
    if len(pending) > 1:
        return _feedback(zh, "当前会话有多个待确认草稿，请点击要创建的那张卡片。",
                         "There are several pending drafts. Use the create button on the one you want.")
    candidates = pending or [
        proposal for proposal in proposals
        if proposal["status"] == AutomationProposalStatus.ACCEPTED and proposal.get("confirmed_task_id")
    ]
    if not candidates:
        if proposals:
            return _feedback(zh, "定时任务草稿已过期，请重新生成草稿。",
                             "The scheduled-task draft has expired. Generate a new draft.")
        return _feedback(zh, "当前会话没有可确认的定时任务草稿，请先描述任务和执行时间。",
                         "There is no scheduled-task draft to confirm. Describe the task and its schedule first.")

    proposal_id = candidates[0]["proposal_id"]
    if pending:
        displayed = await _previous_invitation(
            context.conversation_id, context.tenant_id, context.user_id, context.confirmation_before_index,
        )
        if displayed != proposal_id or (target is not None and target != proposal_id):
            return _feedback(zh, "当前回复未对应刚展示的确认问题。请在草稿卡片上点击「创建任务」。",
                             "This reply is not linked to the latest confirmation question. Use the create button on the draft.")
        if action == "edit":
            return _feedback(zh, "这条回复包含修改要求。请先在草稿卡片中修改并核对，再创建。",
                             "This reply requests changes. Edit and review the draft on its card before creating it.")
    elif action == "edit" or (target is not None and target != proposal_id):
        return _feedback(zh, "这份草稿已无法按当前回复确认，请核对卡片状态。",
                         "This draft cannot be confirmed with this reply. Check the status of its card.")
    try:
        task = await agent_automation_facade.confirm_proposal(
            proposal_id, AutomationProposalConfirmRequest(), context.tenant_id, context.user_id,
        )
    except (AutomationNotFoundError, AutomationScheduleInvalidError):
        return _feedback(zh, "草稿已失效或执行时间不可用，请重新生成草稿。",
                         "The draft or its schedule is no longer valid. Generate a new draft.")
    except AutomationCapabilityNotReadyError:
        return _feedback(zh, "智能体缺少执行所需的能力，请先配置智能体，再确认创建。",
                         "Configure the required agent capabilities, then confirm creation again.")
    except AutomationConversationAlreadyBoundError:
        return _feedback(zh, "当前会话已有定时任务。如需新建，请开启另一会话。",
                         "This conversation already has a scheduled task. Start another conversation to create one.")
    except AgentAutomationError:
        return _feedback(zh, "暂时无法确认定时任务，请稍后重试。",
                         "The scheduled task could not be confirmed. Try again shortly.", status="error")

    task_id = task["task_id"]
    return {
        **_feedback(zh, f"定时任务已创建，任务编号 {task_id}。",
                    f"Scheduled task created. Task ID {task_id}.", status="task_confirmed"),
        "confirmation": {"proposal_id": proposal_id, "task_id": task_id},
    }
