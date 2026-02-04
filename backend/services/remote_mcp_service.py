import logging
import os
import tempfile

from fastmcp import Client

from consts.const import CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT, PERMISSION_READ
from consts.exceptions import MCPConnectionError, MCPNameIllegal
from database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    delete_mcp_record_by_container_id,
    get_mcp_records_by_tenant,
    check_mcp_name_exists,
    update_mcp_status_by_name_and_url,
    update_mcp_record_by_name_and_url,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from services.mcp_container_service import MCPContainerManager

logger = logging.getLogger("remote_mcp_service")


async def mcp_server_health(remote_mcp_server: str) -> bool:
    try:
        client = Client(remote_mcp_server)
        async with client:
            connected = client.is_connected()
            return connected
    except BaseException as e:
        logger.error(
            f"Remote MCP server health check failed: {e}", exc_info=True)
        # Prevent library-level exits (e.g., SystemExit) from crashing the service
        raise MCPConnectionError("MCP connection failed")


async def add_remote_mcp_server_list(
    tenant_id: str,
    user_id: str,
    remote_mcp_server: str,
    remote_mcp_server_name: str,
    container_id: str | None = None,
):

    # check if MCP name already exists
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name, tenant_id=tenant_id):
        logger.error(
            f"MCP name already exists, tenant_id: {tenant_id}, remote_mcp_server_name: {remote_mcp_server_name}")
        raise MCPNameIllegal("MCP name already exists")

    # check if the address is available
    if not await mcp_server_health(remote_mcp_server=remote_mcp_server):
        raise MCPConnectionError("MCP connection failed")

    # update the PG database record
    insert_mcp_data = {
        "mcp_name": remote_mcp_server_name,
        "mcp_server": remote_mcp_server,
        "status": True,
        "container_id": container_id,
    }
    create_mcp_record(mcp_data=insert_mcp_data,
                      tenant_id=tenant_id, user_id=user_id)


async def delete_remote_mcp_server_list(tenant_id: str,
                                        user_id: str,
                                        remote_mcp_server: str,
                                        remote_mcp_server_name: str):
    # delete the record in the PG database
    delete_mcp_record_by_name_and_url(mcp_name=remote_mcp_server_name,
                                      mcp_server=remote_mcp_server,
                                      tenant_id=tenant_id,
                                      user_id=user_id)


async def update_remote_mcp_server_list(
    update_data,
    tenant_id: str,
    user_id: str,
):
    """
    Update an existing remote MCP server record.

    Args:
        update_data: MCPUpdateRequest containing current and new values
        tenant_id: Tenant ID
        user_id: User ID

    Raises:
        MCPNameIllegal: If the new MCP name already exists (and is different from current)
        MCPConnectionError: If the new MCP server URL is not accessible
    """
    # Check if the current record exists by verifying the name exists for this tenant
    if not check_mcp_name_exists(mcp_name=update_data.current_service_name, tenant_id=tenant_id):
        logger.error(
            f"MCP name does not exist, tenant_id: {tenant_id}, current_mcp_server_name: {update_data.current_service_name}")
        raise MCPNameIllegal("MCP name does not exist")

    # If the new name is different from the current name, check if it already exists
    if update_data.new_service_name != update_data.current_service_name:
        if check_mcp_name_exists(mcp_name=update_data.new_service_name, tenant_id=tenant_id):
            logger.error(
                f"New MCP name already exists, tenant_id: {tenant_id}, new_mcp_server_name: {update_data.new_service_name}")
            raise MCPNameIllegal("New MCP name already exists")

    # Check if the new server URL is accessible
    try:
        status = await mcp_server_health(remote_mcp_server=update_data.new_mcp_url)
    except BaseException:
        status = False

    if not status:
        logger.error(
            f"New MCP server health check failed: {update_data.new_mcp_url}")
        raise MCPConnectionError("New MCP server connection failed")

    # Update the database record
    update_mcp_record_by_name_and_url(
        update_data=update_data,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status
    )


async def get_remote_mcp_server_list(tenant_id: str, user_id: str | None = None) -> list[dict]:
    mcp_records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    mcp_records_list = []
    can_edit_all = False
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

    for record in mcp_records:
        created_by = record.get("created_by") or record.get("user_id")
        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = PERMISSION_EDIT if can_edit_all or str(
                created_by) == str(user_id) else PERMISSION_READ

        mcp_records_list.append({
            "remote_mcp_server_name": record["mcp_name"],
            "remote_mcp_server": record["mcp_server"],
            "status": record["status"],
            "permission": permission,
        })
    return mcp_records_list


def attach_mcp_container_permissions(
    *,
    containers: list[dict],
    tenant_id: str,
    user_id: str | None = None,
) -> list[dict]:
    """
    Attach permission (EDIT/READ) to each MCP container entry.

    Rules:
    - If user's role is in CAN_EDIT_ALL_USER_ROLES => EDIT for all containers
    - Otherwise => EDIT only if the container is associated with an MCP record created by this user
    - If association cannot be determined => default to READ
    """
    if not containers:
        return []
    can_edit_all = False
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

    created_by_by_container_id: dict[str, str] = {}
    try:
        for record in get_mcp_records_by_tenant(tenant_id=tenant_id) or []:
            cid = record.get("container_id")
            if not cid:
                continue
            created_by_by_container_id[str(cid)] = str(
                record.get("created_by") or record.get("user_id") or ""
            )
    except Exception as e:
        logger.warning(f"Failed to load MCP records for permission mapping: {e}")

    enriched: list[dict] = []
    for container in containers:
        container_id = str(container.get("container_id") or "")
        created_by = created_by_by_container_id.get(container_id, "")

        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = PERMISSION_EDIT if can_edit_all or (
                created_by and str(created_by) == str(user_id)
            ) else PERMISSION_READ

        enriched.append({**container, "permission": permission})

    return enriched


async def check_mcp_health_and_update_db(mcp_url, service_name, tenant_id, user_id):
    # check the health of the MCP server
    try:
        status = await mcp_server_health(remote_mcp_server=mcp_url)
    except BaseException:
        status = False
    # update the status of the MCP server in the database
    update_mcp_status_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status)
    if not status:
        raise MCPConnectionError("MCP connection failed")


async def delete_mcp_by_container_id(tenant_id: str, user_id: str, container_id: str):
    """
    Soft delete MCP record associated with a specific container ID.

    This is used when stopping a containerized MCP so that the MCP record and
    its container are removed together.
    """
    delete_mcp_record_by_container_id(
        container_id=container_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def upload_and_start_mcp_image(
    tenant_id: str,
    user_id: str,
    file_content: bytes,
    filename: str,
    port: int,
    service_name: str | None = None,
    env_vars: str | None = None,
):
    """
    Upload MCP Docker image and start container.

    Args:
        tenant_id: Tenant ID for isolation
        user_id: User ID for isolation
        file_content: Raw file content bytes
        filename: Original filename
        port: Host port to expose the MCP server on
        service_name: Optional name for the MCP service (auto-generated if not provided)
        env_vars: Optional environment variables as JSON string

    Returns:
        Dictionary with service details including mcp_url, container_id, etc.

    Raises:
        MCPContainerError: If container operations fail
        MCPNameIllegal: If service name already exists
        ValueError: If file validation fails
    """
    # Validate file type
    if not filename.lower().endswith('.tar'):
        raise ValueError("Only .tar files are allowed")

    # Validate file size (limit to 1GB)
    file_size = len(file_content)
    if file_size > 1024 * 1024 * 1024:  # 1GB limit
        raise ValueError("File size exceeds 1GB limit")

    # Parse environment variables
    parsed_env_vars = None
    if env_vars:
        try:
            import json
            parsed_env_vars = json.loads(env_vars)
            if not isinstance(parsed_env_vars, dict):
                raise ValueError("Environment variables must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid environment variables format: {str(e)}")

    # Generate service name if not provided
    final_service_name = service_name
    if not final_service_name:
        # Remove .tar extension from filename
        final_service_name = os.path.splitext(filename)[0]

    # Check if MCP service name already exists
    if check_mcp_name_exists(mcp_name=final_service_name, tenant_id=tenant_id):
        raise MCPNameIllegal("MCP service name already exists")

    # Save file to temporary location (delete=False, manual cleanup)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
        temp_file.write(file_content)
        temp_file_path = temp_file.name

    try:
        # Initialize container manager
        container_manager = MCPContainerManager()

        # Start container from uploaded image
        # Note: uploaded image should be a complete MCP server implementation
        # that can be started directly without additional commands (uses image's CMD/ENTRYPOINT)
        container_info = await container_manager.start_mcp_container_from_tar(
            tar_file_path=temp_file_path,
            service_name=final_service_name,
            tenant_id=tenant_id,
            user_id=user_id,
            env_vars=parsed_env_vars,
            host_port=port,
            full_command=None,  # Uploaded image should contain the MCP server
        )
    finally:
        # Manual cleanup of temporary file
        try:
            os.unlink(temp_file_path)
        except Exception as e:
            logger.warning(
                f"Failed to clean up temporary file {temp_file_path}: {e}")

    # Register to remote MCP server list
    await add_remote_mcp_server_list(
        tenant_id=tenant_id,
        user_id=user_id,
        remote_mcp_server=container_info["mcp_url"],
        remote_mcp_server_name=final_service_name,
        container_id=container_info["container_id"],
    )

    return {
        "message": "MCP container started successfully from uploaded image",
        "status": "success",
        "service_name": final_service_name,
        "mcp_url": container_info["mcp_url"],
        "container_id": container_info["container_id"],
        "container_name": container_info.get("container_name"),
        "host_port": container_info.get("host_port")
    }
