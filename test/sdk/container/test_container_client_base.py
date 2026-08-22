"""
Unit tests for container_client_base.py
Tests the abstract base classes
"""

import pytest
from abc import ABC

from nexent.container.container_client_base import ContainerClient, ContainerConfig


# ---------------------------------------------------------------------------
# Test ContainerConfig
# ---------------------------------------------------------------------------


class TestContainerConfig:
    """Test ContainerConfig abstract base class"""

    def test_container_config_is_abstract(self):
        """Test that ContainerConfig cannot be instantiated directly"""
        with pytest.raises(TypeError):
            ContainerConfig()

    def test_container_config_has_abstract_methods(self):
        """Test that ContainerConfig has required abstract methods"""
        # Check that container_type is abstract
        assert hasattr(ContainerConfig, "container_type")
        assert hasattr(ContainerConfig, "validate")

    def test_container_config_subclass_must_implement_methods(self):
        """Test that subclass must implement all abstract methods"""
        class IncompleteConfig(ContainerConfig):
            pass

        with pytest.raises(TypeError):
            IncompleteConfig()


# ---------------------------------------------------------------------------
# Test ContainerClient
# ---------------------------------------------------------------------------


class TestContainerClient:
    """Test ContainerClient abstract base class"""

    def test_container_client_is_abstract(self):
        """Test that ContainerClient cannot be instantiated directly"""
        with pytest.raises(TypeError):
            ContainerClient()

    def test_container_client_has_abstract_methods(self):
        """Test that ContainerClient has required abstract methods"""
        assert hasattr(ContainerClient, "start_container")
        assert hasattr(ContainerClient, "stop_container")
        assert hasattr(ContainerClient, "remove_container")
        assert hasattr(ContainerClient, "list_containers")
        assert hasattr(ContainerClient, "get_container_logs")
        assert hasattr(ContainerClient, "get_container_status")

    def test_container_client_subclass_must_implement_methods(self):
        """Test that subclass must implement all abstract methods"""
        class IncompleteClient(ContainerClient):
            pass

        with pytest.raises(TypeError):
            IncompleteClient()

    def test_container_client_is_abc(self):
        """Test that ContainerClient is an ABC"""
        assert issubclass(ContainerClient, ABC)

    def test_container_config_is_abc(self):
        """Test that ContainerConfig is an ABC"""
        assert issubclass(ContainerConfig, ABC)

