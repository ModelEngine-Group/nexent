# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Send model chat requests from Management to the AgentOS model service."""

import asyncio

from backend.http.client import create_httpx_client
from contracts.agentos import ChatInvocation, ChatMessage, ChatOptions
from contracts.constants import environment
from management.clients.agentos import AgentOSClient
from management.services.model.text import remove_think_blocks


async def invoke_chat_prompt(
    *,
    model_id: int,
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    tenant_id: str,
    options: ChatOptions | None = None,
) -> str:
    return await invoke_chat_messages(
        model_id=model_id,
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ],
        user_id=user_id,
        tenant_id=tenant_id,
        options=options,
    )


async def invoke_chat_messages(
    *,
    model_id: int,
    messages: list[ChatMessage],
    user_id: str,
    tenant_id: str,
    options: ChatOptions | None = None,
) -> str:
    payload = ChatInvocation(model_id=model_id, input=messages, options=options)
    client = AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    result = await client.invoke_model(payload, user_id, tenant_id)
    content = result.output.get("content") if isinstance(result.output, dict) else None
    return content if isinstance(content, str) else ""


def invoke_chat_prompt_in_worker(
    *, model_id: int, system_prompt: str, user_prompt: str, user_id: str, tenant_id: str,
) -> str:
    """Invoke AgentOS from an existing synchronous job worker."""
    output = asyncio.run(invoke_chat_prompt(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        user_id=user_id,
        tenant_id=tenant_id,
        options=ChatOptions(temperature=0.3, top_p=0.95),
    ))
    return remove_think_blocks(output).strip()
