"""
Docker container configuration
"""

import os
import sys
from typing import Optional

from .container_client_base import ContainerConfig


class DockerContainerConfig(ContainerConfig):
    """Docker container configuration"""

    def __init__(
        self,
        docker_socket_path: Optional[str] = None,
    ):
        """
        Initialize Docker configuration

        Args:
            docker_socket_path: Path to Docker socket (Unix) or named pipe (Windows)
        """
        self._docker_socket_path = docker_socket_path
        self._base_url = None

    @property
    def container_type(self) -> str:
        """Get container type"""
        return "docker"

    @property
    def base_url(self) -> str:
        """Get Docker base URL"""
        if self._base_url:
            return self._base_url

        socket_path = self._docker_socket_path or self._get_default_socket_path()
        self._base_url = self._normalize_base_url(socket_path)
        return self._base_url

    def _get_default_socket_path(self) -> str:
        """Get default Docker socket path based on OS"""
        if sys.platform.startswith("win"):
            return "//./pipe/docker_engine"
        return "/var/run/docker.sock"

    def _normalize_base_url(self, value: str) -> str:
        """Normalize Docker base URL to include scheme for different platforms"""
        if value and "://" in value:
            return value

        # Windows: prefer named pipe
        if sys.platform.startswith("win"):
            if not value:
                return "npipe:////./pipe/docker_engine"
            if value.startswith("//./pipe/") or value.startswith(r"\\.\\pipe\\"):
                return f"npipe://{value}"
            return f"npipe://{value}"

        # Unix-like: use unix socket
        if not value:
            return "unix:///var/run/docker.sock"
        if value.startswith("/"):
            return f"unix://{value}"
        return value

    def validate(self) -> None:
        """
        Validate configuration parameters

        Raises:
            ValueError: If configuration is invalid
        """
        # Configuration is always valid as we have defaults
        pass

