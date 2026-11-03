# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorize creator targets independently of the shared executor identity."""

from contracts.conversation import ConversationTarget
from management.db.agent.repository import query_agent_records_for_nl2agent
from management.db.conversation.repository import bind_creation_conversation_target, get_conversation_history
from management.db.skill import repository as skill_db
from management.services.agent.authorization import require_agent_draft_edit
from management.services.agent.system import system_agent_provider
from management.services.skill.permission import _can_edit_skill


def authorize_target(target, user_id, tenant_id):
    target = ConversationTarget.model_validate(target).model_dump()
    if target["type"] == "agent":
        draft = require_agent_draft_edit(agent_id=target["id"], tenant_id=tenant_id, user_id=user_id)
        if draft.get("agent_origin") == "SYSTEM":
            raise PermissionError("A creator cannot edit a system Agent")
    else:
        skill = skill_db.get_skill_by_id(target["id"], tenant_id)
        if not skill or not _can_edit_skill(skill, user_id):
            raise PermissionError("Skill target is not editable")
    return target


def bind_creator_target(conversation_id, target, user_id, tenant_id):
    target = authorize_target(target, user_id, tenant_id)
    ref = system_agent_provider.get_creator_ref(tenant_id, f"nl2{target['type']}_main")
    history = get_conversation_history(conversation_id, user_id)
    if not history or history.get("agent_id") != ref.agent_id:
        raise ValueError("Conversation does not belong to this creator")
    previous = history.get("target")
    if previous == target:
        return target
    if previous is not None:
        records = query_agent_records_for_nl2agent(previous.get("id"), tenant_id) if previous.get("type") == "agent" else []
        if not records or any(row.get("delete_flag") != "Y" for row in records):
            raise ValueError("Conversation already has another target")
    if not bind_creation_conversation_target(conversation_id, ref.agent_id, previous, target, user_id):
        raise ValueError("Conversation target changed concurrently")
    return target
