# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management adapter for the per-run MCP server catalog (OPS-MCP-TOOL-MONITORING-20261118).

Tenant database lookups stay in Management; URL-to-identity assembly lives in
``infrastructure.monitoring.catalog`` so Runtime images never need this
module. Lookups degrade to an omitted catalog because capture failures must
never interrupt the business run.
"""

import logging

from infrastructure.monitoring.catalog import (
    build_mcp_server_catalog as _build_catalog,
    converted_tool_names_from_services,
    select_run_monitoring_catalog,
)


logger = logging.getLogger(__name__)


def query_converted_tool_names(tenant_id):
    """Collect the OpenAPI-converted tool names registered on the tenant MCP server."""
    try:
        from management.db.tool.outer_api import query_available_openapi_services

        services = query_available_openapi_services(tenant_id)
    except Exception as error:
        logger.warning("event=monitoring_catalog_openapi_lookup_failed error=%s", type(error).__name__)
        return set()
    return converted_tool_names_from_services(services)


def _mcp_records_for_tenant(tenant_id):
    try:
        from management.db.mcp.remote import get_mcp_records_by_tenant

        return get_mcp_records_by_tenant(tenant_id=tenant_id)
    except Exception as error:
        logger.warning("event=monitoring_catalog_record_lookup_failed error=%s", type(error).__name__)
        return []


def build_mcp_server_catalog(used_mcp_urls, mcp_records, local_server_url, converted_tool_names):
    """Management-facing alias of the shared pure assembler."""
    return _build_catalog(used_mcp_urls, mcp_records, local_server_url, converted_tool_names)


def build_run_monitoring_catalog(tenant_id, used_mcp_urls, mcp_records, local_server_url, *, enabled, is_debug):
    """Assemble the per-run catalog from Management-shaped record dicts; None when omitted."""
    if not enabled or is_debug or not used_mcp_urls:
        return None
    try:
        converted = query_converted_tool_names(tenant_id)
        return _build_catalog(used_mcp_urls, mcp_records, local_server_url, converted) or None
    except Exception as error:
        logger.warning("event=monitoring_catalog_build_failed error=%s", type(error).__name__)
        return None


def build_run_monitoring_catalog_from_db(tenant_id, used_mcp_urls, mcp_rows, local_server_url, *, enabled, is_debug):
    """Assemble the per-run catalog from unified infrastructure MCP record rows.

    ``mcp_rows`` are ``McpRecord`` dicts keyed by persistence column names
    (``mcp_server``/``mcp_name``); they are mapped to the catalog record shape
    and delegated to the shared assembler. Container records keep
    ``container_id``/``config_json`` so container classification survives.
    """
    if not enabled or is_debug or not used_mcp_urls:
        return None
    mapped = [
        {
            "remote_mcp_server": row.get("mcp_server"),
            "remote_mcp_server_name": row.get("mcp_name"),
            "status": row.get("status"),
            "mcp_id": row.get("mcp_id"),
            "container_id": row.get("container_id"),
            "config_json": row.get("config_json"),
        }
        for row in (mcp_rows or [])
        if isinstance(row, dict)
    ]
    return select_run_monitoring_catalog(mapped, used_mcp_urls, local_server_url, query_converted_tool_names(tenant_id))


def prepare_tenant_monitoring_catalog(tenant_id, local_server_url, *, enabled=True):
    """Build the full tenant catalog for a prepared payload; None when omitted.

    Management attaches this to the prepared run payload; Runtime filters it to
    the URLs each run materializes. Failures degrade to an omitted catalog.
    """
    if not enabled:
        return None
    try:
        local_server_url = local_server_url if local_server_url else None
        records = _mcp_records_for_tenant(tenant_id)
        if not records:
            return None
        return select_run_monitoring_catalog(
            records,
            [record.get("remote_mcp_server") for record in records if record.get("remote_mcp_server")],
            local_server_url,
            query_converted_tool_names(tenant_id),
        )
    except Exception as error:
        logger.warning("event=monitoring_catalog_prepare_failed error=%s", type(error).__name__)
        return None
