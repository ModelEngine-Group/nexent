# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Per-run MCP server catalog for monitoring facts (OPS-MCP-TOOL-MONITORING-20261118).

Run preparation resolves every used MCP URL into a server identity entry so SDK
facts never guess identity and never carry raw transport strings (design
D-003/D-004). The URL-to-type mapping is pure and unit-tested with injected
inputs; tenant lookups degrade to an omitted catalog because capture failures
must never interrupt the business run.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Mirrors FastMCP's OpenAPI default tool naming (fastmcp/server/openapi/server.py
# ``_generate_default_name`` + ``_slugify``); pinned against the real
# implementation by test_monitoring_catalog.py. Revisit when the FastMCP
# dependency is upgraded.
_SLUGIFY_SEPARATORS = re.compile(r"[\s\-\.]+")
_SLUGIFY_ILLEGAL = re.compile(r"[^a-zA-Z0-9_]")
_SLUGIFY_REPEATS = re.compile(r"_+")
_MAX_TOOL_NAME_LENGTH = 56


def _slugify(text: str) -> str:
    slug = _SLUGIFY_SEPARATORS.sub("_", text)
    slug = _SLUGIFY_ILLEGAL.sub("", slug)
    slug = _SLUGIFY_REPEATS.sub("_", slug)
    return slug.strip("_")


def _openapi_tool_names(openapi_json: dict) -> set:
    """Derive the FastMCP default tool names for one OpenAPI spec."""
    names = set()
    paths = (openapi_json or {}).get("paths") or {}
    if not isinstance(paths, dict):
        return names
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, detail in methods.items():
            if not isinstance(detail, dict):
                continue
            operation_id = detail.get("operationId")
            if operation_id:
                name = str(operation_id).split("__")[0]
            else:
                # FastMCP parses route methods uppercased (openapi parser).
                name = detail.get("summary") or f"{str(method).upper()}_{path}"
            names.add(_slugify(name)[:_MAX_TOOL_NAME_LENGTH])
    return names


def query_converted_tool_names(tenant_id):
    """Collect the OpenAPI-converted tool names registered on the tenant MCP server."""
    names = set()
    try:
        from management.db.tool.outer_api import query_available_openapi_services

        services = query_available_openapi_services(tenant_id)
    except Exception as error:
        logger.warning("event=monitoring_catalog_openapi_lookup_failed error=%s", type(error).__name__)
        return names
    for service in services or []:
        spec = service.get("openapi_json") if isinstance(service, dict) else None
        if isinstance(spec, dict):
            names.update(_openapi_tool_names(spec))
    return names


def build_mcp_server_catalog(used_mcp_urls, mcp_records, local_server_url, converted_tool_names):
    """Map the used MCP URLs to monitoring identity entries (design section 3).

    Entries are plain dicts ``{url, mcp_server_id, mcp_server_name,
    mcp_server_type}``. The tenant-local endpoint hosts both built-in and
    OpenAPI-converted tools, so it carries a URL-level ``builtin`` type plus
    ``tool_types`` overrides marking converted tools as ``api_convert``; the
    SDK consults the override after the URL-level entry. URLs without a record
    are omitted so the SDK falls back to ``unknown``.
    """
    from management.services.mcp.provisioning import _is_container_record

    records_by_url = {}
    for record in mcp_records or []:
        url = record.get("remote_mcp_server") if isinstance(record, dict) else None
        if record.get("status") and url and url not in records_by_url:
            records_by_url[url] = record
    catalog = []
    for url in used_mcp_urls or []:
        record = records_by_url.get(url)
        if record is None:
            continue
        if url == local_server_url:
            server_type = "builtin"
            tool_types = {name: "api_convert" for name in (converted_tool_names or ())}
        elif _is_container_record(record):
            server_type = "container"
            tool_types = None
        else:
            server_type = "remote"
            tool_types = None
        entry = {
            "url": url,
            "mcp_server_id": record.get("mcp_id"),
            "mcp_server_name": record.get("remote_mcp_server_name"),
            "mcp_server_type": server_type,
        }
        if tool_types:
            entry["tool_types"] = tool_types
        catalog.append(entry)
    return catalog


def build_run_monitoring_catalog(tenant_id, used_mcp_urls, mcp_records, local_server_url, *, enabled, is_debug):
    """Assemble the per-run catalog; returns None when omitted or lookup fails."""
    if not enabled or is_debug or not used_mcp_urls:
        return None
    try:
        converted = query_converted_tool_names(tenant_id)
        return build_mcp_server_catalog(used_mcp_urls, mcp_records, local_server_url, converted)
    except Exception as error:
        logger.warning("event=monitoring_catalog_build_failed error=%s", type(error).__name__)
        return None
