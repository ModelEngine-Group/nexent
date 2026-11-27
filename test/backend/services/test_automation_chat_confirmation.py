# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from contracts.errors.exceptions import (
    AgentAutomationError,
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


@pytest.mark.parametrize("boundary", [None, 0])
async def test_first_turn_does_not_search_for_an_invitation(owned_confirmation, boundary):
    assert await confirmation.route_chat_confirmation("可以", 42, "tenant", "user", boundary, None) is None
    confirmation.previous_automation_invitation.assert_not_called()


@pytest.mark.parametrize("text", ["   ", "可以" * 501])
async def test_blank_or_oversized_reply_is_not_sent_to_the_classifier(owned_confirmation, mocker, text):
    classify = mocker.patch.object(confirmation, "_classify_reply")

    assert await confirmation.route_chat_confirmation(text, 42, "tenant", "user", 8, None) is None

    classify.assert_not_awaited()


async def test_complex_reply_without_an_available_model_cannot_confirm(owned_confirmation, mocker):
    mocker.patch.object(confirmation, "resolve_automation_model_id", return_value=None)
    invoke = mocker.patch.object(confirmation, "invoke_chat_prompt")

    assert await confirmation.route_chat_confirmation("按原计划吧", 42, "tenant", "user", 8, None) is None

    invoke.assert_not_awaited()


@pytest.mark.parametrize("context_change", [
    {"has_attachments": True}, {"user_message": "请告诉我天气"}, {"confirmation_action": "confirm"},
])
async def test_untrusted_confirmation_does_not_look_up_or_write_proposals(owned_confirmation, context_change):
    context, lookup, confirm = owned_confirmation

    result = await confirmation.confirm_from_chat(replace(context, **context_change))

    assert result["status"] == "needs_clarification"
    assert "confirmation" not in result
    lookup.assert_not_called()
    confirm.assert_not_awaited()


@pytest.mark.parametrize(("action", "target"), [("edit", 7), ("confirm", 8)])
async def test_accepted_receipt_cannot_be_reused_by_an_edit_or_another_draft(owned_confirmation, action, target):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = [_proposal(status="ACCEPTED", task_id=71)]

    result = await confirmation.confirm_from_chat(replace(
        context, user_message="请按原计划执行", confirmation_action=action, confirmation_proposal_id=target,
    ))

    assert result["status"] == "needs_clarification"
    assert "confirmation" not in result
    confirm.assert_not_awaited()


async def test_unexpected_automation_error_returns_retryable_feedback(owned_confirmation):
    context, lookup, confirm = owned_confirmation
    lookup.return_value = [_proposal()]
    confirm.side_effect = AgentAutomationError("internal detail")

    result = await confirmation.confirm_from_chat(context)

    assert result == {"status": "error", "user_message": "暂时无法确认定时任务，请稍后重试。"}


@pytest.mark.parametrize(("requested", "selected", "default", "expected"), [
    (12, {"model_type": "llm"}, {"model_id": 16}, 12),
    (12, {"model_type": "embedding"}, {"model_id": 16}, 16),
    (12, None, None, None),
    (None, None, {"model_id": 16}, 16),
])
def test_confirmation_model_selection_respects_tenant_and_model_type(mocker, requested, selected, default, expected):
    from management.services.automation import intent
    from management.services.configuration.tenant.settings import tenant_config_manager

    lookup = mocker.patch.object(intent, "get_model_by_model_id", return_value=selected)
    tenant_default = mocker.patch.object(tenant_config_manager, "get_model_config", return_value=default)

    assert intent.resolve_automation_model_id(requested, "tenant") == expected

    if requested is None:
        lookup.assert_not_called()
    else:
        lookup.assert_called_once_with(requested, "tenant")
    if selected and selected["model_type"] == "llm":
        tenant_default.assert_not_called()
    else:
        tenant_default.assert_called_once_with(key=intent.MODEL_CONFIG_MAPPING["llm"], tenant_id="tenant")
