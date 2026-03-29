"""Tests for KubernetesContainerConfig"""

import pytest

from nexent.container.k8s_config import KubernetesContainerConfig


class TestKubernetesContainerConfigDefaultInit:
    """Test cases for default initialization"""

    def test_default_namespace(self):
        """Test that default namespace is 'nexent'"""
        config = KubernetesContainerConfig()
        assert config.namespace == "nexent"

    def test_default_kubeconfig_path(self):
        """Test that default kubeconfig_path is None"""
        config = KubernetesContainerConfig()
        assert config.kubeconfig_path is None

    def test_default_in_cluster(self):
        """Test that default in_cluster is False"""
        config = KubernetesContainerConfig()
        assert config.in_cluster is False

    def test_default_service_port(self):
        """Test that default service_port is 5020"""
        config = KubernetesContainerConfig()
        assert config.service_port == 5020


class TestKubernetesContainerConfigCustomInit:
    """Test cases for custom initialization"""

    def test_custom_namespace(self):
        """Test custom namespace initialization"""
        config = KubernetesContainerConfig(namespace="custom-ns")
        assert config.namespace == "custom-ns"

    def test_custom_kubeconfig_path(self):
        """Test custom kubeconfig_path initialization"""
        config = KubernetesContainerConfig(kubeconfig_path="/path/to/kubeconfig")
        assert config.kubeconfig_path == "/path/to/kubeconfig"

    def test_custom_in_cluster_true(self):
        """Test custom in_cluster initialization with True"""
        config = KubernetesContainerConfig(in_cluster=True)
        assert config.in_cluster is True

    def test_custom_in_cluster_false(self):
        """Test custom in_cluster initialization with False"""
        config = KubernetesContainerConfig(in_cluster=False)
        assert config.in_cluster is False

    def test_custom_service_port(self):
        """Test custom service_port initialization"""
        config = KubernetesContainerConfig(service_port=8080)
        assert config.service_port == 8080

    def test_all_custom_parameters(self):
        """Test initialization with all custom parameters"""
        config = KubernetesContainerConfig(
            namespace="my-namespace",
            kubeconfig_path="/custom/kubeconfig",
            in_cluster=True,
            service_port=9000,
        )
        assert config.namespace == "my-namespace"
        assert config.kubeconfig_path == "/custom/kubeconfig"
        assert config.in_cluster is True
        assert config.service_port == 9000


class TestKubernetesContainerConfigProperties:
    """Test cases for all properties"""

    def test_container_type_returns_kubernetes(self):
        """Test container_type property returns 'kubernetes'"""
        config = KubernetesContainerConfig()
        assert config.container_type == "kubernetes"

    def test_namespace_property(self):
        """Test namespace property returns correct value"""
        config = KubernetesContainerConfig(namespace="test-ns")
        assert config.namespace == "test-ns"

    def test_kubeconfig_path_property_with_value(self):
        """Test kubeconfig_path property returns set value"""
        config = KubernetesContainerConfig(kubeconfig_path="/path/to/config")
        assert config.kubeconfig_path == "/path/to/config"

    def test_kubeconfig_path_property_none(self):
        """Test kubeconfig_path property returns None when not set"""
        config = KubernetesContainerConfig()
        assert config.kubeconfig_path is None

    def test_in_cluster_property_true(self):
        """Test in_cluster property returns True when set"""
        config = KubernetesContainerConfig(in_cluster=True)
        assert config.in_cluster is True

    def test_in_cluster_property_false(self):
        """Test in_cluster property returns False by default"""
        config = KubernetesContainerConfig()
        assert config.in_cluster is False

    def test_service_port_property(self):
        """Test service_port property returns correct value"""
        config = KubernetesContainerConfig(service_port=7000)
        assert config.service_port == 7000


class TestKubernetesContainerConfigValidate:
    """Test cases for validate method"""

    def test_validate_with_default_namespace(self):
        """Test validate passes with default namespace 'nexent'"""
        config = KubernetesContainerConfig()
        config.validate()

    def test_validate_with_custom_namespace(self):
        """Test validate passes with custom namespace"""
        config = KubernetesContainerConfig(namespace="custom-ns")
        config.validate()

    def test_validate_with_empty_namespace_raises_value_error(self):
        """Test validate raises ValueError when namespace is empty"""
        config = KubernetesContainerConfig(namespace="")
        with pytest.raises(ValueError, match="Kubernetes namespace is required"):
            config.validate()
