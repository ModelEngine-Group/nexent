# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Send model chat requests from Management to the AgentOS model service."""

import asyncio
import math

from backend.http.client import create_httpx_client
from contracts.agentos import ChatInvocation, ChatMessage, ChatOptions, EmbeddingInvocation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceUnavailableError
from management.clients.agentos import AgentOSClient
from management.services.model.text import remove_think_blocks


def _model_client():
    return AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)


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
    result = await _model_client().invoke_model(payload, user_id, tenant_id)
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


def embed_query_in_worker(*, model_id: int, query: str, user_id: str, tenant_id: str) -> list[float]:
    """Obtain the one query vector requested by a synchronous evaluation worker."""
    payload = EmbeddingInvocation(model_id=model_id, input=[query])
    output = asyncio.run(_model_client().invoke_model(payload, user_id, tenant_id)).output
    if not isinstance(output, list) or len(output) != 1 or not isinstance(output[0], list):
        raise RuntimeServiceUnavailableError("Invalid AgentOS query embedding response")
    vector = output[0]
    if not vector or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
        raise RuntimeServiceUnavailableError("Invalid AgentOS query embedding vector")
    return vector
