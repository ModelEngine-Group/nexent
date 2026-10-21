# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import os
import random
import socket
import tempfile
from typing import Awaitable, Callable

from consts.const import NEXENT_MCP_DOCKER_IMAGE
from contracts.exceptions import MCPConnectionError, McpNameConflictError, MCPNameIllegal, McpPortConflictError, McpValidationError
from contracts.models import MCPConfigRequest
from management.db.mcp.remote import check_mcp_name_exists
from management.services.mcp.common import (
    logger,
)
from management.services.mcp.containers import MCPContainerManager


def _is_container_record(record: dict | None) -> bool:
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


def check_container_port_conflict_records(port: int) -> bool:
    """Check if there are enabled MCP records that already use the given container port."""
    from management.db.mcp.remote import get_mcp_records_by_container_port

    return not get_mcp_records_by_container_port(container_port=port)


def check_runtime_host_port_available(port: int) -> bool:
    """Return True when the host port is not occupied by a listener."""
    probe_targets = [(socket.AF_INET, "127.0.0.1")]
    if socket.has_ipv6:
        probe_targets.append((socket.AF_INET6, "::1"))

    try:
        host_infos = socket.getaddrinfo(
            "host.docker.internal", port, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        for family, _, _, _, sockaddr in host_infos:
            probe_targets.append((family, sockaddr[0]))
    except OSError:
        pass

    for family, host in probe_targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe_socket:
                probe_socket.settimeout(0.2)
                connect_result = probe_socket.connect_ex(
                    (host, port) if family == socket.AF_INET else (host, port, 0, 0)
                )
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
            bind_probe.bind(("127.0.0.1", port))
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
    market_id: int | None,
    port: int,
    mcp_config: MCPConfigRequest,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
    wait_for_ready: bool = True,
    skip_health_check: bool = False,
    on_container_started: Callable[[dict], Awaitable[None]] | None = None,
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
        community_id: Linked community record ID
        port: Host port for the container
        mcp_config: MCP server configuration
        group_ids: Comma-separated group IDs that can access this MCP
        ingroup_permission: Permission level: EDIT, READ_ONLY, PRIVATE

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
            wait_for_ready=wait_for_ready,
        )
        logger.info(f"Started MCP container with info: {container_info}")

        if on_container_started:
            await on_container_started(container_info)

        container_config = mcp_config.model_dump(exclude_none=True)

        # Streaming callers need the container ID before it is healthy so the
        # UI can display startup logs. Keep the original readiness guarantee
        # by waiting here, after that ID has been emitted.
        if not wait_for_ready and not skip_health_check:
            readiness_error: MCPConnectionError | None = None
            for _ in range(30):
                try:
                    await mcp_server_health(
                        remote_mcp_server=container_info.get("mcp_url"),
                        authorization_token=auth_token,
                    )
                    readiness_error = None
                    break
                except MCPConnectionError as exc:
                    readiness_error = exc
                    await asyncio.sleep(5)
            if readiness_error:
                raise readiness_error

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
            market_id=market_id,
            enabled=True,
            container_id=container_info.get("container_id"),
            container_port=container_info.get("host_port"),
            group_ids=group_ids,
            ingroup_permission=ingroup_permission,
            skip_health_check=skip_health_check,
        )
    except Exception as exc:
        logger.warning(f"Failed to start container MCP service: {exc}")
        # Clean up orphan container if it was started
        try:
            await container_manager.stop_mcp_container(
                container_info.get("container_id")
            )
        except Exception:
            pass
        raise

    return {
        "service_name": service_name,
        "mcp_url": container_info.get("mcp_url"),
        "container_id": container_info.get("container_id"),
        "container_name": container_info.get("container_name"),
        "host_port": container_info.get("host_port"),
    }


async def upload_and_start_mcp_image(
    tenant_id: str,
    user_id: str,
    file_content: bytes,
    filename: str,
    port: int,
    service_name: str | None = None,
    env_vars: str | None = None,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
    wait_for_ready: bool = True,
    on_container_started: Callable[[dict], Awaitable[None]] | None = None,
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
    if not filename.lower().endswith(".tar"):
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

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as temp_file:
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
            wait_for_ready=wait_for_ready,
        )
    finally:
        try:
            os.unlink(temp_file_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary file {temp_file_path}: {e}")

    authorization_token = None
    if parsed_env_vars:
        authorization_token = parsed_env_vars.get("authorization_token")

    if on_container_started:
        await on_container_started(container_info)

    if not wait_for_ready:
        readiness_error: MCPConnectionError | None = None
        for _ in range(30):
            try:
                await mcp_server_health(
                    remote_mcp_server=container_info["mcp_url"],
                    authorization_token=authorization_token,
                )
                readiness_error = None
                break
            except MCPConnectionError as exc:
                readiness_error = exc
                await asyncio.sleep(5)
        if readiness_error:
            raise readiness_error

    try:
        await add_remote_mcp_server_list(
            tenant_id=tenant_id,
            user_id=user_id,
            remote_mcp_server=container_info["mcp_url"],
            remote_mcp_server_name=final_service_name,
            container_id=container_info["container_id"],
            authorization_token=authorization_token,
            container_port=port,
            group_ids=group_ids,
            ingroup_permission=ingroup_permission,
            shared_fields=shared_fields,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to register uploaded-image MCP service: {exc}; "
            "cleaning up the started container so it does not become an orphan "
            "that keeps occupying the host port"
        )
        try:
            await container_manager.stop_mcp_container(container_info["container_id"])
        except Exception as cleanup_exc:
            logger.warning(
                f"Failed to clean up container {container_info['container_id']}: {cleanup_exc}"
            )
        raise

    return {
        "message": "MCP container started successfully from uploaded image",
        "status": "success",
        "service_name": final_service_name,
        "mcp_url": container_info["mcp_url"],
        "container_id": container_info["container_id"],
        "container_name": container_info.get("container_name"),
        "host_port": container_info.get("host_port"),
    }


from management.services.mcp.health import (
    mcp_server_health,
)
from management.services.mcp.registration import (
    add_mcp_service,
    add_remote_mcp_server_list,
)
