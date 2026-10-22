# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Jiuwen native MCP tools with Nexent managed session ownership."""

import asyncio
import keyword
import logging
import re
from contextlib import AsyncExitStack, nullcontext
from copy import deepcopy
from types import SimpleNamespace

from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig, MCPTool, McpToolCard
from openjiuwen.core.foundation.tool.mcp.client.streamable_http_client import StreamableHttpClient

from ....consts.mcp_errors import MCPConnectionTimeoutError, MCPToolTimeoutError
from ...concurrency import ManagedTaskSpec
from ..managed_mcp import ManagedMCPToolCollection
from ..tool_user_context import USER_CONTEXT_FIELDS


logger = logging.getLogger(__name__)


def _registered_tool_name(name):
    """Match the naming contract used by Nexent's MCP registration adapter."""
    normalized = re.sub(r"[^\w_]", "", name.replace("-", "_"))
    if normalized and normalized[0].isdigit():
        normalized = "_" + normalized
    if keyword.iskeyword(normalized):
        normalized += "_"
    return normalized


class JiuwenMCPCollection(ManagedMCPToolCollection):
    """Reuse bounded lifecycle ownership, never instantiate a smolagents MCP adapter."""

    def __init__(self, *, authorized_tools, observe, user_context=None, emit_result=None, **kwargs):
        super().__init__(**kwargs)
        self.authorized_tools = authorized_tools
        self.observe = observe
        self.emit_result = emit_result
        self.terminal_error = None
        self.user_context = deepcopy(dict(user_context or {}))

    async def _run_async_session(self):
        from ..run_agent import _normalize_mcp_config

        async with AsyncExitStack() as stack:
            available = {}
            for index, raw in enumerate(self.server_parameters):
                parameters = _normalize_mcp_config(raw)
                headers = dict(parameters.get("headers") or {})
                if parameters.get("authorization"):
                    headers["Authorization"] = parameters["authorization"]
                config = McpServerConfig(
                    server_name=f"nexent_{index}", server_path=parameters["url"],
                    client_type=parameters["transport"], auth_headers=headers,
                )
                client = _ConfiguredNativeClient(config, parameters.get("httpx_client_factory"))
                # Connect and disconnect in this owner task: MCP uses task-bound cancel scopes.
                stack.push_async_callback(client.disconnect, timeout=self.close_timeout_seconds)
                if not await client.connect(timeout=self.connect_timeout_seconds):
                    raise MCPConnectionTimeoutError("Jiuwen MCP connection failed")
                for card in await client.list_tools(timeout=self.connect_timeout_seconds):
                    # The public saved name may be normalized; the proxy keeps the raw wire name.
                    for name in {card.name, _registered_tool_name(card.name)} - {""}:
                        available[name] = None if name in available else (client, card)

            tools = []
            for tool_config in self.authorized_tools:
                match = available.get(tool_config.class_name)
                if match is None:
                    raise ValueError(f"Authorized MCP tool missing or ambiguous: {tool_config.class_name}")
                client, remote_card = match
                properties = remote_card.input_params.get("properties", {})
                hidden = [name for name in USER_CONTEXT_FIELDS if name in properties]
                proxy = _ManagedNativeClient(self, client, remote_card.name, hidden, tool_config.params)
                card = remote_card.model_copy(deep=True)
                for name in hidden:
                    card.input_params["properties"].pop(name, None)
                card.input_params["required"] = [name for name in card.input_params.get("required", [])
                                                 if name not in hidden]
                card.name = tool_config.name or tool_config.class_name
                if tool_config.description:
                    card.description = tool_config.description
                tools.append(_ObservedMCPTool(proxy, card, self.observe, self.emit_result))

            close_event = asyncio.Event()
            with self._lock:
                self._async_close_event = close_event
                self.tools = tools
                self._public_collection = SimpleNamespace(tools=tools)
            if self._close_requested.is_set():
                close_event.set()
            self._ready.set()
            await close_event.wait()


class _ManagedNativeClient:
    def __init__(self, owner, client, remote_name, hidden_fields=(), configured_arguments=None):
        self.owner, self.client, self.remote_name = owner, client, remote_name
        self.hidden_fields = hidden_fields
        self.configured_arguments = deepcopy(dict(configured_arguments or {}))

    async def call_tool(self, tool_name, arguments):
        owner = self.owner
        if owner.cancellation_scope.cancelled:
            raise asyncio.CancelledError()
        arguments = {**arguments, **deepcopy(self.configured_arguments)}
        for name in self.hidden_fields:
            arguments[name] = owner.user_context.get(name)
        execution = owner.manager.submit(
            "model-tool-io",
            ManagedTaskSpec(task_name="jiuwen-mcp-tool", owner=__name__, close_hook=owner.request_close),
            owner._call_tool, self.client, self.remote_name, arguments,
        )
        try:
            return await asyncio.wait_for(asyncio.wrap_future(execution.future), owner.tool_timeout_seconds)
        except asyncio.TimeoutError as exc:
            logger.warning("event=mcp_tool_timeout tool_name=%s timeout_seconds=%s phase=execution",
                           tool_name, owner.tool_timeout_seconds)
            owner.terminal_error = MCPToolTimeoutError("Jiuwen MCP tool deadline exceeded")
            owner.request_close()
            owner.manager.cancel(execution.execution_id, reason="MCP tool deadline exceeded", wait_timeout=0,
                                 mark_stuck_on_timeout=False)
            raise owner.terminal_error from exc
        except asyncio.CancelledError:
            owner.request_close()
            raise


class _ObservedMCPTool(MCPTool):
    def __init__(self, client, card, observe, emit_result):
        super().__init__(client, card)
        self._observe = observe
        self._emit_result = emit_result

    async def invoke(self, inputs, **kwargs):
        with self._observe(self.card.name, inputs) or nullcontext():
            result = await super().invoke(inputs, **kwargs)
            if self._emit_result:
                self._emit_result(result)
            return result


class _ConfiguredNativeClient(StreamableHttpClient):
    """Preserve Nexent transport policy while retaining native Jiuwen MCP operations."""

    def __init__(self, config, http_client_factory):
        super().__init__(config)
        self._transport = config.client_type
        self._http_client_factory = http_client_factory

    async def connect(self, *, timeout):
        import httpx
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        options = {"headers": self._auth_headers, "timeout": timeout}
        if self._http_client_factory is not None:
            options["httpx_client_factory"] = self._http_client_factory
        if self._transport == "sse":
            self._client = sse_client(self._server_path, **options)
        else:
            factory = self._http_client_factory or create_mcp_http_client
            http_client = factory(headers=self._auth_headers, timeout=httpx.Timeout(timeout, read=300))
            await self._exit_stack.enter_async_context(http_client)
            self._client = streamable_http_client(self._server_path, http_client=http_client)
        streams = await self._exit_stack.enter_async_context(self._client)
        self._read, self._write, *_ = streams
        self._session = await self._exit_stack.enter_async_context(ClientSession(self._read, self._write))
        await self._session.initialize()
        self._is_disconnected = False
        return True

    async def list_tools(self, *, timeout):
        response = await self._session.list_tools()
        return [McpToolCard(name=tool.name, server_name=self._name, description=tool.description or "",
                            input_params=tool.inputSchema) for tool in response.tools]
