"""
Factory for creating container clients from configuration

This factory supports multiple container backends (Docker, Kubernetes, etc.)
through a registration-based system. To add a new backend:

1. Create a config class inheriting from ContainerConfig
2. Create a client class inheriting from ContainerClient
3. Register them using register_container_client()
"""

from typing import Dict, Optional, Tuple, Type

from .container_client_base import ContainerClient, ContainerConfig
from .docker_client import DockerContainerClient
from .docker_config import DockerContainerConfig

# Registry mapping container_type to (config_class, client_class)
_CONTAINER_CLIENT_REGISTRY: Dict[str, Tuple[Type[ContainerConfig], Type[ContainerClient]]] = {}


def register_container_client(
    config_class: Type[ContainerConfig],
    client_class: Type[ContainerClient],
) -> None:
    """
    Register a container client implementation

    Args:
        config_class: Configuration class for the container type
        client_class: Client class that implements ContainerClient

    Example:
        # For future Kubernetes implementation:
        register_container_client(KubernetesContainerConfig, KubernetesContainerClient)
    """
    container_type = config_class().container_type
    _CONTAINER_CLIENT_REGISTRY[container_type] = (config_class, client_class)


def create_container_client_from_config(
    config: Optional[ContainerConfig] = None,
) -> ContainerClient:
    """
    Create container client from configuration

    Args:
        config: Container configuration. If None, creates default Docker client

    Returns:
        Container client instance

    Raises:
        ValueError: If configuration type is not supported

    Example:
        # Docker
        docker_config = DockerContainerConfig()
        client = create_container_client_from_config(docker_config)

        # Future Kubernetes support:
        # k8s_config = KubernetesContainerConfig(namespace="default")
        # client = create_container_client_from_config(k8s_config)
    """
    if config is None:
        # Default to Docker
        config = DockerContainerConfig()

    container_type = config.container_type

    if container_type not in _CONTAINER_CLIENT_REGISTRY:
        raise ValueError(
            f"Unsupported container type: {container_type}. "
            f"Supported types: {list(_CONTAINER_CLIENT_REGISTRY.keys())}"
        )

    _, client_class = _CONTAINER_CLIENT_REGISTRY[container_type]
    return client_class(config)


# Register Docker implementation
register_container_client(DockerContainerConfig, DockerContainerClient)

