# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Derive history routing from public executor identity without changing configuration."""

from sqlalchemy import exists, or_, select

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.models import AgentInfo, ConversationRecord


def _public_identity_filters():
    return (
        AgentInfo.agent_id == ConversationRecord.agent_id,
        AgentInfo.version_no == 0,
        AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
        AgentInfo.agent_origin == "SYSTEM",
        AgentInfo.delete_flag == "N",
    )


def executor_system_key():
    """Expose only the public executor's key for an already owner-scoped history row."""
    return (
        select(AgentInfo.system_key)
        .where(*_public_identity_filters())
        .correlate(ConversationRecord)
        .limit(1)
        .scalar_subquery()
    )


def is_workbench_history():
    """Include standalone creators in the shared history viewer without fake configuration."""
    creator = exists(
        select(1).where(
            *_public_identity_filters(),
            AgentInfo.system_key.in_(("nl2agent_main", "nl2skill_main")),
        ).correlate(ConversationRecord)
    )
    return or_(ConversationRecord.workbench_config.is_not(None), creator)
