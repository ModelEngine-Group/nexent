# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from functools import wraps
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.tool import ToolResult

from tool_collection.mcp.nl2agent_mcp_tools import (
    DISCOVER_REQUIREMENTS_DESCRIPTION,
    DISCOVER_REQUIREMENTS_LOCAL_NAME,
    READ_CONFIGURATION_DESCRIPTION,
    READ_GENERATION_CONTEXT_DESCRIPTION,
    READ_GENERATION_CONTEXT_LOCAL_NAME,
    READ_CONFIGURATION_LOCAL_NAME,
    SAVE_CONFIGURATION_DESCRIPTION,
    SAVE_CONFIGURATION_LOCAL_NAME,
    NL2AGENT_CONVERSATION_ID_HEADER,
    NL2AGENT_MCP_TOOL_META,
    NL2AGENT_RECEIPT_KEY,
    NL2AGENT_RUN_ID_HEADER,
    NL2A_MCP_SERVICE_NAME,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_LOCAL_NAME,
    RECOMMEND_RESOURCES_DESCRIPTION,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    SHOW_RESOURCE_CARD_DESCRIPTION,
    SHOW_RESOURCE_CARD_LOCAL_NAME,
    VALIDATE_AGENT_GENERATION_COMPLETE_DESCRIPTION,
    VALIDATE_AGENT_GENERATION_COMPLETE_LOCAL_NAME,
    VERIFY_REQUIREMENTS_DESCRIPTION,
    VERIFY_REQUIREMENTS_LOCAL_NAME,
    nl2a_wrapper as _nl2a_wrapper,
    recommend_resources as _recommend_resources,
    save_agent_draft_fields as _save_agent_draft_fields,
    search_installed_mcp_tools as _search_installed_mcp_tools,
    search_installed_resources as _search_installed_resources,
    search_uninstalled_resources as _search_uninstalled_resources,
    validate_agent_generation_complete as _validate_agent_generation_complete,
)
from tool_collection.mcp.nl2agent_resource_tools import (
    discover_requirements,
    read_generation_context,
    show_resource_card,
    verify_requirements,
)
from tool_collection.mcp.nl2agent_configuration_tools import read_agent_configuration, save_agent_configuration


def _attach_receipt(tool, *, card: bool = False):
    """Keep legacy tool functions compatible while publishing trusted MCP metadata."""

    @wraps(tool)
    async def wrapped(*args, **kwargs):
        output = await tool(*args, **kwargs)
        if isinstance(output, ToolResult):
            return output
        try:
            headers = get_http_request().headers
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


nl2agent_mcp_service = FastMCP(NL2A_MCP_SERVICE_NAME)
nl2agent_mcp_service.tool(read_generation_context, name=READ_GENERATION_CONTEXT_LOCAL_NAME,
                          description=READ_GENERATION_CONTEXT_DESCRIPTION, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(read_agent_configuration, name=READ_CONFIGURATION_LOCAL_NAME,
                          description=READ_CONFIGURATION_DESCRIPTION, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(save_agent_configuration, name=SAVE_CONFIGURATION_LOCAL_NAME,
                          description=SAVE_CONFIGURATION_DESCRIPTION, output_schema=None, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(discover_requirements, name=DISCOVER_REQUIREMENTS_LOCAL_NAME,
                          description=DISCOVER_REQUIREMENTS_DESCRIPTION, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(verify_requirements, name=VERIFY_REQUIREMENTS_LOCAL_NAME,
                          description=VERIFY_REQUIREMENTS_DESCRIPTION, output_schema=None, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(show_resource_card, name=SHOW_RESOURCE_CARD_LOCAL_NAME,
                          description=SHOW_RESOURCE_CARD_DESCRIPTION, output_schema=None, meta=NL2AGENT_MCP_TOOL_META)
nl2agent_mcp_service.tool(
    _search_installed_mcp_tools,
    name=SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    description=SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _search_installed_resources,
    name=SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    description=SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _search_uninstalled_resources,
    name=SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    description=SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _recommend_resources,
    name=RECOMMEND_RESOURCES_LOCAL_NAME,
    description=RECOMMEND_RESOURCES_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _attach_receipt(_save_agent_draft_fields),
    name=SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    description=SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
    output_schema=None,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _attach_receipt(_validate_agent_generation_complete),
    name=VALIDATE_AGENT_GENERATION_COMPLETE_LOCAL_NAME,
    description=VALIDATE_AGENT_GENERATION_COMPLETE_DESCRIPTION,
    output_schema=None,
    meta=NL2AGENT_MCP_TOOL_META,
)
nl2agent_mcp_service.tool(
    _attach_receipt(_nl2a_wrapper, card=True),
    name=NL2A_WRAPPER_LOCAL_NAME,
    description=NL2A_WRAPPER_DESCRIPTION,
    output_schema=None,
    meta=NL2AGENT_MCP_TOOL_META,
)
