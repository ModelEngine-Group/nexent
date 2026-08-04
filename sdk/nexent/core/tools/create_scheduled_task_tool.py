"""System-managed tool for creating a scheduled-task proposal.

The SDK owns only the tool contract and event emission. Persistence, identity,
intent extraction, and capability resolution are injected by the host
application through ``create_proposal``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType


logger = logging.getLogger("create_scheduled_task_tool")


class CreateScheduledTaskProposalTool(Tool):
    """Create a pending proposal without executing the requested business task."""

    name = "create_scheduled_task_proposal"
    description = (
        "Create a pending scheduled-task proposal when the user explicitly asks "
        "for a task to run later or repeatedly. Pass the user's scheduling request "
        "verbatim. This tool only extracts and saves a proposal for user confirmation; "
        "it never executes the business task. Call it as the only action in the code "
        "block and return its result directly as the final answer."
    )
    description_zh = (
        "当用户明确要求未来、延迟或周期性执行任务时，创建一个待确认的"
        "定时任务提案。request_text 必须原样传入用户的定时执行请求。"
        "此工具只提取并保存待用户确认的提案，不会立即执行业务任务。"
        "调用时它必须是代码块中的唯一动作，并将返回结果直接作为最终回答。"
    )
    inputs = {
        "request_text": {
            "type": "string",
            "description": "The user's scheduling request copied verbatim",
            "description_zh": "原样复制的用户定时执行请求",
        }
    }
    output_type = "string"
    emit_tool_event = False

    def __init__(
        self,
        create_proposal: Callable[[str], dict[str, Any]] = Field(
            description="Host callback that creates or reuses a proposal",
            default=None,
            exclude=True,
        ),
        observer: MessageObserver = Field(
            description="Message observer",
            default=None,
            exclude=True,
        ),
    ) -> None:
        super().__init__()
        self._create_proposal = create_proposal
        self.observer = observer

    def forward(self, request_text: str) -> str:
        if self._create_proposal is None:
            raise RuntimeError("Scheduled-task proposal service is not configured.")

        normalized = str(request_text or "").strip()
        if not normalized:
            return "请说明要定时执行的任务和执行时间。"

        result = self._create_proposal(normalized)
        if not isinstance(result, dict):
            raise RuntimeError("Scheduled-task proposal service returned an invalid result.")

        if result.get("status") == "proposal_ready":
            proposal = result.get("proposal")
            if isinstance(proposal, dict) and self.observer is not None:
                self.observer.add_message(
                    "",
                    ProcessType.AUTOMATION_PROPOSAL,
                    json.dumps(proposal, ensure_ascii=False),
                )

        message = str(result.get("user_message") or "").strip()
        if message:
            return message
        logger.warning("Scheduled-task proposal result has no user_message: %s", result.get("status"))
        return "定时任务请求已处理，请查看结果。"
