# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Local MCP read and write tools for ordinary Agent configuration."""

import json
import logging
from uuid import uuid4

from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.tool import ToolResult
from pydantic import ValidationError

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.exceptions import (
    AgentDraftEditError, TagManagementConflictError, TagManagementNotFoundError, UnauthorizedError,
)
from contracts.nl2agent_configuration import ConfigurationSection
from contracts.tag import AuthenticatedCaller
from gateway.authentication.auth import get_current_user_context
from services.nl2agent_configuration import ConfigurationError, read_configuration, save_configuration
from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_AGENT_ID_HEADER, NL2AGENT_CONVERSATION_ID_HEADER, NL2AGENT_POLICY_CLARIFICATION_HEADER,
    NL2AGENT_RECEIPT_KEY, NL2AGENT_RUN_ID_HEADER,
)

logger = logging.getLogger(__name__)


def _context():
    headers = get_http_request().headers
    agent_id = int(headers.get(NL2AGENT_AGENT_ID_HEADER, "0"))
    if agent_id <= 0 or not headers.get(NL2AGENT_RUN_ID_HEADER):
        raise ConfigurationError("invalid_configuration_context")
    user_id, tenant_id, role = get_current_user_context(headers.get("Authorization"))
    return AuthenticatedCaller(user_id, tenant_id, role, can_edit_all=role in CAN_EDIT_ALL_USER_ROLES), agent_id, headers


def _error(error):
    if isinstance(error, AgentDraftEditError):
        code = error.code
    elif isinstance(error, ConfigurationError):
        code = str(error)
    elif isinstance(error, (ValidationError, TagManagementConflictError, TagManagementNotFoundError, ValueError)):
        code = "invalid_configuration"
    elif isinstance(error, (PermissionError, UnauthorizedError)):
        code = "unauthorized"
    else:
        logger.exception("NL2Agent configuration operation failed")
        code = "configuration_operation_failed"
    return {"status": "error", "code": code,
            "retryable": code in {"configuration_changed", "configuration_operation_failed"}}


async def read_agent_configuration(section: ConfigurationSection) -> dict:
    try:
        caller, agent_id, _ = _context()
        values = await read_configuration(caller, agent_id, section)
        return {"status": "success", "agent_id": agent_id, "section": section, "configuration": values}
    except Exception as error:
        return _error(error)


async def save_agent_configuration(section: ConfigurationSection, changes: dict) -> ToolResult:
    try:
        caller, agent_id, headers = _context()
        if (section == "advanced" and "enable_protocol_repair_retry" in changes
                and headers.get(NL2AGENT_POLICY_CLARIFICATION_HEADER) == "true"):
            raise ConfigurationError("policy_clarification_required")
        fields = await save_configuration(caller, agent_id, section, changes)
    except Exception as error:
        return ToolResult(content=json.dumps(_error(error)))

    return ToolResult(
        content=json.dumps({"status": "success", "agent_id": agent_id, "section": section, "updated_fields": fields}),
        meta={NL2AGENT_RECEIPT_KEY: {
            "event_id": uuid4().hex, "run_id": headers[NL2AGENT_RUN_ID_HEADER],
            "conversation_id": headers.get(NL2AGENT_CONVERSATION_ID_HEADER, ""),
            "payload": {"event": "agent_draft_fields_saved", "agent_id": agent_id, "updated_fields": fields},
        }},
    )
