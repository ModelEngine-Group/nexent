# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Jiuwen native MCP tools with Nexent managed lazy session ownership."""

import asyncio
import logging
from contextlib import nullcontext
from copy import deepcopy

from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig, MCPTool, McpToolCard
from openjiuwen.core.foundation.tool.mcp.client.streamable_http_client import StreamableHttpClient

from nexent.consts.mcp_errors import MCPConnectionFailure, MCPConnectionTimeoutError, MCPToolTimeoutError
from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
from nexent.core.agents.resources.tool_schemas import parse_mcp_tool_inputs
from nexent.core.agents.resources.tool_user_context import USER_CONTEXT_FIELDS
from nexent.core.concurrency import ManagedTaskSpec


logger = logging.getLogger(__name__)


class JiuwenMCPCollection(ManagedMCPToolCollection):
    """Reuse the lazy lifecycle ownership with native Jiuwen MCP clients.

    Tool objects are built from the DB-cached ToolConfig schemas without any
    network I/O; each server connects lazily when one of its tools is first
    invoked, and the native client is reused for the rest of the run.
    """

    def __init__(self, *, observe, emit_result=None, user_context=None, **kwargs):
        kwargs.setdefault("tool_builder", self._build_tool)
        super().__init__(**kwargs)
        self.observe = observe
        self.emit_result = emit_result
        self.terminal_error = None
        self.user_context = deepcopy(dict(user_context or {}))

    def _build_tool(self, tool_config, call_fn):
        """Build one observed native tool from its cached ToolConfig."""
        server_key = self._resolve_server_key(tool_config)
        wire_name = self._wire_name_for(tool_config)

        def lazy_call(arguments=None):
            return self.call_tool(server_key, wire_name, arguments)

        properties = parse_mcp_tool_inputs(tool_config)
        hidden = [name for name in USER_CONTEXT_FIELDS if name in properties]
        proxy = _ManagedNativeClient(self, lazy_call, wire_name, hidden, tool_config.params)
        card_properties = {name: spec for name, spec in properties.items() if name not in hidden}
        # The DB cache stores only inputSchema["properties"]; the required list
        # is not persisted, so the card advertises properties without it.
        input_params = {"type": "object", "properties": card_properties}
        card = McpToolCard(
            name=tool_config.name or tool_config.class_name,
            server_name=tool_config.usage or server_key,
            description=tool_config.description or "",
            input_params=input_params,
        )
        return _ObservedMCPTool(proxy, card, self.observe, self.emit_result)

    def wrap_tool(self, tool):
        """Native tools enforce their own deadline inside _ManagedNativeClient."""
        return tool

    async def _connect_server(self, parameters):
        """Connect one server with a native Jiuwen client; return (client, live names)."""
        headers = dict(parameters.get("headers") or {})
        if parameters.get("authorization"):
            headers["Authorization"] = parameters["authorization"]
        config = McpServerConfig(
            server_name=parameters.get("name") or parameters["url"],
            server_path=parameters["url"],
            client_type=parameters["transport"],
            auth_headers=headers,
        )
        client = _ConfiguredNativeClient(config, parameters.get("httpx_client_factory"))
        # Connect and disconnect in this owner task: MCP uses task-bound cancel scopes.
        self._stack.push_async_callback(client.disconnect, timeout=self.close_timeout_seconds)
        try:
            if not await client.connect(timeout=self.connect_timeout_seconds):
                raise MCPConnectionTimeoutError("Jiuwen MCP connection failed")
            cards = await client.list_tools(timeout=self.connect_timeout_seconds)
        except Exception as exc:
            failure = MCPConnectionFailure(url=parameters["url"], transport=parameters["transport"])
            failure.__cause__ = exc
            # Retain the cause before task-bound MCP cleanup can cancel this owner.
            with self._lock:
                if self._startup_error is None:
                    self._startup_error = failure
            raise failure from exc
        return client, {card.name for card in cards}


class _ManagedNativeClient:
    """Lazy proxy that routes calls through the owning collection on demand."""

    def __init__(self, owner, call_fn, remote_name, hidden_fields=(), configured_arguments=None):
        self.owner, self._call_fn = owner, call_fn
        self.remote_name = remote_name
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
            self._call_fn, arguments,
        )
        try:
            return await asyncio.wait_for(asyncio.wrap_future(execution.future), owner.tool_timeout_seconds)
        except MCPConnectionTimeoutError:
            # Lazy connect failed inside the tool call; keep the connection
            # error instead of misreporting it as the tool deadline.
            raise
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
            # Empty collections and explicit null are valid MCP argument values.
            # Keep native schema validation and formatting, but never erase them.
            kwargs["skip_none_value"] = False
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

    async def disconnect(self, *, timeout=None):
        """Let the session owner observe transport failures surfaced by task-group cleanup."""
        try:
            await self._exit_stack.aclose()
        finally:
            self._session = self._client = self._read = self._write = None
            self._is_disconnected = True
        return True

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
