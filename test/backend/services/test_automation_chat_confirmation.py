# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from contracts.errors.exceptions import (
    AutomationCapabilityNotReadyError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
)
from management.services.automation import confirmation
from management.services.automation.proposal import AutomationToolRuntimeContext


def _proposal(proposal_id=7, status="PENDING", *, expired=False, task_id=None):
    return {
        "proposal_id": proposal_id,
        "status": status,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1),
        "confirmed_task_id": task_id,
    }


@pytest.fixture
def owned_confirmation(mocker):
    context = AutomationToolRuntimeContext(
        tenant_id="tenant", user_id="user", conversation_id=42, agent_id=3, user_message="确认创建",
        confirm_from_chat=True, confirmation_action="explicit", confirmation_before_index=8,
    )
    async def run_inline(_name, fn, *args, **kwargs):
        return fn(*args)

    mocker.patch.object(confirmation, "run_blocking", side_effect=run_inline)
    mocker.patch.object(confirmation, "previous_automation_invitation", return_value=7)
    lookup = mocker.patch.object(confirmation.repository, "list_confirmation_proposals", return_value=[])
    confirm = mocker.patch.object(confirmation.agent_automation_facade, "confirm_proposal", return_value={"task_id": 71})
    return context, lookup, confirm


@pytest.mark.parametrize(("text", "expected"), [
    ("确认创建", True), ("创建这个任务！", True), ("Ｃｏｎｆｉｒｍ   creation.", True),
    ("确认创建？", False), ("改到九点再创建", False), ("我没有确认创建", False),
    ("每天九点创建任务", False), ("好", False), ("创建", False),
])
async def test_confirmation_dispatch_recognizes_only_standalone_commands(owned_confirmation, text, expected):
    confirmation.previous_automation_invitation.return_value = None
    decision = await confirmation.route_chat_confirmation(text, 42, "tenant", "user", 8, None)
    assert (decision is not None) is expected


@pytest.mark.parametrize("text", ["好", "可以", "好的！", "创建", "确认"])
async def test_affirmative_reply_is_bound_to_the_immediate_invitation(owned_confirmation, mocker, text):
    classify = mocker.patch.object(confirmation, "_classify_reply")
    decision = await confirmation.route_chat_confirmation(text, 42, "tenant", "user", 8, None)
    assert decision == confirmation.ChatConfirmation("confirm", 7)
    confirmation.previous_automation_invitation.assert_called_once_with(42, "tenant", "user", 8)
    classify.assert_not_awaited()


async def test_changed_topic_cannot_consume_an_affirmative(owned_confirmation, mocker):
    confirmation.previous_automation_invitation.return_value = None
    classify = mocker.patch.object(confirmation, "_classify_reply")
    assert await confirmation.route_chat_confirmation("好", 42, "tenant", "user", 8, None) is None
    classify.assert_not_awaited()


@pytest.mark.parametrize(("text", "model_label", "action"), [
    ("按刚才这个方案安排吧", "CONFIRM", "confirm"),
    ("好，改到九点再创建", "EDIT", "edit"),
    ("好，改到九点再创建", "CONFIRM", None),
    ("好，先别创建", "CONFIRM", None),
    ("什么时候创建？", "CONFIRM", None),
    ("另外想了解天气", "OTHER", None),
    ("如果条件满足再创建", "CONFIRM", None),
    ("按原计划执行", '{"action":"CONFIRM"}', None),
])
async def test_complex_reply_uses_scoped_model_and_validates_label(owned_confirmation, mocker, text, model_label, action):
    model = mocker.patch.object(confirmation, "resolve_automation_model_id", return_value=123)
    invoke = mocker.patch.object(confirmation, "invoke_chat_prompt", return_value=model_label)

    decision = await confirmation.route_chat_confirmation(text, 42, "tenant", "user", 8, 123)

    assert decision == (confirmation.ChatConfirmation(action, 7) if action else None)
    model.assert_called_once_with(123, "tenant")
    assert invoke.await_args.kwargs["tenant_id"] == "tenant"
    assert invoke.await_args.kwargs["user_id"] == "user"
    assert json.dumps(text, ensure_ascii=False) in invoke.await_args.kwargs["user_prompt"]


async def test_model_failure_cannot_confirm(owned_confirmation, mocker):
    mocker.patch.object(confirmation, "resolve_automation_model_id", return_value=123)
    mocker.patch.object(confirmation, "invoke_chat_prompt", side_effect=TimeoutError)
    assert await confirmation.route_chat_confirmation("按原计划吧", 42, "tenant", "user", 8, 123) is None


@pytest.mark.parametrize("row", [_proposal(), _proposal(status="ACCEPTED", task_id=71)])
async def test_receipt_is_returned_for_the_owned_proposal(owned_confirmation, row):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = [row, _proposal(8, expired=True)]

    result = await confirmation.confirm_from_chat(context)

    assert result == {
        "status": "task_confirmed", "user_message": "定时任务已创建，任务编号 71。",
        "confirmation": {"proposal_id": 7, "task_id": 71},
    }
    lookup.assert_called_once_with(42, "tenant", "user")
    proposal_id, request, tenant_id, user_id = confirm.await_args.args
    assert (proposal_id, request.instruction, tenant_id, user_id) == (7, None, "tenant", "user")


@pytest.mark.parametrize("reply", ["好", "可以", "按刚才这个方案安排吧"])
async def test_prevalidated_reply_creates_the_draft_anchored_to_the_previous_question(owned_confirmation, reply):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = [_proposal()]
    result = await confirmation.confirm_from_chat(replace(
        context, user_message=reply, confirmation_action="confirm", confirmation_proposal_id=7,
    ))
    assert result["confirmation"] == {"proposal_id": 7, "task_id": 71}
    assert confirm.await_args.args[0] == 7


@pytest.mark.parametrize(("proposals", "message"), [
    ([], "没有可确认"),
    ([_proposal(expired=True)], "已过期"),
    ([_proposal(), _proposal(8)], "多个待确认草稿"),
])
async def test_missing_expired_and_ambiguous_drafts_cannot_create_a_task(owned_confirmation, proposals, message):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = proposals

    result = await confirmation.confirm_from_chat(context)

    assert result["status"] == "needs_clarification"
    assert message in result["user_message"]
    assert "confirmation" not in result
    confirm.assert_not_awaited()


@pytest.mark.parametrize(("error", "message"), [
    (AutomationCapabilityNotReadyError("internal detail"), "缺少"),
    (AutomationNotFoundError("internal detail"), "失效"),
    (AutomationConversationAlreadyBoundError("internal detail"), "已有"),
])
async def test_confirmation_failure_cannot_emit_creation_receipt(owned_confirmation, error, message):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = [_proposal()]
    confirm.side_effect = error

    result = await confirmation.confirm_from_chat(context)

    assert result["status"] == "needs_clarification"
    assert message in result["user_message"]
    assert "confirmation" not in result


@pytest.mark.parametrize(("target", "shown", "rows", "action", "message"), [
    (7, 8, [_proposal(8)], "confirm", "未对应"),
    (7, None, [_proposal(7)], "confirm", "未对应"),
    (7, 7, [_proposal(7), _proposal(8)], "confirm", "多个待确认草稿"),
    (7, 7, [_proposal(7)], "edit", "包含修改要求"),
    (None, None, [_proposal(7)], "explicit", "未对应"),
])
async def test_confirmation_revalidates_latest_card_and_unique_pending_before_writing(
    owned_confirmation, target, shown, rows, action, message,
):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = rows
    confirmation.previous_automation_invitation.return_value = shown
    result = await confirmation.confirm_from_chat(replace(
        context, confirmation_action=action, confirmation_proposal_id=target,
    ))
    assert message in result["user_message"]
    assert "confirmation" not in result
    confirm.assert_not_awaited()
