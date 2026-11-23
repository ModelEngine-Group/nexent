# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Per-run MCP server catalog for monitoring facts (OPS-MCP-TOOL-MONITORING-20261118).

Pure URL-to-identity assembly shared by producers and preparation: Management
supplies tenant database rows as plain dicts, infrastructure maps them to
monitoring catalog entries, and the SDK consumes them through the monitoring
context. URL-to-type mapping stays pure and unit-tested with injected inputs;
tenant lookups degrade to an omitted catalog because capture failures must
never interrupt the business run.
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


def is_container_record(record: dict | None) -> bool:
    """Check if the MCP record is container-based.

    A record is considered container-based if it has:
    - container_id (Docker container ID)
    - a non-empty config_json holding a container configuration

    API-type MCPs store OpenAPI JSON in config_json and are never treated as
    containers. An empty dict config_json (e.g. `{}`) is not a container
    configuration either, so records with only an empty config_json are treated
    as plain remote MCPs instead of being misclassified as containers.
    """
    if not record:
        return False
    config_json = record.get("config_json")
    # API-type MCPs store OpenAPI JSON in config_json, not container config
    if isinstance(config_json, dict) and "openapi" in config_json:
        return False
    return record.get("container_id") is not None or (
        isinstance(config_json, dict) and bool(config_json)
    )


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


def converted_tool_names_from_services(services) -> set:
    """Collect OpenAPI-converted tool names from tenant service rows."""
    names = set()
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
        elif is_container_record(record):
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


def select_run_monitoring_catalog(mcp_records, used_mcp_urls, local_server_url, converted_tool_names):
    """Assemble the per-run catalog; returns None when empty or inputs are omitted."""
    if not used_mcp_urls or not mcp_records:
        return None
    try:
        catalog = build_mcp_server_catalog(
            used_mcp_urls, mcp_records, local_server_url, converted_tool_names)
        return catalog or None
    except Exception as error:
        logger.warning("event=monitoring_catalog_build_failed error=%s", type(error).__name__)
        return None


def filter_prepared_catalog(payload_catalog, used_mcp_urls, *, enabled, is_debug):
    """Runtime-side projection of the prepared catalog onto this run's used URLs.

    Management attaches the tenant catalog to the prepared payload; Runtime
    keeps only entries for URLs this run materialized. Never raises: capture
    must not interrupt run preparation.
    """
    if not enabled or is_debug or not used_mcp_urls or not payload_catalog:
        return None
    try:
        wanted = set(used_mcp_urls)
        selected = [entry for entry in payload_catalog
                    if isinstance(entry, dict) and entry.get("url") in wanted]
        return selected or None
    except Exception as error:
        logger.warning("event=monitoring_catalog_filter_failed error=%s", type(error).__name__)
        return None
