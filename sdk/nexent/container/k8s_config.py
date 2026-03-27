"""
Kubernetes container configuration
"""

from typing import Optional

from .container_client_base import ContainerConfig


class KubernetesContainerConfig(ContainerConfig):
    """Kubernetes container configuration"""

    def __init__(
        self,
        namespace: str = "nexent",
        kubeconfig_path: Optional[str] = None,
        in_cluster: bool = False,
        service_port: int = 5020,
    ):
        """
        Initialize Kubernetes configuration

        Args:
            namespace: Kubernetes namespace for pods and services
            kubeconfig_path: Path to kubeconfig file (None for in-cluster config)
            in_cluster: Whether to use in-cluster config
            service_port: Default service port for MCP servers
        """
        self._namespace = namespace
        self._kubeconfig_path = kubeconfig_path
        self._in_cluster = in_cluster
        self._service_port = service_port

    @property
    def container_type(self) -> str:
        """Get container type"""
        return "kubernetes"

    @property
    def namespace(self) -> str:
        """Get Kubernetes namespace"""
        return self._namespace

    @property
    def kubeconfig_path(self) -> Optional[str]:
        """Get kubeconfig path"""
        return self._kubeconfig_path

    @property
    def in_cluster(self) -> bool:
        """Get in-cluster flag"""
        return self._in_cluster

    @property
    def service_port(self) -> int:
        """Get default service port"""
        return self._service_port

    def validate(self) -> None:
        """
        Validate configuration parameters

        Raises:
            ValueError: If configuration is invalid
        """
        if not self._namespace:
            raise ValueError("Kubernetes namespace is required")
