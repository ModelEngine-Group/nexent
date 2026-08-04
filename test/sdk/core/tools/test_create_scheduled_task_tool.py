import importlib
import json
from unittest.mock import MagicMock

from sdk.nexent.core.tools.create_scheduled_task_tool import (
    CreateScheduledTaskProposalTool,
)
from sdk.nexent.core.utils.observer import ProcessType


def test_proposal_tool_emits_structured_event_without_executing_task():
    observer = MagicMock()
    proposal = {
        "proposal_id": 12,
        "conversation_id": 34,
        "task": {"title": "检查服务"},
    }
    callback = MagicMock(return_value={
        "status": "proposal_ready",
        "proposal": proposal,
        "user_message": "请确认任务提案。",
    })
    tool = CreateScheduledTaskProposalTool(
        create_proposal=callback,
        observer=observer,
    )

    result = tool.forward("每五分钟检查服务")

    assert result == "请确认任务提案。"
    callback.assert_called_once_with("每五分钟检查服务")
    observer.add_message.assert_called_once_with(
        "",
        ProcessType.AUTOMATION_PROPOSAL,
        json.dumps(proposal, ensure_ascii=False),
    )
    assert tool.emit_tool_event is False


def test_proposal_tool_does_not_emit_card_for_clarification():
    observer = MagicMock()
    tool = CreateScheduledTaskProposalTool(
        create_proposal=lambda _: {
            "status": "needs_clarification",
            "user_message": "请补充执行时间。",
        },
        observer=observer,
    )

    assert tool.forward("创建一个定时任务") == "请补充执行时间。"
    observer.add_message.assert_not_called()


def test_proposal_tool_is_not_exported_to_the_user_tool_catalog():
    tools_package = importlib.import_module("sdk.nexent.core.tools")

    assert not hasattr(tools_package, "CreateScheduledTaskProposalTool")
