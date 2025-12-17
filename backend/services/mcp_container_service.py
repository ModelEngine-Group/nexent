"""
MCP Container Service - Wrapper around SDK container management

This module provides a compatibility layer for the existing MCPContainerManager
interface while using the standardized SDK container management module.
"""

import logging
from typing import Dict, List, Optional

from consts.const import DOCKER_HOST
from consts.exceptions import MCPConnectionError, MCPContainerError
from nexent.container import (
    DockerContainerConfig,
    create_container_client_from_config,
    ContainerError,
    ContainerConnectionError,
)

logger = logging.getLogger("mcp_container_service")


class MCPContainerManager:
    """
    Manage MCP service containers using SDK container management

    This class maintains backward compatibility with the existing interface
    while delegating to the SDK's standardized container management module.
    """

    def __init__(self, docker_socket_path: str = "/var/run/docker.sock"):
        """
        Initialize container manager using SDK

        Args:
            docker_socket_path: Path to Docker socket
                For container access, mount docker socket: -v /var/run/docker.sock:/var/run/docker.sock
        """
        try:
            # Create Docker configuration
            config = DockerContainerConfig(
                docker_socket_path=docker_socket_path, docker_host=DOCKER_HOST
            )
            # Create container client from config
            self.client = create_container_client_from_config(config)
            logger.info("MCPContainerManager initialized using SDK container module")
        except ContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise MCPContainerError(f"Cannot connect to Docker: {e}")

    async def start_mcp_container(
        self,
        service_name: str,
        tenant_id: str,
        user_id: str,
        env_vars: Optional[Dict[str, str]] = None,
        host_port: Optional[int] = None,
        image: Optional[str] = None,
        full_command: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Start MCP container and return access URL

        Args:
            service_name: Name of the MCP service
            tenant_id: Tenant ID for isolation
            user_id: User ID for isolation
            env_vars: Optional environment variables

        Returns:
            Dictionary with container_id, mcp_url, host_port, and status

        Raises:
            MCPContainerError: If container startup fails
        """
        try:
            if not full_command:
                raise MCPContainerError("full_command is required to start MCP container")
            result = await self.client.start_container(
                service_name=service_name,
                tenant_id=tenant_id,
                user_id=user_id,
                full_command=full_command,
                env_vars=env_vars,
                host_port=host_port,
                image=image,
            )
            # Map SDK response to existing interface (mcp_url instead of service_url)
            return {
                "container_id": result["container_id"],
                "mcp_url": result["service_url"],  # Map service_url to mcp_url for compatibility
                "host_port": result["host_port"],
                "status": result["status"],
                "container_name": result.get("container_name"),
            }
        except ContainerError as e:
            logger.error(f"Failed to start MCP container: {e}")
            raise MCPContainerError(f"Container startup failed: {e}")
        except ContainerConnectionError as e:
            logger.error(f"MCP connection error: {e}")
            raise MCPConnectionError(f"MCP connection failed: {e}")

    async def stop_mcp_container(self, container_id: str) -> bool:
        """
        Stop and remove MCP container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was stopped successfully

        Raises:
            MCPContainerError: If container stop fails
        """
        try:
            return await self.client.stop_container(container_id)
        except ContainerError as e:
            logger.error(f"Failed to stop container: {e}")
            raise MCPContainerError(f"Failed to stop container: {e}")

    def list_mcp_containers(self, tenant_id: Optional[str] = None) -> List[Dict[str, any]]:
        """
        List all MCP containers, optionally filtered by tenant

        Args:
            tenant_id: Optional tenant ID to filter containers

        Returns:
            List of container information dictionaries
        """
        try:
            containers = self.client.list_containers(tenant_id=tenant_id)
            # Map SDK response to existing interface (mcp_url instead of service_url)
            result = []
            for container in containers:
                result.append(
                    {
                        "container_id": container["container_id"],
                        "name": container["name"],
                        "status": container["status"],
                        "mcp_url": container.get(
                            "service_url"
                        ),  # Map service_url to mcp_url for compatibility
                        "host_port": container.get("host_port"),
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Failed to list MCP containers: {e}")
            return []

    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """
        Get container logs

        Args:
            container_id: Container ID or name
            tail: Number of log lines to retrieve

        Returns:
            Container logs as string
        """
        try:
            return self.client.get_container_logs(container_id, tail=tail)
        except Exception as e:
            logger.error(f"Failed to get container logs: {e}")
            return f"Error retrieving logs: {e}"
