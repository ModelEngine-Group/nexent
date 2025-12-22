"""
Unit tests for container_client_factory.py
Tests the container client factory functions
"""

import pytest
from unittest.mock import MagicMock, patch

from nexent.container.container_client_factory import (
    create_container_client_from_config,
    register_container_client,
)
from nexent.container.container_client_base import ContainerClient, ContainerConfig
from nexent.container.docker_config import DockerContainerConfig
from nexent.container.docker_client import DockerContainerClient


# ---------------------------------------------------------------------------
# Test register_container_client
# ---------------------------------------------------------------------------


class TestRegisterContainerClient:
    """Test register_container_client function"""

    def test_register_container_client(self):
        """Test registering a container client"""
        # Create mock config and client classes
        class MockConfig(ContainerConfig):
            @property
            def container_type(self):
                return "mock"

            def validate(self):
                pass

        class MockClient(ContainerClient):
            def __init__(self, config):
                self.config = config

            async def start_container(self, *args, **kwargs):
                pass

            async def stop_container(self, container_id):
                pass

            async def remove_container(self, container_id):
                pass

            def list_containers(self, tenant_id=None, service_name=None):
                pass

            def get_container_logs(self, container_id, tail=100):
                pass

            def get_container_status(self, container_id):
                pass

        # Register the mock client
        register_container_client(MockConfig, MockClient)

        # Verify it was registered
        from nexent.container.container_client_factory import _CONTAINER_CLIENT_REGISTRY
        assert "mock" in _CONTAINER_CLIENT_REGISTRY
        assert _CONTAINER_CLIENT_REGISTRY["mock"] == (MockConfig, MockClient)

    def test_register_container_client_overwrite(self):
        """Test that registering the same type overwrites previous registration"""
        class MockConfig1(ContainerConfig):
            @property
            def container_type(self):
                return "test-type"

            def validate(self):
                pass

        class MockClient1(ContainerClient):
            def __init__(self, config):
                self.config = config

            async def start_container(self, *args, **kwargs):
                pass

            async def stop_container(self, container_id):
                pass

            def list_containers(self, tenant_id=None, service_name=None):
                pass

            def get_container_logs(self, container_id, tail=100):
                pass

            def get_container_status(self, container_id):
                pass

        class MockConfig2(ContainerConfig):
            @property
            def container_type(self):
                return "test-type"

            def validate(self):
                pass

        class MockClient2(ContainerClient):
            def __init__(self, config):
                self.config = config

            async def start_container(self, *args, **kwargs):
                pass

            async def stop_container(self, container_id):
                pass

            def list_containers(self, tenant_id=None, service_name=None):
                pass

            def get_container_logs(self, container_id, tail=100):
                pass

            def get_container_status(self, container_id):
                pass

        # Register first client
        register_container_client(MockConfig1, MockClient1)

        # Register second client with same type
        register_container_client(MockConfig2, MockClient2)

        # Verify it was overwritten
        from nexent.container.container_client_factory import _CONTAINER_CLIENT_REGISTRY
        assert _CONTAINER_CLIENT_REGISTRY["test-type"] == (MockConfig2, MockClient2)


# ---------------------------------------------------------------------------
# Test create_container_client_from_config
# ---------------------------------------------------------------------------


class TestCreateContainerClientFromConfig:
    """Test create_container_client_from_config function"""

    def test_create_container_client_with_docker_config(self):
        """Test creating container client with Docker config"""
        config = DockerContainerConfig(docker_host="tcp://localhost:2375")

        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_client = MagicMock()
            mock_docker_client.ping.return_value = True
            mock_docker_class.return_value = mock_docker_client

            client = create_container_client_from_config(config)

            assert isinstance(client, DockerContainerClient)
            mock_docker_class.assert_called_once()

    def test_create_container_client_with_none(self):
        """Test creating container client with None config (defaults to Docker)"""
        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_client = MagicMock()
            mock_docker_client.ping.return_value = True
            mock_docker_class.return_value = mock_docker_client

            client = create_container_client_from_config(None)

            assert isinstance(client, DockerContainerClient)
            mock_docker_class.assert_called_once()

    def test_create_container_client_unsupported_type(self):
        """Test creating container client with unsupported type"""
        class UnsupportedConfig(ContainerConfig):
            @property
            def container_type(self):
                return "unsupported"

            def validate(self):
                pass

        config = UnsupportedConfig()

        with pytest.raises(ValueError, match="Unsupported container type"):
            create_container_client_from_config(config)

    def test_create_container_client_custom_type(self):
        """Test creating container client with custom registered type"""
        class CustomConfig(ContainerConfig):
            @property
            def container_type(self):
                return "custom"

            def validate(self):
                pass

        class CustomClient(ContainerClient):
            def __init__(self, config):
                self.config = config

            async def start_container(self, *args, **kwargs):
                return {}

            async def stop_container(self, container_id):
                return True

            def list_containers(self, tenant_id=None, service_name=None):
                return []

            def get_container_logs(self, container_id, tail=100):
                return ""

            def get_container_status(self, container_id):
                return None

        # Register custom client
        register_container_client(CustomConfig, CustomClient)

        config = CustomConfig()
        client = create_container_client_from_config(config)

        assert isinstance(client, CustomClient)
        assert client.config == config

    def test_create_container_client_docker_default(self):
        """Test that Docker is the default when no config provided"""
        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_client = MagicMock()
            mock_docker_client.ping.return_value = True
            mock_docker_class.return_value = mock_docker_client

            client = create_container_client_from_config()

            assert isinstance(client, DockerContainerClient)

    def test_create_container_client_docker_registered(self):
        """Test that Docker client is pre-registered"""
        from nexent.container.container_client_factory import _CONTAINER_CLIENT_REGISTRY

        assert "docker" in _CONTAINER_CLIENT_REGISTRY
        config_class, client_class = _CONTAINER_CLIENT_REGISTRY["docker"]
        assert config_class == DockerContainerConfig
        assert client_class == DockerContainerClient

