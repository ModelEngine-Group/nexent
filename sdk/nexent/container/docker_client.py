"""
Docker container client implementation
"""

import asyncio
import logging
import socket
from pathlib import Path
from typing import Dict, List, Optional, Any

import docker
from docker.errors import APIError, DockerException, NotFound
from fastmcp import Client

from .container_client_base import ContainerClient, ContainerConfig
from .docker_config import DockerContainerConfig

logger = logging.getLogger("nexent.container.docker")


class ContainerError(Exception):
    """Raised when container operation fails"""

    pass


class ContainerConnectionError(Exception):
    """Raised when container connection fails"""

    pass


class DockerContainerClient(ContainerClient):
    """Docker container client implementation"""

    DEFAULT_NETWORK_NAME = "nexent_nexent"

    def __init__(self, config: DockerContainerConfig):
        """
        Initialize Docker client

        Args:
            config: Docker container configuration

        Raises:
            ContainerError: If Docker connection fails
        """
        config.validate()
        base_url = config.base_url

        try:
            self.client = docker.DockerClient(base_url=base_url)
            # Test connection
            self.client.ping()
            logger.info(
                f"Docker client initialized successfully with base_url={base_url}")
        except DockerException as e:
            logger.error(f"Failed to connect to Docker socket: {e}")
            raise ContainerError(f"Cannot connect to Docker: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise ContainerError(f"Cannot connect to Docker: {e}")

    @staticmethod
    def _is_running_in_docker() -> bool:
        """
        Check if the current process is running inside a Docker container

        Returns:
            True if running in Docker container, False otherwise
        """
        # Check for /.dockerenv file (most reliable indicator)
        if Path("/.dockerenv").exists():
            return True

        # Check /proc/self/cgroup for Docker (Linux only)
        try:
            cgroup_path = Path("/proc/self/cgroup")
            if cgroup_path.exists():
                content = cgroup_path.read_text()
                if "docker" in content or "containerd" in content:
                    return True
        except Exception:
            pass

        return False

    @staticmethod
    def _get_service_host(service_name: str) -> str:
        """
        Get the appropriate host for service URLs based on running environment

        Returns:
            Service name if running in Docker container (container-to-container DNS),
            'localhost' if running in local development environment
        """
        if DockerContainerClient._is_running_in_docker():
            return service_name
        return "localhost"

    def _ensure_network(self, network_name: str) -> None:
        """Ensure the Docker network exists (create it if missing)."""
        try:
            self.client.networks.get(network_name)
        except NotFound:
            try:
                self.client.networks.create(network_name)
                logger.info(f"Created Docker network: {network_name}")
            except APIError as e:
                # Handle race where another process created it.
                try:
                    self.client.networks.get(network_name)
                except Exception as inner:
                    raise ContainerError(
                        f"Failed to create or get Docker network '{network_name}': {e}"
                    ) from inner
        except APIError as e:
            raise ContainerError(
                f"Failed to get Docker network '{network_name}': {e}")

    @staticmethod
    def _get_container_service_port(container: Any) -> Optional[str]:
        """
        Get the service port for a container.

        - In Docker-to-Docker mode (no published ports required), prefer PORT from env.
        - Otherwise fall back to published host port if available.
        """
        try:
            # Prefer PORT from environment if present.
            env_list = container.attrs.get("Config", {}).get("Env", []) or []
            for item in env_list:
                if isinstance(item, str) and item.startswith("PORT="):
                    return item.split("=", 1)[1]
        except Exception:
            pass

        # Fall back to published host port mapping
        try:
            ports = container.attrs.get(
                "NetworkSettings", {}).get("Ports", {}) or {}
            for _, host_mappings in ports.items():
                if host_mappings and len(host_mappings) > 0:
                    host_port = host_mappings[0].get("HostPort")
                    if host_port:
                        return str(host_port)
        except Exception:
            pass

        return None

    def find_free_port(self, start_port: int = 5020, max_attempts: int = 100) -> int:
        """
        Find an available port on host

        Args:
            start_port: Starting port number to check
            max_attempts: Maximum number of ports to check

        Returns:
            Available port number

        Raises:
            ContainerError: If no available port found
        """
        for i in range(max_attempts):
            port = start_port + i
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(("localhost", port))
                if result != 0:
                    logger.debug(f"Found free port: {port}")
                    return port
        raise ContainerError(
            f"No available port found in range {start_port}-{start_port + max_attempts}"
        )

    def _generate_container_name(self, service_name: str, tenant_id: str, user_id: str) -> str:
        """Generate unique container name with service, tenant, and user segments."""
        # Sanitize service name for container name (only alphanumeric and hyphens)
        safe_name = "".join(c if c.isalnum() or c ==
                            "-" else "-" for c in service_name)
        tenant_part = (tenant_id or "")[:8]
        user_part = (user_id or "")[:8]
        return f"mcp-{safe_name}-{tenant_part}-{user_part}"

    async def start_container(
        self,
        service_name: str,
        tenant_id: str,
        user_id: str,
        full_command: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        host_port: Optional[int] = None,
        image: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start container and return access URL

        Args:
            service_name: Name of the service
            tenant_id: Tenant ID for isolation
            user_id: User ID for isolation
            full_command: Optional complete command list to run inside container (must start an HTTP endpoint).
                         If None, uses the image's default CMD/ENTRYPOINT.
            env_vars: Optional environment variables

        Returns:
            Dictionary with container_id, service_url, host_port, and status

        Raises:
            ContainerError: If container startup fails
        """
        container_name = self._generate_container_name(
            service_name, tenant_id, user_id)
        self._ensure_network(self.DEFAULT_NETWORK_NAME)

        # Check if container already exists
        try:
            existing = self.client.containers.get(container_name)
            if existing.status == "running":
                if DockerContainerClient._is_running_in_docker():
                    service_port = self._get_container_service_port(existing) or (
                        str(host_port) if host_port is not None else None
                    )
                else:
                    # Local mode: prefer published host port mapping over internal PORT env.
                    service_port = None
                    ports = existing.attrs.get(
                        "NetworkSettings", {}).get("Ports", {}) or {}
                    for _, host_mappings in ports.items():
                        if host_mappings and len(host_mappings) > 0:
                            mapped = host_mappings[0].get("HostPort")
                            if mapped:
                                service_port = str(mapped)
                                break
                    if service_port is None and host_port is not None:
                        service_port = str(host_port)
                if service_port:
                    host = self._get_service_host(container_name)
                    service_url = f"http://{host}:{service_port}/mcp"
                    logger.info(
                        f"Using existing container {container_name} on port {service_port}"
                    )
                    return {
                        "container_id": existing.id,
                        "service_url": service_url,
                        "host_port": service_port,
                        "status": "existing",
                        "container_name": container_name,
                    }
            # Remove existing stopped container
            logger.info(
                f"Removing existing stopped container {container_name}")
            existing.remove(force=True)
        except NotFound:
            pass
        except Exception as e:
            logger.warning(f"Error checking existing container: {e}")

        # Find free port
        if host_port is None:
            if DockerContainerClient._is_running_in_docker():
                # Inside Docker we do not need to publish host ports; use a stable default.
                host_port = 5020
            else:
                try:
                    host_port = self.find_free_port()
                except ContainerError as e:
                    logger.error(f"Failed to find free port: {e}")
                    raise

        # Prepare environment variables
        container_env = {
            "PORT": str(host_port),
            "TRANSPORT": "streamable-http",
            "NODE_ENV": "production",
        }
        if env_vars:
            container_env.update(env_vars)

        # Determine image name
        command0 = full_command[0] if full_command else ""
        if image is not None:
            image_name = image
        elif command0 in ["npx", "node", "npm"]:
            image_name = "node:22-alpine"
        else:
            image_name = "alpine:latest"

        full_command_to_run = full_command

        container_config = {
            "image": image_name,
            "name": container_name,
            "environment": container_env,
            "network": self.DEFAULT_NETWORK_NAME,
            "restart_policy": {"Name": "unless-stopped"},
            "detach": True,
            "remove": False,
            "stdin_open": True,  # Keep stdin open for stdio-based services
            "tty": False,
        }

        # Only set command if full_command is provided
        if full_command_to_run:
            container_config["command"] = full_command_to_run

        # Only publish ports when running locally; inside Docker network DNS is used.
        if not DockerContainerClient._is_running_in_docker():
            container_config["ports"] = {f"{host_port}/tcp": host_port}

        try:
            if full_command_to_run:
                logger.info(
                    f"Starting container {container_name} with command: {full_command_to_run}")
            else:
                logger.info(
                    f"Starting container {container_name} with default image CMD/ENTRYPOINT")
            container = self.client.containers.run(**container_config)

            # Wait a bit for container to start
            await asyncio.sleep(2)

            # Wait for service to be ready
            host = self._get_service_host(container_name)
            service_url = f"http://{host}:{host_port}/mcp"
            try:
                await self._wait_for_service_ready(service_url, max_retries=30)
            except ContainerConnectionError:
                # If health check fails, log but don't fail immediately
                logger.warning(
                    f"Service health check failed for {service_url}, but container is running"
                )
                # Check if container is still running
                try:
                    container.reload()
                    if container.status != "running":
                        raise ContainerError(
                            f"Container {container_name} stopped unexpectedly")
                except NotFound:
                    raise ContainerError(
                        f"Container {container_name} not found after start")

            logger.info(
                f"Container {container_name} started successfully on port {host_port}")
            return {
                "container_id": container.id,
                "service_url": service_url,
                "host_port": str(host_port),
                "status": "started",
                "container_name": container_name,
            }
        except APIError as e:
            logger.error(f"Docker API error starting container: {e}")
            raise ContainerError(f"Container startup failed: {e}")
        except Exception as e:
            logger.error(f"Failed to start container: {e}")
            raise ContainerError(f"Container startup failed: {e}")

    async def _wait_for_service_ready(
        self, url: str, max_retries: int = 30, retry_delay: int = 5
    ):
        """
        Wait for service to be ready by checking connection

        Args:
            url: Service URL
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Raises:
            ContainerConnectionError: If service is not ready after max retries
        """
        for i in range(max_retries):
            try:
                client = Client(url)
                async with client:
                    if client.is_connected():
                        logger.info(f"Service ready at {url}")
                        return
                    # If not connected, treat as failure
                    if i < max_retries - 1:
                        logger.debug(
                            f"Service not ready yet (attempt {i+1}/{max_retries}): not connected")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(
                            f"Service not ready after {max_retries} attempts: not connected")
                        raise ContainerConnectionError(
                            f"Service not ready after {max_retries * retry_delay} seconds: not connected"
                        )
            except BaseException as e:
                if i < max_retries - 1:
                    logger.debug(
                        f"Service not ready yet (attempt {i+1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(
                        f"Service not ready after {max_retries} attempts: {e}", exc_info=True
                    )
                    raise ContainerConnectionError(
                        f"Service not ready after {max_retries * retry_delay} seconds: {e}"
                    )

    async def stop_container(self, container_id: str) -> bool:
        """
        Stop container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was stopped successfully, False if not found

        Raises:
            ContainerError: If container stop fails
        """
        try:
            container = self.client.containers.get(container_id)
            logger.info(
                f"Stopping container {container.name} ({container.id})")
            container.stop(timeout=10)
            logger.info(f"Container {container.name} stopped")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return False
        except APIError as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            raise ContainerError(f"Failed to stop container: {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error stopping container {container_id}: {e}")
            raise ContainerError(f"Failed to stop container: {e}")

    async def remove_container(self, container_id: str) -> bool:
        """
        Remove container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was removed successfully, False if not found

        Raises:
            ContainerError: If container removal fails
        """
        try:
            container = self.client.containers.get(container_id)
            logger.info(
                f"Removing container {container.name} ({container.id})")
            container.remove()
            logger.info(f"Container {container.name} removed")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return False
        except APIError as e:
            logger.error(f"Failed to remove container {container_id}: {e}")
            raise ContainerError(f"Failed to remove container: {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error removing container {container_id}: {e}")
            raise ContainerError(f"Failed to remove container: {e}")

    def list_containers(
        self, tenant_id: Optional[str] = None, service_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all containers, optionally filtered by tenant or service

        Args:
            tenant_id: Optional tenant ID to filter containers
            service_name: Optional service name to filter containers

        Returns:
            List of container information dictionaries
        """
        try:
            containers = self.client.containers.list(
                all=True, filters={"name": "mcp-"})
            result = []
            for container in containers:
                # Filter by tenant_id if provided
                if tenant_id and tenant_id[:8] not in container.name:
                    continue

                # Filter by service_name if provided
                if service_name:
                    safe_name = "".join(
                        c if c.isalnum() or c == "-" else "-" for c in service_name
                    )
                    if safe_name not in container.name:
                        continue

                ports = container.attrs.get(
                    "NetworkSettings", {}).get("Ports", {})
                host_port = None
                for port_mappings in ports.values():
                    if port_mappings and len(port_mappings) > 0:
                        host_port = port_mappings[0].get("HostPort")
                        if host_port:
                            break

                service_port = None
                if DockerContainerClient._is_running_in_docker():
                    service_port = self._get_container_service_port(container)
                else:
                    service_port = host_port

                host = self._get_service_host(container.name)
                result.append(
                    {
                        "container_id": container.id,
                        "name": container.name,
                        "status": container.status,
                        "service_url": (
                            f"http://{host}:{service_port}/mcp" if service_port else None
                        ),
                        "host_port": service_port,
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Failed to list containers: {e}")
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
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail, stdout=True, stderr=True)
            return logs.decode("utf-8", errors="replace")
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return ""
        except Exception as e:
            logger.error(f"Failed to get container logs: {e}")
            return f"Error retrieving logs: {e}"

    def get_container_status(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get container status information

        Args:
            container_id: Container ID or name

        Returns:
            Dictionary with container status information, or None if not found
        """
        try:
            container = self.client.containers.get(container_id)
            ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            host_port = None
            for port_mappings in ports.values():
                if port_mappings and len(port_mappings) > 0:
                    host_port = port_mappings[0].get("HostPort")
                    if host_port:
                        break

            service_port = None
            if DockerContainerClient._is_running_in_docker():
                service_port = self._get_container_service_port(container)
            else:
                service_port = host_port

            host = self._get_service_host(container.name)
            return {
                "container_id": container.id,
                "name": container.name,
                "status": container.status,
                "service_url": (
                    f"http://{host}:{service_port}/mcp" if service_port else None
                ),
                "host_port": service_port,
                "created": container.attrs.get("Created"),
                "image": container.attrs.get("Config", {}).get("Image"),
            }
        except NotFound:
            return None
        except Exception as e:
            logger.error(f"Failed to get container status: {e}")
            return None
