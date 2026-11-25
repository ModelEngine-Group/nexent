# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Use Jiuwen's A2A client with Nexent-owned authentication and cancellation."""

import asyncio
import logging
from contextlib import aclosing
from copy import deepcopy

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientTimeoutError
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, GetTaskRequest, StreamResponse
from openjiuwen.core.controller.schema.task import TaskStatus
from openjiuwen.extensions.a2a.a2a_client import A2AClient
from openjiuwen.extensions.a2a.a2a_transformer import A2ATransformer


logger = logging.getLogger(__name__)
_ACTIVE_STATES = {TaskStatus.SUBMITTED, TaskStatus.WORKING, TaskStatus.WAITING}
_REMOTE_CANCEL_GRACE_SECONDS = 2.0


class _ConfiguredA2AClient(A2AClient):
    """Inject the authorized HTTP transport into Jiuwen's default client."""

    def __init__(self, info, http_client):
        protocol = info.get_protocol_type()
        url = info.url
        if protocol == "HTTP+JSON":
            url = url.rstrip("/").removesuffix("/message:send").removesuffix("/message:stream")
        self.card = AgentCard(
            name=info.name,
            capabilities=AgentCapabilities(
                streaming=((info.raw_card or {}).get("capabilities") or {}).get("streaming") is True,
            ),
            supported_interfaces=[AgentInterface(url=url, protocol_binding=protocol,
                                                 protocol_version=info.protocol_version)],
        )
        self.client = ClientFactory(ClientConfig(
            httpx_client=http_client, supported_protocol_bindings=[protocol],
            streaming=info.transport_type == "http-streaming",
        )).create(self.card)

    def events(self, request):
        return self._send_message(request)


class _RemoteResult:
    def __init__(self):
        self.task_id = None
        self.status = None
        self.artifacts = {}
        self.status_text = ""

    @staticmethod
    def _text(parts):
        return "".join(part.text for part in parts)

    def accept(self, event):
        result = A2ATransformer.from_a2a_response(event)
        if result.task_id and self.task_id and result.task_id != self.task_id:
            raise ValueError("Remote response switched task IDs")
        self.task_id = result.task_id or self.task_id
        if result.status not in {None, TaskStatus.UNKNOWN}:
            self.status = result.status
        if event.HasField("task"):
            # A polling response is a snapshot of the task's artifacts.
            for artifact in event.task.artifacts:
                self.artifacts[artifact.artifact_id] = self._text(artifact.parts)
            self.status_text = self._text(event.task.status.message.parts)
        elif event.HasField("artifact_update"):
            update = event.artifact_update
            artifact_id = update.artifact.artifact_id
            previous = self.artifacts.get(artifact_id, "") if update.append else ""
            self.artifacts[artifact_id] = previous + self._text(update.artifact.parts)
        elif event.HasField("message"):
            self.status_text = self._text(event.message.parts)
        elif event.HasField("status_update"):
            self.status_text = self._text(event.status_update.status.message.parts)

    def answer(self):
        if self.status != TaskStatus.COMPLETED:
            raise RuntimeError(f"Remote agent did not complete ({self.status or 'unknown'})")
        return "".join(self.artifacts.values()) or self.status_text or "No response received"


async def invoke_native_a2a(info, task, *, scope, runtime_metadata, user_context, timeout, close_timeout):
    """Run one authorized call and return text for the existing result envelope."""
    if info.get_protocol_type() not in {"JSONRPC", "HTTP+JSON"}:
        raise ValueError("Unsupported Jiuwen A2A HTTP transport")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    current = asyncio.current_task()
    if scope.cancelled:
        raise asyncio.CancelledError()

    def cancel():
        if not current.done() and not current.cancelling():
            current.cancel()

    token = scope.register_closer(lambda: loop.call_soon_threadsafe(cancel))
    try:
        context = deepcopy(runtime_metadata or {})
        context.pop("user_context", None)
        if user_context:
            context["user_context"] = deepcopy(user_context)
        request = A2ATransformer.to_a2a_request({"query": task})
        request.message.metadata.update(context)
        headers = httpx.Headers(info.request_headers())
        headers["A2A-Version"] = info.protocol_version
        result = _RemoteResult()
        async with httpx.AsyncClient(headers=headers, verify=info.ssl_verify, timeout=timeout) as http_client:
            client = _ConfiguredA2AClient(info, http_client)
            try:
                async with asyncio.timeout_at(deadline):
                    if loop.time() >= deadline:
                        raise TimeoutError("A2A request timed out before dispatch")
                    async with aclosing(client.events(request)) as events:
                        async for event in events:
                            result.accept(event)
                            if result.status not in _ACTIVE_STATES and result.status is not None:
                                break
                    while result.task_id and result.status in _ACTIVE_STATES:
                        await asyncio.sleep(0.2)
                        task_state = await client.client.get_task(GetTaskRequest(id=result.task_id))
                        result.accept(StreamResponse(task=task_state))
                    return result.answer()
            except (asyncio.CancelledError, TimeoutError, httpx.TimeoutException, A2AClientTimeoutError) as error:
                if not isinstance(error, asyncio.CancelledError):
                    logger.warning(
                        "event=a2a_request_timeout agent_id=%s timeout_seconds=%.3f phase=native_call error_type=%s",
                        info.agent_id, timeout, type(error).__name__,
                    )
                if result.task_id and result.status in _ACTIVE_STATES:
                    try:
                        async with asyncio.timeout(min(close_timeout, _REMOTE_CANCEL_GRACE_SECONDS)):
                            await client.cancel_task(result.task_id)
                    except Exception as cancel_error:
                        logger.warning("event=a2a_remote_cancel_failed agent_id=%s error_type=%s",
                                       info.agent_id, type(cancel_error).__name__)
                if isinstance(error, A2AClientTimeoutError):
                    raise TimeoutError("A2A request timed out") from None
                raise
    finally:
        scope.unregister_closer(token)
