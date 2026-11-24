# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AgentNotFoundError, AppException, ForbiddenError
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.db.agent.repository import search_agent_info_by_agent_id
from management.services.agent.authorization import authorize_debug_version


def require_business_agent_edit(agent_id: int, tenant_id: str, user_id: str) -> None:
    """Use current tenant membership and the same draft visibility/edit policy as Agent debug."""
    if not get_user_role_by_tenant(user_id, tenant_id):
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    try:
        draft = authorize_debug_version(agent_id, 0, user_id, tenant_id)
    except AgentNotFoundError as exc:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND) from exc
    except ForbiddenError as exc:
        raise AppException(ErrorCode.COMMON_FORBIDDEN) from exc
    if draft.get("agent_origin") == "SYSTEM":
        raise AppException(ErrorCode.COMMON_FORBIDDEN)


def published_business_agent(tenant_id, agent_id, version_no):
    if version_no <= 0:
        raise AppException(ErrorCode.AGENTSPACE_VERSION_NOT_FOUND)
    try:
        agent = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    except AgentNotFoundError as exc:
        raise AppException(ErrorCode.AGENTSPACE_VERSION_NOT_FOUND) from exc
    if agent.get("tenant_id") != tenant_id or agent.get("agent_origin") == "SYSTEM":
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    return agent
