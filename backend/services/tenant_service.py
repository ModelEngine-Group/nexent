"""
Tenant service for managing tenant operations
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from database.tenant_config_db import (
    get_single_config_info,
    insert_config,
    update_config_by_tenant_config_id,
    get_all_tenant_ids
)
from database.user_tenant_db import get_users_by_tenant_id
from database.group_db import add_group
from consts.const import TENANT_NAME, TENANT_ID, DEFAULT_GROUP_ID
from consts.exceptions import NotFoundException, ValidationError, UserRegistrationException

logger = logging.getLogger(__name__)


def get_tenant_info(tenant_id: str) -> Dict[str, Any]:
    """
    Get tenant information by tenant ID

    Args:
        tenant_id (str): Tenant ID

    Returns:
        Dict[str, Any]: Tenant information

    Raises:
        NotFoundException: When tenant not found
    """
    # Get tenant name
    name_config = get_single_config_info(tenant_id, TENANT_NAME)
    if not name_config:
        logging.warning(f"The name of tenant {tenant_id} not found.")

    group_config = get_single_config_info(tenant_id, DEFAULT_GROUP_ID)

    tenant_info = {
        "tenant_id": tenant_id,
        "tenant_name": name_config.get("config_value") if name_config else "",
        "default_group_id": group_config.get("config_value") if group_config else ""
    }

    return tenant_info


def get_all_tenants() -> List[Dict[str, Any]]:
    """
    Get all tenants

    Returns:
        List[Dict[str, Any]]: List of all tenant information
    """
    tenant_ids = get_all_tenant_ids()
    tenants = []

    for tenant_id in tenant_ids:
        try:
            tenant_info = get_tenant_info(tenant_id)
            tenants.append(tenant_info)
        except NotFoundException:
            # Return tenant with basic info but empty name for frontend to show as "unnamed tenant"
            logging.warning(f"Tenant info of {tenant_id} not found. Returning basic tenant structure.")
            tenant_info = {
                "tenant_id": tenant_id,
                "tenant_name": "",
                "default_group_id": ""
            }
            tenants.append(tenant_info)

    return tenants


def create_tenant(tenant_name: str, created_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new tenant with default group

    Args:
        tenant_name (str): Tenant name
        created_by (Optional[str]): Created by user ID

    Returns:
        Dict[str, Any]: Created tenant information

    Raises:
        ValidationError: When tenant creation fails
    """
    # Generate a random UUID for tenant_id
    tenant_id = str(uuid.uuid4())

    # Check if tenant already exists (extremely unlikely with UUID, but good practice)
    try:
        existing_tenant = get_tenant_info(tenant_id)
        if existing_tenant:
            raise ValidationError(f"Tenant {tenant_id} already exists")
    except NotFoundException:
        # Tenant doesn't exist, which is what we want
        pass

    # Validate tenant name
    if not tenant_name or not tenant_name.strip():
        raise ValidationError("Tenant name cannot be empty")

    try:
        # Create default group first
        default_group_id = _create_default_group_for_tenant(tenant_id, created_by)

        # Create tenant ID configuration
        tenant_id_data = {
            "tenant_id": tenant_id,
            "config_key": TENANT_ID,
            "config_value": tenant_id,
            "created_by": created_by,
            "updated_by": created_by
        }
        id_success = insert_config(tenant_id_data)
        if not id_success:
            raise ValidationError("Failed to create tenant ID configuration")

        # Create tenant name configuration
        tenant_name_data = {
            "tenant_id": tenant_id,
            "config_key": TENANT_NAME,
            "config_value": tenant_name.strip(),
            "created_by": created_by,
            "updated_by": created_by
        }
        name_success = insert_config(tenant_name_data)
        if not name_success:
            raise ValidationError("Failed to create tenant name configuration")

        # Create default group ID configuration
        group_config_data = {
            "tenant_id": tenant_id,
            "config_key": DEFAULT_GROUP_ID,
            "config_value": str(default_group_id),
            "created_by": created_by,
            "updated_by": created_by
        }
        group_success = insert_config(group_config_data)
        if not group_success:
            raise ValidationError("Failed to create tenant default group configuration")

        tenant_info = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name.strip(),
            "default_group_id": str(default_group_id)
        }

        logger.info(f"Created tenant {tenant_id} with name '{tenant_name}' and default group {default_group_id}")
        return tenant_info

    except Exception as e:
        logger.error(f"Failed to create tenant {tenant_id}: {str(e)}")
        raise ValidationError(f"Failed to create tenant: {str(e)}")


def update_tenant_info(tenant_id: str, tenant_name: str, updated_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Update tenant information

    Args:
        tenant_id (str): Tenant ID
        tenant_name (str): New tenant name
        updated_by (Optional[str]): Updated by user ID

    Returns:
        Dict[str, Any]: Updated tenant information

    Raises:
        NotFoundException: When tenant not found
        ValidationError: When tenant name is invalid
    """
    # Check if tenant exists and get current name config
    name_config = get_single_config_info(tenant_id, TENANT_NAME)
    if not name_config:
        raise NotFoundException(f"Tenant {tenant_id} not found")

    # Validate tenant name
    if not tenant_name or not tenant_name.strip():
        raise ValidationError("Tenant name cannot be empty")

    # Update tenant name
    success = update_config_by_tenant_config_id(
        name_config["tenant_config_id"],
        tenant_name.strip()
    )
    if not success:
        raise ValidationError("Failed to update tenant name")

    # Return updated tenant information
    updated_tenant = get_tenant_info(tenant_id)
    logger.info(f"Updated tenant {tenant_id} name to '{tenant_name}'")
    return updated_tenant


def delete_tenant(tenant_id: str, deleted_by: Optional[str] = None) -> bool:
    """
    Delete tenant (placeholder for future implementation)
    NOTE: Deletion logic is complex and not yet implemented

    Args:
        tenant_id (str): Tenant ID
        deleted_by (Optional[str]): Deleted by user ID

    Returns:
        bool: Always returns False as this is not yet implemented

    Raises:
        ValidationError: Always raised as this is not yet implemented
    """
    raise NotImplementedError("Tenant deletion is not yet implemented due to complex dependencies")


def _create_default_group_for_tenant(tenant_id: str, created_by: Optional[str] = None) -> int:
    """
    Create a default group for a new tenant

    Args:
        tenant_id (str): Tenant ID
        created_by (Optional[str]): Created by user ID

    Returns:
        int: Created default group ID

    Raises:
        ValidationError: When default group creation fails
    """
    try:
        default_group_name = "Default Group"
        group_id = add_group(
            tenant_id=tenant_id,
            group_name=default_group_name,
            group_description="Default group created automatically for new tenant",
            created_by=created_by
        )

        return group_id

    except Exception as e:
        logger.error(f"Failed to create default group for tenant {tenant_id}: {str(e)}")
        raise ValidationError(f"Failed to create default group: {str(e)}")
