# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fingerprint the response from the MCP session before either core formats it."""

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar

from mcp.types import CallToolResult
from pydantic import AnyUrl

from nexent.core.agents.resources.replay_tools import argument_digest
from nexent.core.agents.resources.tool_user_context import USER_CONTEXT_FIELDS


active_reply = ContextVar("nexent_replay_mcp_reply", default=None)


@contextmanager
def capture_reply(call, fields, probe):
    token = active_reply.set((call, fields, probe))
    try:
        yield
    finally:
        active_reply.reset(token)


async def fixture_state(session):
    """Read the test service's isolated business state through an independent MCP resource."""
    try:
        reply = await asyncio.wait_for(session.read_resource(AnyUrl("nexent-eval://fixture/state")), timeout=3)
        if len(reply.contents) != 1:
            return None
        value = getattr(reply.contents[0], "text", None)
        if not isinstance(value, str) or len(value.encode()) > 65536:
            return None
        state = json.loads(value)
        return argument_digest(state) if isinstance(state, dict) else None
    except Exception:
        # A failed probe is missing evidence. Keep the tool's original result or exception.
        return None


async def call_session_tool(session, name, arguments):
    capture = active_reply.get()
    required = capture[2].get("initial_digest") if capture else None
    before = await fixture_state(session) if required else None
    if required and before != required:
        capture[0]["mcp_fixture_unready"] = True
        raise ValueError("MCP replay fixture is unavailable or has a different initial state")
    response = await session.call_tool(name, arguments)
    after = await fixture_state(session) if required else None
    record_reply(name, arguments, response, before=before, after=after)
    return response


def record_reply(remote_name, arguments, response, *, before=None, after=None):
    capture = active_reply.get()
    if (
        capture is None
        or not isinstance(response, CallToolResult)
        or not isinstance(remote_name, str)
        or not 0 < len(remote_name) <= 256
    ):
        return
    call, fields, probe = capture
    kind = probe["kind"]
    # Multiple physical calls beneath a single tool invocation cannot be attributed.
    if "mcp_reply" in call:
        call["mcp_reply"] = None
        return
    call["mcp_reply"] = None
    values = arguments or {}
    if not isinstance(values, dict) or set(fields).intersection(USER_CONTEXT_FIELDS):
        return
    if kind == "structured":
        value = response.structuredContent
    else:
        value = (
            response.content[0].text
            if len(response.content) == 1 and response.content[0].type == "text"
            else None
        )
    try:
        observed = {
            **({"before": before, "after": after} if probe.get("initial_digest") else {}),
            "remote": remote_name,
            "kind": kind,
            "error": response.isError,
            "exact_fields": set(values).difference(USER_CONTEXT_FIELDS) == set(fields),
            "inputs": argument_digest({key: values[key] for key in fields if key in values}),
            "content": argument_digest(value) if value is not None else None,
        }
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return
    call["mcp_reply"] = observed
