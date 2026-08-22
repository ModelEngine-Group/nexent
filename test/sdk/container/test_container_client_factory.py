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
from nexent.container.k8s_config import KubernetesContainerConfig
from nexent.container.k8s_client import KubernetesContainerClient


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
        config = DockerContainerConfig(docker_socket_path="tcp://localhost:2375")

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

            async def remove_container(self, container_id):
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


# ---------------------------------------------------------------------------
# Test Kubernetes container client registration and creation
# ---------------------------------------------------------------------------


class TestKubernetesContainerClient:
    """Test Kubernetes container client registration and creation"""

    def test_kubernetes_config_properties(self):
        """Test KubernetesContainerConfig properties"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            kubeconfig_path="/path/to/kubeconfig",
            in_cluster=True,
            service_port=8080,
        )

        assert config.container_type == "kubernetes"
        assert config.namespace == "test-namespace"
        assert config.kubeconfig_path == "/path/to/kubeconfig"
        assert config.in_cluster is True
        assert config.service_port == 8080

    def test_kubernetes_config_default_values(self):
        """Test KubernetesContainerConfig default values"""
        config = KubernetesContainerConfig()

        assert config.container_type == "kubernetes"
        assert config.namespace == "nexent"
        assert config.kubeconfig_path is None
        assert config.in_cluster is False
        assert config.service_port == 5020

    def test_kubernetes_config_validate_empty_namespace(self):
        """Test KubernetesContainerConfig validation with empty namespace"""
        config = KubernetesContainerConfig(namespace="")

        with pytest.raises(ValueError, match="Kubernetes namespace is required"):
            config.validate()

    def test_kubernetes_client_registered(self):
        """Test that Kubernetes client is pre-registered"""
        from nexent.container.container_client_factory import _CONTAINER_CLIENT_REGISTRY

        assert "kubernetes" in _CONTAINER_CLIENT_REGISTRY
        config_class, client_class = _CONTAINER_CLIENT_REGISTRY["kubernetes"]
        assert config_class == KubernetesContainerConfig
        assert client_class == KubernetesContainerClient

    def test_create_container_client_with_k8s_config(self):
        """Test creating container client with Kubernetes config"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            kubeconfig_path="mock-kubeconfig-content",
            in_cluster=False,
        )

        with patch("nexent.container.k8s_client.kubernetes.config.load_kube_config_from_dict"):
            with patch("nexent.container.k8s_client.client.CoreV1Api") as mock_core_api:
                with patch("nexent.container.k8s_client.client.AppsV1Api") as mock_apps_api:
                    mock_core_api_instance = MagicMock()
                    mock_core_api.return_value = mock_core_api_instance

                    # Mock the list_namespaced_pod call in __init__
                    mock_core_api_instance.list_namespaced_pod.return_value = MagicMock(items=[])

                    client = create_container_client_from_config(config)

                    assert isinstance(client, KubernetesContainerClient)
                    assert client.config == config
                    mock_core_api.assert_called_once()
                    mock_apps_api.assert_called_once()

    def test_create_container_client_k8s_in_cluster(self):
        """Test creating container client with in-cluster Kubernetes config"""
        config = KubernetesContainerConfig(
            namespace="prod-namespace",
            in_cluster=True,
        )

        with patch("nexent.container.k8s_client.kubernetes.config.load_incluster_config") as mock_load_incluster:
            with patch("nexent.container.k8s_client.client.CoreV1Api") as mock_core_api:
                with patch("nexent.container.k8s_client.client.AppsV1Api") as mock_apps_api:
                    mock_core_api_instance = MagicMock()
                    mock_core_api.return_value = mock_core_api_instance
                    mock_core_api_instance.list_namespaced_pod.return_value = MagicMock(items=[])

                    client = create_container_client_from_config(config)

                    assert isinstance(client, KubernetesContainerClient)
                    mock_load_incluster.assert_called_once()

    def test_kubernetes_client_creation_fails_on_invalid_connection(self):
        """Test that Kubernetes client creation raises error on connection failure"""
        config = KubernetesContainerConfig(
            namespace="test-ns",
            kubeconfig_path="invalid-content",
        )

        with patch("nexent.container.k8s_client.kubernetes.config.load_kube_config_from_dict"):
            with patch("nexent.container.k8s_client.client.CoreV1Api") as mock_core_api:
                mock_core_api.side_effect = Exception("Connection failed")

                from nexent.container.k8s_client import ContainerError

                with pytest.raises(ContainerError, match="Cannot connect to Kubernetes"):
                    KubernetesContainerClient(config)

