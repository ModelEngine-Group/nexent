"""
Abstract base classes for container clients and configurations

Defines the common interfaces that all container implementations must follow.

This design allows for multiple container backends:
- Docker: Direct Docker daemon access (current implementation)
- Kubernetes: K8s Pod/Deployment management (future implementation)

To implement a new container backend:
1. Create a config class inheriting from ContainerConfig
2. Create a client class inheriting from ContainerClient
3. Implement all abstract methods
4. Register in container_client_factory.py
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ContainerConfig(ABC):
    """Abstract container configuration base class"""

    @property
    @abstractmethod
    def container_type(self) -> str:
        """Get container type"""
        pass

    @abstractmethod
    def validate(self) -> None:
        """
        Validate configuration parameters

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        pass


class ContainerClient(ABC):
    """
    Abstract base class for container clients

    All container implementations must inherit from this class and implement
    all abstract methods.
    """

    @abstractmethod
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
        Start a container and return access information

        This method should be implemented to start a container/pod based on the
        backend type. For Docker, this starts a container. For Kubernetes, this
        would create a Pod or Deployment.

        Args:
            service_name: Name of the service
            tenant_id: Tenant ID for isolation (used for namespace/labeling)
            user_id: User ID for isolation (used for labeling/naming)
            full_command: Optional complete command list to run inside container (must start an HTTP endpoint).
                         If None, uses the image's default CMD/ENTRYPOINT.
            env_vars: Optional environment variables
            host_port: Optional host port to bind (if None, auto assign)
            image: Optional image override

        Returns:
            Dictionary with container_id (or pod_id for k8s), service_url,
            host_port (or service port for k8s), and status

        Raises:
            ContainerError: If container startup fails
        """
        pass

    @abstractmethod
    async def stop_container(self, container_id: str) -> bool:
        """
        Stop a container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was stopped successfully, False if not found

        Raises:
            ContainerError: If container stop fails
        """
        pass

    @abstractmethod
    async def remove_container(self, container_id: str) -> bool:
        """
        Remove a container

        Args:
            container_id: Container ID or name

        Returns:
            True if container was removed successfully, False if not found

        Raises:
            ContainerError: If container removal fails
        """
        pass

    @abstractmethod
    def list_containers(
        self, tenant_id: Optional[str] = None, service_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all containers, optionally filtered by tenant or service

        For Docker: Lists containers with matching labels
        For Kubernetes: Lists pods/deployments in namespace with matching labels

        Args:
            tenant_id: Optional tenant ID to filter containers
            service_name: Optional service name to filter containers

        Returns:
            List of container information dictionaries with keys:
            - container_id (or pod_id for k8s)
            - name
            - status
            - service_url (optional)
            - host_port (optional)
        """
        pass

    @abstractmethod
    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """
        Get container logs

        Args:
            container_id: Container ID or name
            tail: Number of log lines to retrieve

        Returns:
            Container logs as string
        """
        pass

    @abstractmethod
    def get_container_status(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get container status information

        Args:
            container_id: Container ID or name

        Returns:
            Dictionary with container status information, or None if not found
        """
        pass

