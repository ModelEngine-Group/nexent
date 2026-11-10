# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Send model chat requests from Management to the AgentOS model service."""

from backend.http.client import create_httpx_client
from contracts.agentos import ChatInvocation, ChatMessage, ChatOptions
from contracts.constants import environment
from management.clients.agentos import AgentOSClient


async def invoke_chat_prompt(
    *,
    model_id: int,
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    tenant_id: str,
    options: ChatOptions | None = None,
) -> str:
    payload = ChatInvocation(
        model_id=model_id,
        input=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ],
        options=options,
    )
    client = AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    result = await client.invoke_model(payload, user_id, tenant_id)
    content = result.output.get("content") if isinstance(result.output, dict) else None
    return content if isinstance(content, str) else ""
