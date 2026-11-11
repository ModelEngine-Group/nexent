# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Forward compatibility public requests to Management through signed AgentOS."""

from fastapi import Request

from backend.http.client import create_httpx_client
from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from contracts.constants.environment import MANAGEMENT_AGENTOS_URL
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal


def management_client() -> AgentOSClient:
    return AgentOSClient(MANAGEMENT_AGENTOS_URL, create_httpx_client)


async def dispatch_signed_start(payload: CompatibilityConversationRun, actor: ServicePrincipal):
    """Return an unconsumed claim to its resource preparation owner."""
    return await management_client().dispatch_conversation(
        payload.model_copy(update={"preparation": "management"}), actor.user_id, actor.tenant_id,
    )


async def dispatch_public_start(request: AgentRequest, context: Request | None, actor: ServicePrincipal):
    language = "zh"
    timezone = None
    if context is not None:
        locale = context.cookies.get("NEXT_LOCALE")
        if locale in {"zh", "en"}:
            language = locale
        timezone = context.headers.get("x-user-timezone")
    payload = CompatibilityConversationRun(
        request=request.model_dump(mode="json", exclude_unset=True),
        language=language,
        timezone=timezone if timezone and len(timezone) <= 128 else None,
    )
    return await management_client().dispatch_conversation(payload, actor.user_id, actor.tenant_id)
