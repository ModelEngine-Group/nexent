# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Send model chat requests from Management to the AgentOS model service."""

import asyncio
import math
from contextlib import contextmanager
from contextvars import ContextVar

from contracts.agentos import (
    ChatInvocation,
    ChatMessage,
    ChatOptions,
    EmbeddingInvocation,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceUnavailableError
from management.clients.agentos import AgentOSClient
from management.services.model.text import remove_think_blocks
from nexent.core.concurrency.cancellation import RunTerminated

from backend.http.client import create_httpx_client

_worker_cancellation = ContextVar('management_model_worker_cancellation', default=None)


@contextmanager
def worker_model_cancellation(scope):
    """Bind synchronous model calls to their owning managed worker's cancellation."""
    token = _worker_cancellation.set(scope)
    try:
        if scope.cancelled:
            raise RunTerminated()
        yield
    finally:
        _worker_cancellation.reset(token)


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
    async def execute():
        scope = _worker_cancellation.get()
        token = None
        if scope is not None:
            if scope.cancelled:
                raise RunTerminated()
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            token = scope.register_closer(lambda: loop.call_soon_threadsafe(task.cancel))
        try:
            return await invoke_chat_prompt(
                model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt,
                user_id=user_id, tenant_id=tenant_id, options=ChatOptions(temperature=0.3, top_p=0.95),
            )
        except asyncio.CancelledError:
            if scope is not None and scope.cancelled:
                raise RunTerminated() from None
            raise
        finally:
            if token is not None:
                scope.unregister_closer(token)
    output = asyncio.run(execute())
    return remove_think_blocks(output).strip()


async def embed_query(
    *, model_id: int, query: str, user_id: str, tenant_id: str, revision: str | None = None,
) -> list[float]:
    """Obtain one query vector using the tenant's Runtime model binding."""
    payload = EmbeddingInvocation(model_id=model_id, input=[query], expected_revision=revision)
    output = (await _model_client().invoke_model(payload, user_id, tenant_id)).output
    if not isinstance(output, list) or len(output) != 1 or not isinstance(output[0], list):
        raise RuntimeServiceUnavailableError("Invalid AgentOS query embedding response")
    vector = output[0]
    if not vector or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
        raise RuntimeServiceUnavailableError("Invalid AgentOS query embedding vector")
    return vector


def embed_query_in_worker(*, model_id: int, query: str, user_id: str, tenant_id: str) -> list[float]:
    """Obtain one query vector from an existing synchronous evaluation worker."""
    return asyncio.run(embed_query(model_id=model_id, query=query, user_id=user_id, tenant_id=tenant_id))
