"""
Database access layer for outer API services (OpenAPI to MCP conversion).
Stores one record per MCP service instead of per tool.
"""

import logging
from typing import Dict, List, Optional, Any

from database.client import get_db_session, filter_property, as_dict
from database.db_models import OuterApiService


logger = logging.getLogger("outer_api_tool_db")


def create_openapi_service(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str,
    tenant_id: str,
    user_id: str,
    description: str = None,
    headers_template: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Create a new OpenAPI service record.

    Args:
        service_name: MCP service name
        openapi_json: Complete OpenAPI JSON specification
        server_url: Base URL of the REST API server
        tenant_id: Tenant ID
        user_id: User ID for audit
        description: Optional service description
        headers_template: Optional default headers template

    Returns:
        Created service dictionary
    """
    service_dict = {
        "mcp_service_name": service_name,
        "openapi_json": openapi_json,
        "server_url": server_url,
        "tenant_id": tenant_id,
        "created_by": user_id,
        "updated_by": user_id,
        "is_available": True,
    }
    if description:
        service_dict["description"] = description
    if headers_template:
        service_dict["headers_template"] = headers_template

    with get_db_session() as session:
        new_service = OuterApiService(**filter_property(service_dict, OuterApiService))
        session.add(new_service)
        session.flush()
        return as_dict(new_service)


def upsert_openapi_service(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str,
    tenant_id: str,
    user_id: str,
    description: str = None,
    headers_template: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Create or update an OpenAPI service record.

    Args:
        service_name: MCP service name
        openapi_json: Complete OpenAPI JSON specification
        server_url: Base URL of the REST API server
        tenant_id: Tenant ID
        user_id: User ID for audit
        description: Optional service description
        headers_template: Optional default headers template

    Returns:
        Service dictionary (created or updated)
    """
    service_dict = {
        "mcp_service_name": service_name,
        "openapi_json": openapi_json,
        "server_url": server_url,
        "tenant_id": tenant_id,
        "updated_by": user_id,
        "is_available": True,
    }
    if description:
        service_dict["description"] = description
    if headers_template:
        service_dict["headers_template"] = headers_template

    with get_db_session() as session:
        existing = session.query(OuterApiService).filter(
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.mcp_service_name == service_name,
            OuterApiService.delete_flag != 'Y'
        ).first()

        if existing:
            for key, value in service_dict.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            session.flush()
            return as_dict(existing)
        else:
            service_dict["created_by"] = user_id
            new_service = OuterApiService(**filter_property(service_dict, OuterApiService))
            session.add(new_service)
            session.flush()
            return as_dict(new_service)


def query_services_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Query all OpenAPI services for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of service dictionaries
    """
    with get_db_session() as session:
        services = session.query(OuterApiService).filter(
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).all()
        return [as_dict(svc) for svc in services]


def query_available_services(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Query all available OpenAPI services for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of available service dictionaries
    """
    with get_db_session() as session:
        services = session.query(OuterApiService).filter(
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y',
            OuterApiService.is_available == True
        ).all()
        return [as_dict(svc) for svc in services]


def query_service_by_name(service_name: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Query OpenAPI service by service name.

    Args:
        service_name: MCP service name
        tenant_id: Tenant ID

    Returns:
        Service dictionary or None
    """
    with get_db_session() as session:
        service = session.query(OuterApiService).filter(
            OuterApiService.mcp_service_name == service_name,
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).first()
        return as_dict(service) if service else None


def query_service_by_id(service_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Query OpenAPI service by ID.

    Args:
        service_id: Service ID
        tenant_id: Tenant ID

    Returns:
        Service dictionary or None
    """
    with get_db_session() as session:
        service = session.query(OuterApiService).filter(
            OuterApiService.id == service_id,
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).first()
        return as_dict(service) if service else None


def update_service(
    service_name: str,
    service_data: Dict[str, Any],
    tenant_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update an OpenAPI service record.

    Args:
        service_name: MCP service name
        service_data: Dictionary containing updated service information
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        Updated service dictionary or None if not found
    """
    service_dict = service_data.copy()
    service_dict["updated_by"] = user_id

    with get_db_session() as session:
        service = session.query(OuterApiService).filter(
            OuterApiService.mcp_service_name == service_name,
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).first()

        if not service:
            return None

        for key, value in service_dict.items():
            if hasattr(service, key):
                setattr(service, key, value)

        session.flush()
        return as_dict(service)


def delete_service(service_name: str, tenant_id: str, user_id: str) -> bool:
    """
    Soft delete an OpenAPI service record.

    Args:
        service_name: MCP service name
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        True if deleted, False if not found
    """
    with get_db_session() as session:
        service = session.query(OuterApiService).filter(
            OuterApiService.mcp_service_name == service_name,
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).first()

        if not service:
            return False

        service.delete_flag = 'Y'
        service.updated_by = user_id
        return True


def delete_service_by_id(service_id: int, tenant_id: str, user_id: str) -> bool:
    """
    Soft delete an OpenAPI service by ID.

    Args:
        service_id: Service ID
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        True if deleted, False if not found
    """
    with get_db_session() as session:
        service = session.query(OuterApiService).filter(
            OuterApiService.id == service_id,
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).first()

        if not service:
            return False

        service.delete_flag = 'Y'
        service.updated_by = user_id
        return True


def delete_all_services(tenant_id: str, user_id: str) -> int:
    """
    Soft delete all OpenAPI services for a tenant.

    Args:
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        Number of deleted services
    """
    with get_db_session() as session:
        count = session.query(OuterApiService).filter(
            OuterApiService.tenant_id == tenant_id,
            OuterApiService.delete_flag != 'Y'
        ).update({
            OuterApiService.delete_flag: 'Y',
            OuterApiService.updated_by: user_id
        })
        return count


# Backward compatibility aliases
def query_available_openapi_services(tenant_id: str) -> List[Dict[str, Any]]:
    """Alias for query_available_services."""
    return query_available_services(tenant_id)


def query_openapi_services_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Alias for query_services_by_tenant."""
    return query_services_by_tenant(tenant_id)


def delete_openapi_service(service_name: str, tenant_id: str, user_id: str) -> bool:
    """Alias for delete_service."""
    return delete_service(service_name, tenant_id, user_id)


# Deprecated functions - kept for compatibility but will be removed
def create_outer_api_tool(tool_data: Dict[str, Any], tenant_id: str, user_id: str) -> Dict[str, Any]:
    """Deprecated: Use create_openapi_service instead."""
    logger.warning("create_outer_api_tool is deprecated, use create_openapi_service")
    raise NotImplementedError("create_outer_api_tool is deprecated, use create_openapi_service")


def batch_create_outer_api_tools(
    tools_data: List[Dict[str, Any]],
    tenant_id: str,
    user_id: str
) -> List[Dict[str, Any]]:
    """Deprecated: Use upsert_openapi_service instead."""
    logger.warning("batch_create_outer_api_tools is deprecated, use upsert_openapi_service")
    raise NotImplementedError("batch_create_outer_api_tools is deprecated, use upsert_openapi_service")


def query_outer_api_tools_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Deprecated: Use query_services_by_tenant instead."""
    logger.warning("query_outer_api_tools_by_tenant is deprecated, use query_services_by_tenant")
    raise NotImplementedError("query_outer_api_tools_by_tenant is deprecated, use query_services_by_tenant")


def query_available_outer_api_tools(tenant_id: str) -> List[Dict[str, Any]]:
    """Deprecated: Use query_available_services instead."""
    logger.warning("query_available_outer_api_tools is deprecated, use query_available_services")
    raise NotImplementedError("query_available_outer_api_tools is deprecated, use query_available_services")


def query_outer_api_tool_by_id(tool_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Deprecated: Use query_service_by_id instead."""
    logger.warning("query_outer_api_tool_by_id is deprecated, use query_service_by_id")
    raise NotImplementedError("query_outer_api_tool_by_id is deprecated, use query_service_by_id")


def query_outer_api_tool_by_name(name: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Deprecated: Use query_service_by_name instead."""
    logger.warning("query_outer_api_tool_by_name is deprecated, use query_service_by_name")
    raise NotImplementedError("query_outer_api_tool_by_name is deprecated, use query_service_by_name")


def update_outer_api_tool(
    tool_id: int,
    tool_data: Dict[str, Any],
    tenant_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """Deprecated: Use update_service instead."""
    logger.warning("update_outer_api_tool is deprecated, use update_service")
    raise NotImplementedError("update_outer_api_tool is deprecated, use update_service")


def delete_outer_api_tool(tool_id: int, tenant_id: str, user_id: str) -> bool:
    """Deprecated: Use delete_service_by_id instead."""
    logger.warning("delete_outer_api_tool is deprecated, use delete_service_by_id")
    raise NotImplementedError("delete_outer_api_tool is deprecated, use delete_service_by_id")


def delete_all_outer_api_tools(tenant_id: str, user_id: str) -> int:
    """Deprecated: Use delete_all_services instead."""
    logger.warning("delete_all_outer_api_tools is deprecated, use delete_all_services")
    raise NotImplementedError("delete_all_outer_api_tools is deprecated, use delete_all_services")


def create_openapi_service_with_tools(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str,
    tenant_id: str,
    user_id: str,
    service_description: str = None
) -> Dict[str, Any]:
    """Alias for create_openapi_service."""
    return create_openapi_service(
        service_name=service_name,
        openapi_json=openapi_json,
        server_url=server_url,
        tenant_id=tenant_id,
        user_id=user_id,
        description=service_description
    )


def sync_openapi_service(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str,
    tools_data: List[Dict[str, Any]],
    tenant_id: str,
    user_id: str,
    service_description: str = None
) -> Dict[str, Any]:
    """Alias for upsert_openapi_service (tools_data is ignored)."""
    logger.warning("sync_openapi_service: tools_data parameter is deprecated, tools are now derived from openapi_json")
    return upsert_openapi_service(
        service_name=service_name,
        openapi_json=openapi_json,
        server_url=server_url,
        tenant_id=tenant_id,
        user_id=user_id,
        description=service_description
    )


def sync_outer_api_tools(
    tools_data: List[Dict[str, Any]],
    tenant_id: str,
    user_id: str
) -> Dict[str, Any]:
    """Deprecated: This function no longer operates at tool level."""
    logger.warning("sync_outer_api_tools is deprecated, use upsert_openapi_service")
    raise NotImplementedError("sync_outer_api_tools is deprecated, use upsert_openapi_service")
