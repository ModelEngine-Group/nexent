# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound MCP header passthrough — Phase 1 helpers.

This module owns every piece of logic that bridges a northbound ``metadata``
reserved field (``_mcp_headers`` / ``_mcp_headers_by_server``) into the MCP
HTTP session, plus the ``${HeaderName}`` placeholder resolution engine that
lets admin-authored MCP static headers defer identity fields to the request.

Design contract in ``nexent-doc/nexent/northbound-mcp-header-passthrough/``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from contracts.agentos import MCPExecutionBinding, SkillDerivedMCPBinding
from contracts.errors.exceptions import AppException
from infrastructure.mcp_execution import LOCAL_MCP_NAME, select_mcp_server
from infrastructure.mcp_header_passthrough import (
    apply_bound_mcp_headers, extract_passthrough_headers as extract_passthrough_headers,
    merge_static_priority as merge_static_priority, resolve_placeholders as resolve_placeholders,
    route_passthrough_headers as route_passthrough_headers, validate_mcp_header_passthrough,
)
from infrastructure.rdb.mcp_execution_records import read_mcp_execution_servers


logger = logging.getLogger("northbound-mcp-passthrough")


def prepare_bound_mcp_header_metadata(metadata, resource, tenant_id):
    """Check Northbound routes against the servers in the compiled resource tree."""
    mode, headers = extract_passthrough_headers(metadata)
    if mode is None or not headers:
        return None

    from management.db.agent.repository import search_agent_info_by_agent_id

    server_ids = set()
    pending = [resource]
    while pending:
        agent = pending.pop()
        pending.extend(agent.subagents)
        for binding in agent.tools:
            if binding.tool_id == "mcp":
                schema = MCPExecutionBinding if binding.version == "1" else SkillDerivedMCPBinding
                server_ids.add(schema.model_validate(binding.parameters).server_id)
    if mode == "by_server":
        servers = read_mcp_execution_servers(tenant_id) if server_ids else []
        usage_by_id = {row["mcp_id"]: row["mcp_name"] for row in servers}
        usage_by_id[None] = LOCAL_MCP_NAME
        hosts = []
        for server_id in server_ids:
            if server_id in usage_by_id:
                try:
                    _, host = select_mcp_server(servers, usage_by_id[server_id], tenant_id)
                except LookupError:
                    continue
                hosts.append(host)
        validate_mcp_header_passthrough(metadata, hosts)

    if not server_ids:
        return None
    agent = search_agent_info_by_agent_id(resource.agent_id, tenant_id, resource.version_no) or {}
    if not agent.get("allow_mcp_header_passthrough", False):
        return None
    key = "_mcp_headers_by_server" if mode == "by_server" else "_mcp_headers"
    return {key: headers}


def apply_mcp_header_passthrough(
    mcp_host: List[Any],
    metadata: Optional[Dict[str, Any]],
    *,
    agent_id: int,
    tenant_id: str,
    version_no: int,
    run_id: str,
) -> None:
    """Run every Phase 1 step against ``mcp_host`` in place.

    Call this AFTER the MCP host list has been assembled (static auth +
    custom headers from DB are already present) but BEFORE the list is
    handed to ``build_run_info``.  The function is deliberately defensive:
    a malformed ``mcp_host`` list leaves no trace, and a missing agent
    record is treated as "passthrough disabled" — never open the flood
    gate on a failed lookup.
    """
    if not isinstance(mcp_host, list) or not mcp_host:
        return

    from management.db.agent.repository import search_agent_info_by_agent_id

    try:
        agent_record = search_agent_info_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        ) or {}
    except Exception:
        # Never open the flood gate on a failed lookup.
        logger.warning(
            "agent_id=%s run_id=%s event=agent_lookup_failed passthrough_disabled",
            agent_id, run_id,
        )
        agent_record = {}

    # Pre-check: raise AppException before any mutation happens.  Callers that
    # want HTTP 400 instead of SSE error must run the same check BEFORE the
    # StreamingResponse is returned — this guard keeps the error semantics
    # identical everywhere apply() is called from.
    try:
        validate_mcp_header_passthrough(metadata, mcp_host)
    except AppException:
        raise
    except Exception:
        # validate never raises non-AppException in happy-path failures, but
        # a malformed mcp_host or metadata dict should be treated exactly
        # like the rest of apply — never let a tool-side issue crash the run.
        logger.warning(
            "agent_id=%s run_id=%s event=passthrough_precheck_failed",
            agent_id, run_id,
            exc_info=True,
        )

    passthrough_allowed = bool(
        agent_record.get("allow_mcp_header_passthrough", False)
    )

    apply_bound_mcp_headers(
        mcp_host, metadata, passthrough_allowed=passthrough_allowed, agent_id=agent_id, run_id=run_id,
    )
