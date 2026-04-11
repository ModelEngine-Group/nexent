"""
MCP Container Service - Wrapper around SDK container management

This module provides a compatibility layer for the existing MCPContainerManager
interface while using the standardized SDK container management module.
"""

import logging
import asyncio
import threading
from typing import Dict, List, Optional, AsyncGenerator

from consts.exceptions import MCPConnectionError, MCPContainerError
from consts.const import IS_DEPLOYED_BY_KUBERNETES, KUBERNETES_NAMESPACE
from nexent.container import (
    DockerContainerConfig,
    KubernetesContainerConfig,
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

    def __init__(self, docker_socket_path: Optional[str] = None):
        """
        Initialize container manager using SDK

        Args:
            docker_socket_path: Path to Docker socket. If None, uses platform default.
                For container access, mount docker socket: -v /var/run/docker.sock:/var/run/docker.sock
                Only used when running in Docker mode.
        """
        try:
            if IS_DEPLOYED_BY_KUBERNETES:
                logger.info("Initializing Kubernetes container client")
                config = KubernetesContainerConfig(
                    namespace=KUBERNETES_NAMESPACE,
                    in_cluster=True,
                )
            else:
                logger.info("Initializing Docker container client")
                config = DockerContainerConfig(
                    docker_socket_path=docker_socket_path
                )
            self.client = create_container_client_from_config(config)
            logger.info(
                f"MCPContainerManager initialized using SDK container module (type: {'kubernetes' if IS_DEPLOYED_BY_KUBERNETES else 'docker'})")
        except ContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise MCPContainerError(f"Cannot connect to container runtime: {e}")

    async def load_image_from_tar_file(self, tar_file_path: str) -> str:
        """
        Load Docker image from tar file

        Args:
            tar_file_path: Path to the tar file containing the Docker image

        Returns:
            Image name/tag that was loaded

        Raises:
            MCPContainerError: If image loading fails
        """
        try:
            # Load image from tar file
            with open(tar_file_path, 'rb') as tar_file:
                images = self.client.client.images.load(tar_file.read())

            if not images:
                raise MCPContainerError("No images found in tar file")

            # Get the first loaded image
            loaded_image = images[0]
            image_name = loaded_image.tags[0] if loaded_image.tags else str(
                loaded_image.id)

        except Exception as e:
            logger.error(f"Failed to load image from tar file: {e}")
            raise MCPContainerError(f"Failed to load image from tar file: {e}")
        logger.info(f"Successfully loaded image: {image_name}")
        return image_name

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
            env_vars: Optional environment variables (may contain authorization_token)

        Returns:
            Dictionary with container_id, mcp_url, host_port, and status

        Raises:
            MCPContainerError: If container startup fails
        """
        try:
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
                # Map service_url to mcp_url for compatibility
                "mcp_url": result["service_url"],
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

    async def start_mcp_container_from_tar(
        self,
        tar_file_path: str,
        service_name: str,
        tenant_id: str,
        user_id: str,
        env_vars: Optional[Dict[str, str]] = None,
        host_port: Optional[int] = None,
        full_command: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Load image from tar file and start MCP container

        Args:
            tar_file_path: Path to the tar file containing the Docker image
            service_name: Name of the MCP service
            tenant_id: Tenant ID for isolation
            user_id: User ID for isolation
            env_vars: Optional environment variables (may contain authorization_token)
            host_port: Optional host port to bind
            full_command: Optional command to run in container

        Returns:
            Dictionary with container_id, mcp_url, host_port, and status

        Raises:
            MCPContainerError: If container startup fails
        """
        try:
            # Load image from tar file
            image_name = await self.load_image_from_tar_file(tar_file_path)

            # Start container with the loaded image
            return await self.start_mcp_container(
                service_name=service_name,
                tenant_id=tenant_id,
                user_id=user_id,
                env_vars=env_vars,
                host_port=host_port,
                image=image_name,
                full_command=full_command,
            )

        except Exception as e:
            logger.error(f"Failed to start MCP container from tar file: {e}")
            raise MCPContainerError(
                f"Failed to start container from tar file: {e}")

    async def stop_mcp_container(self, container_id: str) -> bool:
        """
        Stop and remove MCP container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was stopped and removed successfully

        Raises:
            MCPContainerError: If container stop or removal fails
        """
        try:
            # First stop the container
            stop_result = await self.client.stop_container(container_id)
            if not stop_result:
                return False

            # Then remove the container
            remove_result = await self.client.remove_container(container_id)
            return remove_result
        except ContainerError as e:
            logger.error(f"Failed to stop or remove container: {e}")
            raise MCPContainerError(f"Failed to stop container: {e}")

    async def stop_mcp_container_only(self, container_id: str) -> bool:
        """
        Stop MCP container without removing it.

        Args:
            container_id: Container ID or name

        Returns:
            True if container was stopped, False if not found

        Raises:
            MCPContainerError: If container stop fails
        """
        try:
            return await self.client.stop_container(container_id)
        except ContainerError as e:
            logger.error(f"Failed to stop container: {e}")
            raise MCPContainerError(f"Failed to stop container: {e}")

    async def remove_mcp_container(self, container_id: str) -> bool:
        """
        Remove MCP container without stopping logic.

        Args:
            container_id: Container ID or name

        Returns:
            True if container was removed, False if not found

        Raises:
            MCPContainerError: If container removal fails
        """
        try:
            return await self.client.remove_container(container_id)
        except ContainerError as e:
            logger.error(f"Failed to remove container: {e}")
            raise MCPContainerError(f"Failed to remove container: {e}")

    async def start_existing_mcp_container(self, container_id: str) -> Dict[str, str]:
        """
        Start an existing container by container ID and return runtime access fields.

        Args:
            container_id: Existing container ID or name

        Returns:
            Dictionary with container_id, mcp_url, host_port, status, container_name

        Raises:
            MCPContainerError: If startup fails or runtime info cannot be resolved
        """
        try:
            # SDK Docker client exposes the native docker client as `client`.
            container = self.client.client.containers.get(container_id)
            container.start()
            container.reload()
            if container.status != "running":
                raise MCPContainerError(
                    f"Container {container_id} is not running after start: {container.status}"
                )

            status = self.client.get_container_status(container_id)
            if not status:
                raise MCPContainerError("Container status is unavailable after start")

            return {
                "container_id": status.get("container_id") or container.id,
                "mcp_url": status.get("service_url") or "",
                "host_port": status.get("host_port") or "",
                "status": status.get("status") or "running",
                "container_name": status.get("name") or container.name,
            }
        except ContainerError as e:
            logger.error(f"Failed to start existing container: {e}")
            raise MCPContainerError(f"Failed to start existing container: {e}")
        except Exception as e:
            logger.error(f"Failed to start existing container: {e}")
            raise MCPContainerError(f"Failed to start existing container: {e}")

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

    async def stream_container_logs(
        self, container_id: str, tail: int = 100, follow: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Stream container logs in real-time

        Args:
            container_id: Container ID or name
            tail: Number of log lines to retrieve initially
            follow: Whether to follow logs (stream new logs as they appear)

        Yields:
            Log lines as strings
        """
        try:
            if IS_DEPLOYED_BY_KUBERNETES:
                # Kubernetes mode: use SDK's read_namespaced_pod_log with follow
                namespace = KUBERNETES_NAMESPACE
                # Resolve container_id (UID) to actual Pod name
                pod_name = self.client._resolve_pod_name(container_id)
                if not pod_name:
                    logger.warning(f"Pod {container_id} not found")
                    return

                # First, get initial logs
                initial_logs = self.client.get_container_logs(container_id, tail=tail)
                if initial_logs:
                    for line in initial_logs.splitlines():
                        if line.strip():
                            yield line

                if follow:
                    # Use Kubernetes log API with follow=True in background thread
                    # (same pattern as Docker)
                    loop = asyncio.get_event_loop()
                    log_queue = asyncio.Queue()
                    stop_flag = [False]

                    def _stream_logs_sync():
                        """Run blocking Kubernetes log stream in thread"""
                        try:
                            # Kubernetes log API with follow=True returns a generator
                            log_stream = self.client.core_v1.read_namespaced_pod_log(
                                name=pod_name,
                                namespace=namespace,
                                container="mcp-server",
                                follow=True,
                                timestamps=False,
                                _preload_content=False,
                                tail_lines=0,  # Only new logs after initial batch
                            )
                            for log_line in log_stream:
                                if stop_flag[0]:
                                    break
                                # Kubernetes API returns bytes, decode to string
                                if isinstance(log_line, bytes):
                                    log_line = log_line.decode("utf-8", errors="replace")
                                # Strip trailing newline (Kubernetes API adds \n per line)
                                if log_line.strip():
                                    asyncio.run_coroutine_threadsafe(
                                        log_queue.put(log_line.rstrip("\n")), loop
                                    )
                            # Signal end of stream
                            asyncio.run_coroutine_threadsafe(
                                log_queue.put(None), loop
                            )
                        except Exception as e:
                            logger.error(f"Error in Kubernetes log stream thread: {e}")
                            asyncio.run_coroutine_threadsafe(
                                log_queue.put(None), loop
                            )

                    # Start streaming in background thread
                    stream_thread = threading.Thread(
                        target=_stream_logs_sync, daemon=True
                    )
                    stream_thread.start()

                    # Process log lines from queue
                    try:
                        while True:
                            log_line = await log_queue.get()
                            if log_line is None:  # End of stream signal
                                break
                            if log_line.strip():
                                yield log_line
                    finally:
                        stop_flag[0] = True
            else:
                # Docker mode: use native Docker API for streaming
                container = self.client.client.containers.get(container_id)
                loop = asyncio.get_event_loop()

                # First, get initial logs in a thread pool to avoid blocking
                initial_logs = await loop.run_in_executor(
                    None,
                    lambda: container.logs(
                        tail=tail, stdout=True, stderr=True, timestamps=False
                    )
                )
                if initial_logs:
                    decoded = initial_logs.decode("utf-8", errors="replace")
                    for line in decoded.splitlines():
                        if line.strip():  # Only yield non-empty lines
                            yield line

                # Then, if follow is True, stream new logs
                if follow:
                    # Create a queue to pass log chunks from thread to async generator
                    log_queue = asyncio.Queue()
                    # Use list to allow modification from nested function
                    stop_flag = [False]

                    def _stream_logs_sync():
                        """Run blocking log stream in thread"""
                        try:
                            log_stream = container.logs(
                                stdout=True,
                                stderr=True,
                                follow=True,
                                stream=True,
                                timestamps=False,
                                tail=0,  # Only new logs
                            )
                            for log_chunk in log_stream:
                                if stop_flag[0]:
                                    break
                                # Put chunks in queue (will be processed in async context)
                                asyncio.run_coroutine_threadsafe(
                                    log_queue.put(log_chunk), loop
                                )
                            # Signal end of stream
                            asyncio.run_coroutine_threadsafe(
                                log_queue.put(None), loop
                            )
                        except Exception as e:
                            logger.error(f"Error in log stream thread: {e}")
                            asyncio.run_coroutine_threadsafe(
                                log_queue.put(None), loop
                            )

                    # Start streaming in background thread
                    stream_thread = threading.Thread(
                        target=_stream_logs_sync, daemon=True)
                    stream_thread.start()

                    # Process log chunks from queue
                    try:
                        while True:
                            log_chunk = await log_queue.get()
                            if log_chunk is None:  # End of stream signal
                                break
                            decoded = log_chunk.decode("utf-8", errors="replace")
                            # Split by newlines and yield each line
                            for line in decoded.splitlines():
                                if line.strip():  # Only yield non-empty lines
                                    yield line
                    finally:
                        stop_flag[0] = True
        except Exception as e:
            logger.error(f"Failed to stream container logs: {e}")
            yield f"Error retrieving logs: {e}"
