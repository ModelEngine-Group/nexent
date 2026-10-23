# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import time
from typing import Any, Dict, List

import requests
from contracts.constants.environment import MCP_MANAGEMENT_API
from management.db.tool.outer_api import (
    delete_openapi_service as db_delete_openapi_service,
    query_openapi_services_by_tenant,
    upsert_openapi_service,
)
from management.services.tool.common import (
    logger,
)


def import_openapi_service(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str,
    tenant_id: str,
    user_id: str,
    service_description: str = None,
    auth_enabled: bool = False,
    headers_template: Dict[str, Any] = None,
    ssl_verify: bool = True,
    force_update: bool = False,
) -> Dict[str, Any]:
    """
    Import OpenAPI JSON as an MCP service, using FastMCP.from_openapi() approach.
    All tools from the same OpenAPI spec share the same mcp_service_name.

    Args:
        service_name: MCP service name for grouping tools
        openapi_json: OpenAPI 3.x specification as dictionary
        server_url: Base URL of the REST API server
        tenant_id: Tenant ID for multi-tenancy
        user_id: User ID for audit
        service_description: Optional service description (if not provided, reads from openapi_json.info.description)
        headers_template: Optional default headers template
        force_update: If True, replace all existing tools for this service

    Returns:
        Dictionary with import result
    """
    # If service_description not provided, extract from openapi_json info
    if service_description is None:
        info = openapi_json.get("info", {})
        service_description = info.get("description") or info.get("title", "")

    # Override server URL in openapi_json if different
    openapi_spec = openapi_json.copy()
    openapi_spec["servers"] = [{"url": server_url}]

    result = upsert_openapi_service(
        service_name=service_name,
        openapi_json=openapi_spec,
        server_url=server_url,
        tenant_id=tenant_id,
        user_id=user_id,
        description=service_description,
        auth_enabled=auth_enabled,
        headers_template=headers_template,
        ssl_verify=ssl_verify,
    )

    logger.info(f"Imported service '{service_name}' for tenant {tenant_id}")
    return result


def list_openapi_services(tenant_id: str) -> List[Dict[str, Any]]:
    """
    List all OpenAPI services for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of service dictionaries
    """
    return query_openapi_services_by_tenant(tenant_id)


def delete_openapi_service(service_name: str, tenant_id: str, user_id: str) -> bool:
    """
    Delete an OpenAPI service (all tools belonging to it).

    Args:
        service_name: MCP service name
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        True if deleted, False if not found
    """
    return db_delete_openapi_service(service_name, tenant_id, user_id)


def _refresh_openapi_services_in_mcp(tenant_id: str) -> Dict[str, Any]:
    """
    Refresh OpenAPI services in MCP server via HTTP API using from_openapi approach.

    This replaces the old per-tool registration with service-level registration,
    using FastMCP.from_openapi() to batch-load all tools from each service.

    Args:
        tenant_id: Tenant ID

    Returns:
        Dictionary with refresh result
    """
    refresh_url = f"{MCP_MANAGEMENT_API}/tools/openapi_service/refresh"
    max_retries = 3
    retry_delay = 1.0

    for attempt in range(max_retries):
        try:
            response = requests.post(
                refresh_url,
                params={"tenant_id": tenant_id},
                headers={"Authorization": f"Bearer {MCP_INTERNAL_TOKEN}"},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Refreshed OpenAPI services for tenant {tenant_id}: {result}")
            return result.get("data", {})
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Failed to refresh OpenAPI services (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(
                    f"Failed to refresh OpenAPI services after {max_retries} attempts: {e}"
                )
                return {"error": str(e)}
        except Exception as e:
            logger.warning(f"Failed to refresh OpenAPI services in MCP: {e}")
            return {"error": str(e)}


def get_openapi_service_tool_map(tenant_id: str) -> Dict[str, int]:
    """Load the authenticated internal mapping used by the tool catalog sync."""
    map_url = f"{MCP_MANAGEMENT_API}/internal/tools/openapi-service-map"
    try:
        response = requests.get(
            map_url,
            params={"tenant_id": tenant_id},
            headers={"Authorization": f"Bearer {MCP_INTERNAL_TOKEN}"},
            timeout=30,
        )
        response.raise_for_status()
        return {
            item["name"]: int(item["service_id"])
            for item in response.json().get("data", [])
            if item.get("name") and item.get("service_id") is not None
        }
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        logger.warning("Failed to load OpenAPI service tool map: %s", exc)
        return {}
