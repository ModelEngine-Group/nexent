"""Backend adapter for the SDK scheduled-task proposal tool.

This module is the only bridge between AgentLoop runtime identity and the
automation domain. The extraction model receives the trusted user message and
time settings only; Agent/runtime fields are applied after extraction.
"""

from __future__ import annotations

import asyncio

from utils.time_context_utils import strip_current_time_prefix
import concurrent.futures
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from database import agent_automation_db
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.tools.create_scheduled_task_tool import (
    CreateScheduledTaskProposalTool,
)

from .errors import (
    AgentAutomationError,
    AutomationConversationAlreadyBoundError,
    AutomationScheduleInvalidError,
)
from .facade import agent_automation_facade
from .models import AutomationProposalCreateRequest
from .prompt_generator import detect_instruction_language


logger = logging.getLogger("agent_automation.tool_adapter")
DEFAULT_AUTOMATION_TIMEZONE = "Asia/Shanghai"




def _run_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@dataclass(frozen=True)
class AutomationToolRuntimeContext:
    tenant_id: str
    user_id: str
    conversation_id: int
    agent_id: int
    user_message: str
    source_message_id: Optional[int] = None
    agent_version_no: Optional[int] = None
    model_id: Optional[int] = None
    tool_params: Optional[Dict[str, Any]] = None
    timezone: str = DEFAULT_AUTOMATION_TIMEZONE
    has_attachments: bool = False


class AgentLoopAutomationToolAdapter:
    def build_tool_config(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: int,
        agent_id: int,
        user_message: str,
        agent_version_no: Optional[int],
        model_id: Optional[int],
        tool_params: Optional[Dict[str, Any]],
        has_attachments: bool,
        language: str,
    ) -> ToolConfig:
        """Build the system-injected tool config for one interactive run."""
        from services.conversation_management_service import (
            get_current_run_user_message_id,
        )

        context = AutomationToolRuntimeContext(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            user_message=user_message,
            source_message_id=get_current_run_user_message_id(
                conversation_id,
                user_id,
            ),
            agent_version_no=agent_version_no,
            model_id=model_id,
            tool_params=tool_params,
            has_attachments=has_attachments,
        )
        description = (
            CreateScheduledTaskProposalTool.description
            if language == "en"
            else CreateScheduledTaskProposalTool.description_zh
        )
        return ToolConfig(
            class_name=CreateScheduledTaskProposalTool.__name__,
            name=CreateScheduledTaskProposalTool.name,
            description=description,
            inputs=json.dumps(
                CreateScheduledTaskProposalTool.inputs,
                ensure_ascii=False,
            ),
            output_type=CreateScheduledTaskProposalTool.output_type,
            params={},
            source="builtin",
            usage="builtin",
            metadata={"create_proposal": self.build_callback(context)},
        )

    def build_callback(
        self,
        context: AutomationToolRuntimeContext,
    ) -> Callable[[str], Dict[str, Any]]:
        def create_proposal(request_text: str) -> Dict[str, Any]:
            return _run_coroutine(self.create_proposal(context, request_text))

        return create_proposal

    async def create_proposal(
        self,
        context: AutomationToolRuntimeContext,
        request_text: str,
    ) -> Dict[str, Any]:
        # The model argument is intentionally not forwarded to extraction. The
        # persisted current user message is the authoritative business input.
        del request_text
        user_message = strip_current_time_prefix(str(context.user_message or ""))
        language = detect_instruction_language(user_message)
        if context.source_message_id is None:
            message = (
                "本轮消息尚未完成持久化，无法安全创建定时任务提案。请稍后重试。"
                if language == "zh"
                else "This message is not persisted yet, so a scheduled-task proposal "
                "cannot be created safely. Try again later."
            )
            return {
                "status": "error",
                "error_code": "AUTOMATION_SOURCE_MESSAGE_UNAVAILABLE",
                "user_message": message,
            }
        if context.has_attachments:
            message = (
                "当前版本不能把本轮临时附件作为定时任务的长期输入。"
                "请改为描述稳定的数据来源后再创建。"
                if language == "zh"
                else "This version cannot use a temporary attachment as recurring task input. "
                "Describe a stable data source and try again."
            )
            return {
                "status": "needs_clarification",
                "missing_fields": ["data_source"],
                "user_message": message,
            }

        request = AutomationProposalCreateRequest(
            conversation_id=context.conversation_id,
            agent_id=context.agent_id,
            message=user_message,
            timezone=context.timezone or DEFAULT_AUTOMATION_TIMEZONE,
            agent_version_no=context.agent_version_no,
            model_id=context.model_id,
            tool_params=context.tool_params,
        )
        try:
            proposal = await agent_automation_facade.create_proposal(
                request,
                context.tenant_id,
                context.user_id,
                persist_conversation_exchange=False,
                source_message_id=context.source_message_id,
                force_llm=True,
            )
        except AutomationScheduleInvalidError as exc:
            question = str(exc.details.get("clarification_question") or exc.message)
            return {
                "status": "needs_clarification",
                "missing_fields": exc.details.get("missing_fields") or [],
                "user_message": question,
            }
        except AutomationConversationAlreadyBoundError:
            message = (
                "当前会话已经绑定了一个有效的定时任务。"
                "如需创建另一个任务，请新建会话并重新描述。"
                if language == "zh"
                else "This conversation already has an active scheduled task. "
                "Start a new conversation to create another one."
            )
            return {"status": "conflict", "user_message": message}
        except AgentAutomationError as exc:
            logger.warning(
                "AgentLoop automation proposal failed: code=%s details=%s",
                exc.error_code,
                exc.details,
            )
            return {
                "status": "error",
                "error_code": exc.error_code,
                "user_message": exc.message,
            }

        if proposal.get("proposal_id") is None:
            message = (
                "这条消息没有包含需要未来或周期执行的任务。"
                "请补充明确的执行时间或周期。"
                if language == "zh"
                else "This message does not describe a future or recurring task. "
                "Add a specific execution time or recurrence."
            )
            return {"status": "not_automation", "user_message": message}

        message = (
            "定时任务提案已生成，请核对任务内容和执行时间后确认创建。"
            if language == "zh"
            else "The scheduled-task proposal is ready. Review its task and schedule, then confirm it."
        )
        return {
            "status": "proposal_ready",
            "proposal": proposal,
            "user_message": message,
        }


agent_loop_automation_tool_adapter = AgentLoopAutomationToolAdapter()


def link_persisted_proposal_card(
    content: str,
    tenant_id: str,
    user_id: str,
    message_id: int,
    unit_id: int,
) -> bool:
    """Attach a persisted conversation unit to its proposal for later card updates."""
    try:
        payload = json.loads(content)
        proposal_id = int(payload["proposal_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Invalid persisted automation proposal event payload")
        return False
    return agent_automation_db.link_proposal_message_unit(
        proposal_id,
        tenant_id,
        user_id,
        message_id,
        unit_id,
    )
