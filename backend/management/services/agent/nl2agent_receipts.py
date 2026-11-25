# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Serialize server-owned tool receipts for MCP and signed AgentOS callbacks."""
import json
from functools import wraps
from uuid import uuid4
from fastmcp.tools.tool import ToolResult
from management.services.agent import nl2agent_tools as tools
from infrastructure.nl2agent_tool_config import (
    NL2AGENT_RUN_ID_HEADER, NL2AGENT_CONVERSATION_ID_HEADER, NL2AGENT_RECEIPT_KEY,
)

def attach_receipt(tool, *, card: bool = False, headers_provider=None):
    """Keep legacy tool functions compatible while publishing trusted MCP metadata."""

    @wraps(tool)
    async def wrapped(*args, **kwargs):
        output = await tool(*args, **kwargs)
        if isinstance(output, ToolResult):
            return output
        if not isinstance(output, str):
            return output
        try:
            headers = headers_provider() if headers_provider is not None else tools.tool_headers()
        except RuntimeError:
            return output
        run_id = headers.get(NL2AGENT_RUN_ID_HEADER)
        if not run_id:
            return output
        if card:
            if not output.startswith("<nl2a>\n"):
                return output
            payload, _, content = output.removeprefix("<nl2a>\n").partition("\n</nl2a>\n")
        else:
            content, delimiter, payload = output.partition("\n<nl2a_state>")
            if not delimiter:
                return output
            payload = payload.removesuffix("</nl2a_state>")
        return ToolResult(content=content, meta={
            NL2AGENT_RECEIPT_KEY: {
                "event_id": uuid4().hex,
                "run_id": run_id,
                "conversation_id": headers.get(NL2AGENT_CONVERSATION_ID_HEADER, ""),
                "payload": json.loads(payload),
            },
        })

    return wrapped
