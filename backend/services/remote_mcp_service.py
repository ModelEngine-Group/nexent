import logging
import os
import tempfile
import asyncio
import socket
import random
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, SSETransport
from consts.const import CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT, PERMISSION_READ, NEXENT_MCP_DOCKER_IMAGE
from consts.exceptions import (
    MCPConnectionError,
    MCPNameIllegal,
    MCPContainerError,
    McpNotFoundError,
    McpValidationError,
    McpNameConflictError,
    McpPortConflictError,
)
from consts.model import MCPConfigRequest
from database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_container_id,
    get_mcp_records_by_tenant,
    check_mcp_name_exists,
    check_enabled_mcp_name_exists,
    update_mcp_status_by_name_and_url,
    update_mcp_record_by_name_and_url,
    update_mcp_record_manage_fields_by_id,
    update_mcp_record_enabled_by_id,
    update_mcp_record_container_fields_by_id,
    update_mcp_record_status_by_id,
    delete_mcp_record_by_id,
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_record_by_id_and_tenant,
    get_mcp_custom_headers_by_name_and_url,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from services.mcp_container_service import MCPContainerManager
from utils.http_client_utils import create_httpx_client

logger = logging.getLogger("remote_mcp_service")


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

async def mcp_server_health(remote_mcp_server: str, authorization_token: str | None = None, custom_headers: dict | None = None) -> bool:
    """Check if an MCP server is healthy and reachable."""
    try:
        url_stripped = remote_mcp_server.strip()
        headers = {}
        if authorization_token:
            headers["Authorization"] = authorization_token
        if custom_headers:
            headers.update(custom_headers)

        if url_stripped.endswith("/sse"):
            transport = SSETransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client
            )
        elif url_stripped.endswith("/mcp"):
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client
            )
        else:
            # Default to StreamableHttpTransport for unrecognized formats
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client
            )

        client = Client(transport=transport)
        async with client:
            connected = client.is_connected()
            return connected
    except BaseException as e:
        logger.error(f"Remote MCP server health check failed: {e}", exc_info=True)
        error_message = str(e).strip() or repr(e)
        if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in error_message.lower():
            raise MCPConnectionError("MCP_HEALTH_TIMEOUT")
        raise MCPConnectionError(error_message)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _is_container_record(record: dict | None) -> bool:
    """Check if the MCP record is container-based.

    A record is considered container-based if it has:
    - container_id (Docker container ID)
    - config_json (container configuration)
    """
    if not record:
        return False
    return record.get("container_id") is not None or record.get("config_json") is not None


# ---------------------------------------------------------------------------
# Port Management Functions
# ---------------------------------------------------------------------------

def check_container_port_conflict_records(port: int) -> bool:
    """Check if there are enabled MCP records that already use the given container port."""
    from database.remote_mcp_db import get_mcp_records_by_container_port
    return not get_mcp_records_by_container_port(container_port=port)


def check_runtime_host_port_available(port: int) -> bool:
    """Return True when the host port is not occupied by a listener."""
    probe_targets = [(socket.AF_INET, "127.0.0.1")]
    if socket.has_ipv6:
        probe_targets.append((socket.AF_INET6, "::1"))

    try:
        host_infos = socket.getaddrinfo("host.docker.internal", port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in host_infos:
            probe_targets.append((family, sockaddr[0]))
    except OSError:
        pass

    for family, host in probe_targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe_socket:
                probe_socket.settimeout(0.2)
                connect_result = probe_socket.connect_ex((host, port) if family == socket.AF_INET else (host, port, 0, 0))
                if connect_result == 0:
                    logger.info(f"Host port {port} is already in use on {host}")
                    return False
        except OSError:
            continue

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bind_probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            bind_probe.bind(("0.0.0.0", port))
            bind_probe.listen(1)
        return True
    except OSError as exc:
        logger.info(f"Host port {port} is already in use: {exc}")
        return False


def check_container_port_conflict(*, port: int) -> bool:
    """Check if a port is available for MCP container."""
    no_conflict_records = check_container_port_conflict_records(port=port)
    runtime_available = check_runtime_host_port_available(port)
    return no_conflict_records and runtime_available


def suggest_container_port() -> int:
    """Suggest an available port for MCP container."""
    min_port = 2000
    max_port = 50000
    count = 0
    while count < 1000:
        port = random.randint(min_port, max_port)
        if check_container_port_conflict(port=port):
            return port
        count += 1
    raise McpPortConflictError("No available port found")

# ---------------------------------------------------------------------------
# Add Functions
# ---------------------------------------------------------------------------

async def add_remote_mcp_server_list(
    tenant_id: str,
    user_id: str,
    remote_mcp_server: str,
    remote_mcp_server_name: str,
    container_id: str | None = None,
    authorization_token: str | None = None,
    custom_headers: dict | None = None,
    source: str | None = "local",
    container_port: int | None = None,
):
    """Add a remote MCP server to the list.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        remote_mcp_server: MCP server URL
        remote_mcp_server_name: MCP service name
        container_id: Docker container ID (optional)
        authorization_token: Authorization token (optional)
        custom_headers: Custom HTTP headers (optional)

    Raises:
        MCPNameIllegal: If MCP name already exists
        MCPConnectionError: If MCP server is not reachable
    """
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name, tenant_id=tenant_id):
        logger.error(f"MCP name already exists: {remote_mcp_server_name}")
        raise MCPNameIllegal("MCP name already exists")

    if not await mcp_server_health(remote_mcp_server=remote_mcp_server, authorization_token=authorization_token, custom_headers=custom_headers):
        raise MCPConnectionError("MCP connection failed")

    insert_mcp_data = {
        "mcp_name": remote_mcp_server_name,
        "mcp_server": remote_mcp_server,
        "status": True,
        "container_id": container_id,
        "authorization_token": authorization_token,
        "custom_headers": custom_headers,
        "source": source,
        "container_port": container_port,
    }
    create_mcp_record(mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)


async def add_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str | None,
    source: str,
    server_url: str,
    tags: list | None,
    authorization_token: str | None,
    custom_headers: dict | None,
    container_config: dict | None,
    registry_json: dict | None,
    enabled: bool = False,
    container_id: str | None = None,
    container_port: int | None = None,
) -> None:
    """Add an MCP service record.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        name: MCP service name
        description: MCP service description
        source: Source type (local/mcp_registry/community)
        server_url: MCP server URL
        tags: MCP tags
        authorization_token: Authorization token for MCP server
        custom_headers: Custom HTTP headers
        container_config: Container configuration
        registry_json: Registry metadata JSON
        enabled: Whether the MCP is enabled
        container_id: Docker container ID
        container_port: Container port
    """
    status: bool | None = None
    normalized_container_id = container_id if isinstance(container_id, str) and container_id else None
    is_container = container_id is not None or container_config is not None
    config_json = container_config if is_container and isinstance(container_config, dict) else None

    if enabled:
        if check_mcp_name_exists(mcp_name=name, tenant_id=tenant_id):
            logger.error(f"MCP name already exists: {name}")
            raise MCPNameIllegal("MCP name already exists")

        if not await mcp_server_health(remote_mcp_server=server_url, authorization_token=authorization_token, custom_headers=custom_headers):
            raise MCPConnectionError("MCP connection failed")

        status = True

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": normalized_container_id,
            "container_port": container_port,
            "authorization_token": authorization_token,
            "custom_headers": custom_headers,
            "source": source,
            "registry_json": registry_json,
            "enabled": enabled,
            "tags": tags,
            "description": description,
            "config_json": config_json,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def add_container_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str | None,
    source: str,
    tags: list | None,
    authorization_token: str | None,
    registry_json: dict | None,
    port: int,
    mcp_config: MCPConfigRequest,
) -> dict:
    """Add a container-based MCP service.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        name: MCP service name
        description: MCP service description
        source: Source type
        tags: MCP tags
        authorization_token: Authorization token
        registry_json: Registry metadata JSON
        port: Host port for the container
        mcp_config: MCP server configuration

    Returns:
        Container information dictionary
    """
    service_name = name
    if check_mcp_name_exists(mcp_name=service_name, tenant_id=tenant_id):
        raise McpNameConflictError("Enabled MCP name already exists")

    if not check_container_port_conflict(port=port):
        raise McpPortConflictError(f"Port {port} is already in use")

    servers = mcp_config.mcpServers
    if len(servers) != 1:
        raise McpValidationError("Exactly one mcpServers entry is required")

    _, config = next(iter(servers.items()))
    command = config.command
    if not command:
        raise McpValidationError("command is required")
    if command.strip().lower() == "docker":
        raise McpValidationError("Docker command is not supported")

    env_vars = dict(config.env or {})
    auth_token = authorization_token
    if auth_token:
        env_vars["authorization_token"] = auth_token

    full_command = [
        "python",
        "-m",
        "mcp_proxy",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--transport",
        "streamablehttp",
        "--",
        command,
        *(config.args or []),
    ]

    container_manager = MCPContainerManager()
    try:
        container_info = await container_manager.start_mcp_container(
            service_name=service_name,
            tenant_id=tenant_id,
            user_id=user_id,
            env_vars=env_vars,
            host_port=port,
            image=NEXENT_MCP_DOCKER_IMAGE,
            full_command=full_command,
        )
        logger.info(f"Started MCP container with info: {container_info}")

        container_config = mcp_config.model_dump(exclude_none=True)

        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=service_name,
            description=description,
            source=source,
            server_url=container_info.get("mcp_url"),
            tags=tags,
            authorization_token=auth_token,
            container_config=container_config,
            registry_json=registry_json,
            enabled=True,
            container_id=container_info.get("container_id"),
            container_port=container_info.get("host_port"),
        )
    except Exception as exc:
        logger.warning(f"Failed to start container MCP service: {exc}")
        raise

    return {
        "service_name": service_name,
        "mcp_url": container_info.get("mcp_url"),
        "container_id": container_info.get("container_id"),
        "container_name": container_info.get("container_name"),
        "host_port": container_info.get("host_port"),
    }


# ---------------------------------------------------------------------------
# Update Functions
# ---------------------------------------------------------------------------

async def update_remote_mcp_server_list(update_data, tenant_id: str, user_id: str) -> None:
    """Update an existing remote MCP server record.

    Args:
        update_data: MCPUpdateRequest containing current and new values
        tenant_id: Tenant ID
        user_id: User ID

    Raises:
        MCPNameIllegal: If the new MCP name already exists
        MCPConnectionError: If the new MCP server URL is not accessible
    """
    if not check_mcp_name_exists(mcp_name=update_data.current_service_name, tenant_id=tenant_id):
        raise MCPNameIllegal("MCP name does not exist")

    if update_data.new_service_name != update_data.current_service_name:
        if check_mcp_name_exists(mcp_name=update_data.new_service_name, tenant_id=tenant_id):
            raise MCPNameIllegal("New MCP name already exists")

    authorization_token = update_data.new_authorization_token
    custom_headers = getattr(update_data, 'custom_headers', None)

    try:
        status = await mcp_server_health(
            remote_mcp_server=update_data.new_mcp_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except BaseException:
        status = False

    if not status:
        raise MCPConnectionError("New MCP server connection failed")

    update_mcp_record_by_name_and_url(
        update_data=update_data,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status
    )


def update_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    new_name: str,
    description: str | None,
    server_url: str,
    authorization_token: str | None,
    custom_headers: dict | None,
    tags: list | None,
) -> None:
    """Update an MCP service record by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID
        new_name: New MCP service name
        description: MCP service description
        server_url: New MCP server URL
        authorization_token: Authorization token
        custom_headers: Custom HTTP headers
        tags: MCP tags

    Raises:
        McpNotFoundError: If MCP record is not found
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    is_container = _is_container_record(current_record)
    config_json = None
    if is_container:
        config_json = current_record.get("config_json") if isinstance(current_record.get("config_json"), dict) else None

    update_mcp_record_manage_fields_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=new_name,
        description=description,
        server_url=server_url,
        source=(current_record.get("source") or "local"),
        authorization_token=authorization_token,
        custom_headers=custom_headers,
        config_json=config_json,
        tags=tags,
    )


async def update_mcp_service_enabled(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    enabled: bool,
) -> None:
    """Enable or disable an MCP service.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID
        enabled: True to enable, False to disable

    Raises:
        McpNotFoundError: If MCP record is not found
        McpNameConflictError: If an enabled service with the same name exists
        McpPortConflictError: If the container port is not available
        MCPConnectionError: If MCP connection fails
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    if enabled:
        current_name = current_record.get("mcp_name")
        if current_name:
            records = get_mcp_records_by_tenant(tenant_id=tenant_id)
            for record in records:
                if int(record.get("mcp_id") or 0) == mcp_id:
                    continue
                record_name = record.get("mcp_name")
                is_enabled = bool(record.get("enabled"))
                if is_enabled and record_name == current_name:
                    raise McpNameConflictError("An enabled service already uses this name")

    authorization_token = current_record.get("authorization_token")
    custom_headers = current_record.get("custom_headers") if isinstance(current_record.get("custom_headers"), dict) else None

    if _is_container_record(current_record):
        if enabled:
            port = current_record.get("container_port")
            if port is None:
                raise McpValidationError("Container port is missing, cannot rebuild container")
            if not check_runtime_host_port_available(port):
                raise McpPortConflictError(f"Port {port} is already in use")

            config_json = current_record.get("config_json")
            if not isinstance(config_json, dict):
                raise McpValidationError("Container configuration is missing, cannot rebuild container")

            try:
                mcp_config = MCPConfigRequest(**config_json)
            except Exception as exc:
                raise McpValidationError(f"Invalid container configuration: {exc}")

            servers = mcp_config.mcpServers
            if not servers or len(servers) != 1:
                raise McpValidationError("Exactly one mcpServers entry is required")
            _, config = next(iter(servers.items()))
            command = config.command
            if not command:
                raise McpValidationError("command is required")

            env_vars = dict(config.env or {})
            if authorization_token:
                env_vars["authorization_token"] = authorization_token

            full_command = [
                "python",
                "-m",
                "mcp_proxy",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--transport",
                "streamablehttp",
                "--",
                command,
                *(config.args or []),
            ]

            container_manager = MCPContainerManager()
            container_info = await container_manager.start_mcp_container(
                service_name=current_record.get("mcp_name"),
                tenant_id=tenant_id,
                user_id=user_id,
                env_vars=env_vars,
                host_port=port,
                image=NEXENT_MCP_DOCKER_IMAGE,
                full_command=full_command,
            )

            next_server_url = container_info.get("mcp_url")
            next_container_id = container_info.get("container_id")
            next_container_port = container_info.get("host_port") or port

            health_ok = False
            MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS = 10
            MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS = 0.5
            for attempt in range(MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS):
                try:
                    health_ok = await mcp_server_health(
                        remote_mcp_server=next_server_url,
                        authorization_token=authorization_token,
                        custom_headers=custom_headers,
                    )
                except MCPConnectionError:
                    health_ok = False
                if health_ok:
                    break
                if attempt < MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS - 1:
                    await asyncio.sleep(MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS)

            if not health_ok:
                if next_container_id:
                    try:
                        await MCPContainerManager().stop_mcp_container(next_container_id)
                    except Exception as exc:
                        logger.warning(f"Failed to stop unhealthy container {next_container_id}: {exc}")
                update_mcp_record_container_fields_by_id(
                    mcp_id=mcp_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    container_id=None,
                    container_port=port,
                    mcp_server=next_server_url,
                    status=False,
                )
                raise MCPConnectionError("MCP connection failed")

            update_mcp_record_container_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=next_container_id,
                container_port=next_container_port,
                mcp_server=next_server_url,
                status=True,
            )
        else:
            current_container_id = current_record.get("container_id")
            if current_container_id and current_record.get("config_json"):
                try:
                    manager = MCPContainerManager()
                    await manager.stop_mcp_container(current_container_id)
                except Exception as exc:
                    logger.warning(f"Failed to stop container {current_container_id}: {exc}")
            update_mcp_record_container_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=None,
                container_port=current_record.get("container_port"),
                mcp_server=current_record.get("mcp_server"),
                status=None,
            )
    elif enabled:
        server_url = current_record.get("mcp_server")
        health_ok = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=bool(health_ok),
        )
        if not health_ok:
            raise MCPConnectionError("MCP connection failed")

    update_mcp_record_enabled_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Delete Functions
# ---------------------------------------------------------------------------

async def delete_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> None:
    """Delete an MCP service by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID

    Raises:
        McpNotFoundError: If MCP record is not found
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")
    container_id = current_record.get("container_id")
    if container_id:
        try:
            manager = MCPContainerManager()
            await manager.stop_mcp_container(container_id=container_id)
        except Exception as exc:
            logger.warning(f"Failed to stop container: {exc}, but continue to delete MCP record")

    delete_mcp_record_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def delete_mcp_by_container_id(tenant_id: str, user_id: str, container_id: str) -> None:
    """Soft delete MCP record associated with a specific container ID."""
    delete_mcp_record_by_container_id(
        container_id=container_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# List Functions
# ---------------------------------------------------------------------------

async def get_remote_mcp_server_list(
    tenant_id: str,
    user_id: str | None = None,
    is_need_auth: bool = True,
) -> list[dict]:
    """Get list of remote MCP servers with full details.

    Args:
        tenant_id: Tenant ID
        user_id: User ID for permission checking
        is_need_auth: Whether to include authorization tokens

    Returns:
        List of MCP server records with all fields including container_id, description,
        enabled, source, update_time, tags, container_port, registry_json, config_json,
        container_status, and authorization_token
    """
    mcp_records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    mcp_records_list = []
    can_edit_all = False
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

    container_status_map = {}
    try:
        manager = MCPContainerManager()
        for container in manager.list_mcp_containers(tenant_id=tenant_id):
            container_id = container.get("container_id")
            status = container.get("status")
            if not container_id:
                continue
            if status == "running":
                container_status_map[container_id] = "running"
            elif status:
                container_status_map[container_id] = "stopped"
    except Exception as exc:
        logger.warning(f"Failed to load container runtime status: {exc}")

    for record in mcp_records:
        created_by = record.get("created_by") or record.get("user_id")
        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = PERMISSION_EDIT if can_edit_all or str(created_by) == str(user_id) else PERMISSION_READ

        config_json = record.get("config_json")
        container_id = record.get("container_id")

        is_container = container_id is not None or config_json is not None

        container_status = None
        if is_container:
            if container_id:
                container_status = container_status_map.get(container_id, "stopped")
            else:
                container_status = "stopped"

        record_dict = {
            "remote_mcp_server_name": record["mcp_name"],
            "remote_mcp_server": record["mcp_server"],
            "status": record.get("status"),
            "permission": permission,
            "mcp_id": record.get("mcp_id"),
            "container_id": container_id,
            "description": record.get("description"),
            "enabled": record.get("enabled"),
            "source": record.get("source"),
            "update_time": record.get("update_time"),
            "tags": record.get("tags") or [],
            "container_port": record.get("container_port"),
            "registry_json": record.get("registry_json"),
            "config_json": record.get("config_json"),
            "container_status": container_status,
        }
        if is_need_auth:
            record_dict["authorization_token"] = record.get("authorization_token")
            record_dict["custom_headers"] = record.get("custom_headers")
        mcp_records_list.append(record_dict)
    return mcp_records_list


def attach_mcp_container_permissions(
    *,
    containers: list[dict],
    tenant_id: str,
    user_id: str | None = None,
) -> list[dict]:
    """Attach permission (EDIT/READ) to each MCP container entry.

    Args:
        containers: List of container records
        tenant_id: Tenant ID
        user_id: User ID for permission checking

    Returns:
        List of containers with permission field added
    """
    if not containers:
        return []
    can_edit_all = False
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

    created_by_by_container_id = {}
    try:
        for record in get_mcp_records_by_tenant(tenant_id=tenant_id) or []:
            cid = record.get("container_id")
            if not cid:
                continue
            created_by_by_container_id[str(cid)] = str(record.get("created_by") or record.get("user_id") or "")
    except Exception as e:
        logger.warning(f"Failed to load MCP records for permission mapping: {e}")

    enriched = []
    for container in containers:
        container_id = str(container.get("container_id") or "")
        created_by = created_by_by_container_id.get(container_id, "")

        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = PERMISSION_EDIT if can_edit_all or (created_by and str(created_by) == str(user_id)) else PERMISSION_READ

        enriched.append({**container, "permission": permission})

    return enriched


async def get_mcp_record_by_id(mcp_id: int, tenant_id: str) -> dict | None:
    """Get MCP record by ID.

    Args:
        mcp_id: MCP record ID
        tenant_id: Tenant ID

    Returns:
        Dictionary containing mcp_name, mcp_server, authorization_token, and custom_headers, or None if not found
    """
    mcp_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not mcp_record:
        return None

    return {
        "mcp_name": mcp_record.get("mcp_name"),
        "mcp_server": mcp_record.get("mcp_server"),
        "authorization_token": mcp_record.get("authorization_token"),
        "custom_headers": mcp_record.get("custom_headers"),
    }


# ---------------------------------------------------------------------------
# Health Check Functions
# ---------------------------------------------------------------------------

async def check_mcp_health_and_update_db(mcp_url, service_name, tenant_id, user_id) -> None:
    """Check MCP health and update database status.

    Args:
        mcp_url: MCP server URL
        service_name: MCP service name
        tenant_id: Tenant ID
        user_id: User ID

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    authorization_token = get_mcp_authorization_token_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id
    )
    custom_headers = get_mcp_custom_headers_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id
    )

    try:
        status = await mcp_server_health(
            remote_mcp_server=mcp_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except BaseException:
        status = False

    update_mcp_status_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status
    )
    if not status:
        raise MCPConnectionError("MCP connection failed")


async def check_mcp_service_health(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> str:
    """Check MCP service health by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID

    Returns:
        "healthy" if MCP is reachable

    Raises:
        McpNotFoundError: If MCP record is not found
        McpValidationError: If MCP server URL is empty
        MCPConnectionError: If MCP connection fails
    """
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    server_url = record.get("mcp_server")
    if not server_url:
        raise McpValidationError("MCP server URL is empty")

    authorization_token = record.get("authorization_token")
    custom_headers = record.get("custom_headers")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except MCPConnectionError:
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=False,
        )
        raise
    except Exception as exc:
        logger.error(f"MCP health check failed: {exc}")
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=False,
        )
        raise MCPConnectionError(str(exc) or "MCP connection failed")

    update_mcp_record_status_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
    )

    if not status:
        raise MCPConnectionError("MCP connection failed")

    return "healthy"


# ---------------------------------------------------------------------------
# Tool Functions
# ---------------------------------------------------------------------------

async def list_mcp_service_tools_by_id(*, tenant_id: str, mcp_id: int) -> list[dict]:
    """Get tools from an MCP service by ID.

    Args:
        tenant_id: Tenant ID
        mcp_id: MCP record ID

    Returns:
        List of tool dictionaries

    Raises:
        McpNotFoundError: If MCP record is not found
        McpValidationError: If MCP record is missing connection fields
        MCPConnectionError: If MCP connection fails
    """
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    service_name = record.get("mcp_name")
    server_url = record.get("mcp_server")
    if not service_name or not server_url:
        raise McpValidationError("MCP record is missing runtime connection fields")

    authorization_token = record.get("authorization_token")
    custom_headers = record.get("custom_headers")

    from services.tool_configuration_service import get_tool_from_remote_mcp_server
    tools_info = await get_tool_from_remote_mcp_server(
        mcp_server_name=service_name,
        remote_mcp_server=server_url,
        tenant_id=tenant_id,
        authorization_token=authorization_token,
        custom_headers=custom_headers,
    )
    return [tool.__dict__ for tool in tools_info]


# ---------------------------------------------------------------------------
# Image Upload Functions
# ---------------------------------------------------------------------------

async def upload_and_start_mcp_image(
    tenant_id: str,
    user_id: str,
    file_content: bytes,
    filename: str,
    port: int,
    service_name: str | None = None,
    env_vars: str | None = None,
) -> dict:
    """Upload MCP Docker image and start container.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        file_content: Raw file content bytes
        filename: Original filename
        port: Host port to expose the MCP server on
        service_name: Optional name for the MCP service
        env_vars: Optional environment variables as JSON string

    Returns:
        Dictionary with service details

    Raises:
        MCPContainerError: If container operations fail
        MCPNameIllegal: If service name already exists
        ValueError: If file validation fails
    """
    if not filename.lower().endswith('.tar'):
        raise ValueError("Only .tar files are allowed")

    file_size = len(file_content)
    if file_size > 1024 * 1024 * 1024:
        raise ValueError("File size exceeds 1GB limit")

    parsed_env_vars = None
    if env_vars:
        import json
        try:
            parsed_env_vars = json.loads(env_vars)
            if not isinstance(parsed_env_vars, dict):
                raise ValueError("Environment variables must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid environment variables format: {str(e)}")

    final_service_name = service_name
    if not final_service_name:
        final_service_name = os.path.splitext(filename)[0]

    if check_mcp_name_exists(mcp_name=final_service_name, tenant_id=tenant_id):
        raise MCPNameIllegal("MCP service name already exists")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
        temp_file.write(file_content)
        temp_file_path = temp_file.name

    try:
        container_manager = MCPContainerManager()
        container_info = await container_manager.start_mcp_container_from_tar(
            tar_file_path=temp_file_path,
            service_name=final_service_name,
            tenant_id=tenant_id,
            user_id=user_id,
            env_vars=parsed_env_vars,
            host_port=port,
            full_command=None,
        )
    finally:
        try:
            os.unlink(temp_file_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary file {temp_file_path}: {e}")

    authorization_token = None
    if parsed_env_vars:
        authorization_token = parsed_env_vars.get("authorization_token")

    await add_remote_mcp_server_list(
        tenant_id=tenant_id,
        user_id=user_id,
        remote_mcp_server=container_info["mcp_url"],
        remote_mcp_server_name=final_service_name,
        container_id=container_info["container_id"],
        authorization_token=authorization_token,
        container_port=port
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
